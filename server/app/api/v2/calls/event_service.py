import json
import hashlib
from datetime import datetime

from app.extensions import db
from app.models import CallEvent, CallLog, CallSession


def _digits_only(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _phone_matches(value, target):
    left = _digits_only(value)
    right = _digits_only(target)
    if not left or not right:
        return False
    # Accept exact or suffix match to handle country-prefix differences.
    return left == right or left.endswith(right) or right.endswith(left)


def _extract_channel_digits(payload):
    candidates = [
        _value(payload, "Channel", "channel"),
        _value(payload, "DestChannel", "destchannel"),
        _value(payload, "ConnectedLineNum", "connectedlinenum"),
        _value(payload, "CallerIDNum", "calleridnum"),
    ]
    for value in candidates:
        digits = _digits_only(value)
        if digits:
            return digits
    return ""


def _value(payload, *keys):
    for key in keys:
        if key in payload and payload.get(key) not in (None, ""):
            return payload.get(key)
    lowered = {str(k).lower(): v for k, v in payload.items()}
    for key in keys:
        found = lowered.get(str(key).lower())
        if found not in (None, ""):
            return found
    return None


def _resolve_status(event_name, payload):
    event_name = (event_name or "").strip()
    if event_name == "OriginateResponse":
        response = str(_value(payload, "Response", "response") or "").lower()
        reason = str(_value(payload, "Reason", "reason") or "").lower()
        if response == "success":
            return "ringing"
        if reason in {"5", "busy"}:
            return "busy"
        if reason in {"8", "cancel", "canceled"}:
            return "canceled"
        if reason in {"3", "no answer", "no_answer"}:
            return "no_answer"
        return "failed"

    if event_name == "DialBegin":
        return "ringing"
    if event_name in {"BridgeEnter", "BridgeCreate"}:
        return "answered"
    if event_name == "DialEnd":
        dial_status = str(_value(payload, "DialStatus", "dialstatus") or "").upper()
        if dial_status == "ANSWER":
            return "answered"
        if dial_status == "BUSY":
            return "busy"
        if dial_status in {"NOANSWER", "CANCEL", "CHANUNAVAIL", "CONGESTION"}:
            return "no_answer" if dial_status == "NOANSWER" else "failed"
        return None
    if event_name == "Hangup":
        cause_txt = str(_value(payload, "Cause-txt", "CauseTxt", "cause_txt") or "").lower()
        cause = str(_value(payload, "Cause", "cause") or "").lower()
        if "busy" in cause_txt or cause == "17":
            return "busy"
        if "no answer" in cause_txt or cause == "19":
            return "no_answer"
        if "normal clearing" in cause_txt or cause == "16":
            return "completed"
        if "cancel" in cause_txt:
            return "canceled"
        return "failed"
    return None


def _event_fingerprint(payload):
    event_name = str(_value(payload, "Event", "event") or "")
    action_id = str(_value(payload, "ActionID", "actionid") or "")
    uniqueid = str(_value(payload, "Uniqueid", "UniqueID", "DestUniqueid", "destuniqueid") or "")
    linkedid = str(_value(payload, "Linkedid", "LinkedID", "linkedid") or "")
    channel = str(_value(payload, "Channel", "channel") or "")
    ts = str(_value(payload, "Timestamp", "timestamp") or "")

    base = f"{event_name}|{action_id}|{uniqueid}|{linkedid}|{channel}|{ts}"
    if base.strip("|"):
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _find_call_log(payload, business_id=None):
    action_id = _value(payload, "ActionID", "actionid")
    uniqueid = _value(payload, "Uniqueid", "UniqueID", "DestUniqueid", "destuniqueid")
    linkedid = _value(payload, "Linkedid", "LinkedID", "linkedid")

    query = CallLog.query
    if business_id is not None:
        query = query.filter(CallLog.business_id == int(business_id))

    if action_id:
        row = query.filter(CallLog.action_id == str(action_id)).order_by(CallLog.id.desc()).first()
        if row:
            return row
    if uniqueid:
        row = query.filter(CallLog.asterisk_uniqueid == str(uniqueid)).order_by(CallLog.id.desc()).first()
        if row:
            return row
    if linkedid:
        row = query.filter(CallLog.linkedid == str(linkedid)).order_by(CallLog.id.desc()).first()
        if row:
            return row
    channel_digits = _extract_channel_digits(payload)
    if channel_digits:
        # Conservative fallback: correlate by recent destination/caller numbers.
        recent_rows = query.order_by(CallLog.id.desc()).limit(50).all()
        for row in recent_rows:
            if _phone_matches(row.to_number, channel_digits) or _phone_matches(
                row.dialed_number, channel_digits
            ) or _phone_matches(row.from_number, channel_digits):
                return row
    return None


def _find_call_session(payload, business_id=None):
    action_id = _value(payload, "ActionID", "actionid")
    uniqueid = _value(payload, "Uniqueid", "UniqueID", "DestUniqueid", "destuniqueid")
    linkedid = _value(payload, "Linkedid", "LinkedID", "linkedid")

    query = CallSession.query
    if business_id is not None:
        query = query.filter(CallSession.business_id == int(business_id))

    if action_id:
        row = query.filter(CallSession.ami_action_id == str(action_id)).order_by(CallSession.id.desc()).first()
        if row:
            return row
    if uniqueid:
        row = query.filter(CallSession.uniqueid == str(uniqueid)).order_by(CallSession.id.desc()).first()
        if row:
            return row
    if linkedid:
        row = query.filter(CallSession.linkedid == str(linkedid)).order_by(CallSession.id.desc()).first()
        if row:
            return row
    channel_digits = _extract_channel_digits(payload)
    if channel_digits:
        # Conservative fallback: correlate by recent phone number.
        recent_rows = query.order_by(CallSession.id.desc()).limit(50).all()
        for row in recent_rows:
            if _phone_matches(row.phone_number, channel_digits):
                return row
    return None


def _to_call_session_status(call_log_status):
    if call_log_status == "canceled":
        return "cancelled"
    return call_log_status


def process_call_event(payload, business_id=None):
    if not isinstance(payload, dict):
        return None, "Invalid event payload"

    event_name = _value(payload, "Event", "event")
    if not event_name:
        return None, "Missing event name"

    action_id = _value(payload, "ActionID", "actionid")
    uniqueid = _value(payload, "Uniqueid", "UniqueID", "DestUniqueid", "destuniqueid")
    linkedid = _value(payload, "Linkedid", "LinkedID", "linkedid")
    event_fp = _event_fingerprint(payload)

    existing_event = (
        CallEvent.query.filter(CallEvent.event_fingerprint == event_fp)
        .order_by(CallEvent.id.desc())
        .first()
    )
    if existing_event is not None:
        if existing_event.processing_status == "processed":
            return {
                "event_id": existing_event.id,
                "event": str(event_name),
                "status": "duplicate_ignored",
            }, None

    call_log = _find_call_log(payload, business_id=business_id)
    call_session = _find_call_session(payload, business_id=business_id)
    if call_log is None and call_session is None:
        call_event = CallEvent(
            business_id=int(business_id) if business_id is not None else None,
            call_log_id=None,
            call_session_id=None,
            event_name=str(event_name),
            event_fingerprint=event_fp,
            event_payload_json=json.dumps(payload),
            action_id=str(action_id) if action_id else None,
            uniqueid=str(uniqueid) if uniqueid else None,
            linkedid=str(linkedid) if linkedid else None,
            processing_status="failed",
            process_attempts=1,
            last_error="Call correlation failed",
            processed_at=None,
        )
        db.session.add(call_event)
        db.session.commit()
        return None, "Call log not found for event correlation"

    call_event = existing_event or CallEvent(
        business_id=(
            int(business_id)
            if business_id is not None
            else (call_log.business_id if call_log is not None else call_session.business_id)
        ),
        call_log_id=(call_log.id if call_log is not None else None),
        call_session_id=(call_session.id if call_session is not None else None),
        event_name=str(event_name),
        event_fingerprint=event_fp,
        event_payload_json=json.dumps(payload),
        action_id=str(action_id) if action_id else None,
        uniqueid=str(uniqueid) if uniqueid else None,
        linkedid=str(linkedid) if linkedid else None,
        processing_status="pending",
        process_attempts=0,
    )
    if existing_event is None:
        db.session.add(call_event)

    # Backfill correlation ids if missing.
    if call_log is not None:
        if action_id and not call_log.action_id:
            call_log.action_id = str(action_id)
        if uniqueid and not call_log.asterisk_uniqueid:
            call_log.asterisk_uniqueid = str(uniqueid)
        if linkedid and not call_log.linkedid:
            call_log.linkedid = str(linkedid)

    if call_session is not None:
        if action_id and not call_session.ami_action_id:
            call_session.ami_action_id = str(action_id)
        if uniqueid and not call_session.uniqueid:
            call_session.uniqueid = str(uniqueid)
        if linkedid and not call_session.linkedid:
            call_session.linkedid = str(linkedid)

    new_status = _resolve_status(str(event_name), payload)
    if new_status and call_log is not None:
        call_log.status = new_status
    if new_status and call_session is not None:
        call_session.status = _to_call_session_status(new_status)

    now = datetime.utcnow()
    if new_status == "answered":
        if call_log is not None and call_log.answered_at is None:
            call_log.answered_at = now
        if call_session is not None and call_session.answered_at is None:
            call_session.answered_at = now
    if str(event_name) == "Hangup":
        if call_log is not None:
            if call_log.ended_at is None:
                call_log.ended_at = now
            if call_log.started_at and call_log.ended_at:
                call_log.duration_sec = int((call_log.ended_at - call_log.started_at).total_seconds())
            if call_log.answered_at and call_log.ended_at:
                call_log.billsec = int((call_log.ended_at - call_log.answered_at).total_seconds())
            call_log.hangup_cause = str(_value(payload, "Cause", "cause") or "")
            call_log.hangup_cause_text = str(
                _value(payload, "Cause-txt", "CauseTxt", "cause_txt") or ""
            )

        if call_session is not None:
            if call_session.ended_at is None:
                call_session.ended_at = now
            call_session.hangup_cause = str(_value(payload, "Cause", "cause") or "")

    if call_log is not None:
        call_log.raw_event_json = json.dumps(payload)
    call_event.call_log_id = call_log.id if call_log is not None else None
    call_event.call_session_id = call_session.id if call_session is not None else None
    call_event.processing_status = "processed"
    call_event.process_attempts = int(call_event.process_attempts or 0) + 1
    call_event.last_error = None
    call_event.processed_at = datetime.utcnow()
    db.session.commit()

    return {
        "event_id": call_event.id,
        "call_log_id": (call_log.id if call_log is not None else None),
        "call_log_uuid": (call_log.uuid if call_log is not None else None),
        "call_session_id": (call_session.id if call_session is not None else None),
        "event": str(event_name),
        "status": (
            call_log.status
            if call_log is not None
            else call_session.status
            if call_session is not None
            else None
        ),
    }, None


def _serialize_call_event(row):
    return {
        "id": row.id,
        "business_id": row.business_id,
        "call_log_id": row.call_log_id,
        "call_session_id": row.call_session_id,
        "event_name": row.event_name,
        "event_fingerprint": row.event_fingerprint,
        "action_id": row.action_id,
        "uniqueid": row.uniqueid,
        "linkedid": row.linkedid,
        "processing_status": row.processing_status,
        "process_attempts": row.process_attempts,
        "last_error": row.last_error,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_call_events(*, business_id=None, status=None, page=1, page_size=20):
    query = CallEvent.query
    if business_id is not None:
        query = query.filter(CallEvent.business_id == int(business_id))
    if status:
        query = query.filter(CallEvent.processing_status == str(status).strip().lower())

    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 20)))
    total = query.count()
    rows = (
        query.order_by(CallEvent.created_at.desc(), CallEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [_serialize_call_event(row) for row in rows],
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }, None


def reprocess_call_event(event_id, business_id=None):
    try:
        normalized_id = int(event_id)
    except (TypeError, ValueError):
        return None, "Invalid event id"

    query = CallEvent.query.filter(CallEvent.id == normalized_id)
    if business_id is not None:
        query = query.filter(CallEvent.business_id == int(business_id))
    row = query.first()
    if row is None:
        return None, "Call event not found"

    try:
        payload = json.loads(row.event_payload_json or "{}")
    except Exception:  # noqa: BLE001
        row.processing_status = "failed"
        row.process_attempts = int(row.process_attempts or 0) + 1
        row.last_error = "Invalid event_payload_json"
        row.processed_at = None
        db.session.commit()
        return None, "Invalid stored event payload"

    # Remove this row before reprocessing so fingerprint dedupe doesn't short-circuit.
    db.session.delete(row)
    db.session.commit()
    result, error = process_call_event(payload, business_id=business_id)
    if error:
        return None, error
    return result, None
