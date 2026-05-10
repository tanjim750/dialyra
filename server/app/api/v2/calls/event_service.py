import json
from datetime import datetime

from app.extensions import db
from app.models import CallLog


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
    return None


def process_call_event(payload, business_id=None):
    if not isinstance(payload, dict):
        return None, "Invalid event payload"

    event_name = _value(payload, "Event", "event")
    if not event_name:
        return None, "Missing event name"

    call_log = _find_call_log(payload, business_id=business_id)
    if call_log is None:
        return None, "Call log not found for event correlation"

    # Backfill correlation ids if missing.
    action_id = _value(payload, "ActionID", "actionid")
    uniqueid = _value(payload, "Uniqueid", "UniqueID", "DestUniqueid", "destuniqueid")
    linkedid = _value(payload, "Linkedid", "LinkedID", "linkedid")
    if action_id and not call_log.action_id:
        call_log.action_id = str(action_id)
    if uniqueid and not call_log.asterisk_uniqueid:
        call_log.asterisk_uniqueid = str(uniqueid)
    if linkedid and not call_log.linkedid:
        call_log.linkedid = str(linkedid)

    new_status = _resolve_status(str(event_name), payload)
    if new_status:
        call_log.status = new_status

    now = datetime.utcnow()
    if new_status == "answered" and call_log.answered_at is None:
        call_log.answered_at = now
    if str(event_name) == "Hangup":
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

    call_log.raw_event_json = json.dumps(payload)
    db.session.commit()

    return {
        "call_log_id": call_log.id,
        "call_log_uuid": call_log.uuid,
        "event": str(event_name),
        "status": call_log.status,
    }, None
