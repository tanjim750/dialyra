from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
import logging

from flask import current_app
from sqlalchemy import text

from app.extensions import db
from app.models import CallLog, CallSession, FlowRuntimeEvent

FINAL_STATUSES = {"completed", "failed", "no_answer", "busy", "canceled"}
SESSION_FINAL_STATUSES = {"completed", "failed", "no_answer", "busy", "cancelled", "hangup"}
INVALID_ID_TOKENS = {"", "unknown", "<unknown>", "none", "null", "n/a"}
STATUS_RANK = {
    "queued": 0,
    "ringing": 1,
    "answered": 2,
    "completed": 3,
    "failed": 3,
    "no_answer": 3,
    "busy": 3,
    "canceled": 3,
    "cancelled": 3,
    "hangup": 3,
}

LOGGER = logging.getLogger(__name__)


def _pipeline_verbose_enabled():
    try:
        return bool(current_app.config.get("CALL_PIPELINE_VERBOSE", False))
    except Exception:
        return False


def _vlog(message, **meta):
    if not _pipeline_verbose_enabled():
        return
    if meta:
        LOGGER.info("CALL-PIPELINE: %s | %s", message, meta)
    else:
        LOGGER.info("CALL-PIPELINE: %s", message)


@dataclass
class ReconcileStats:
    scanned: int = 0
    matched: int = 0
    updated: int = 0
    skipped_finalized: int = 0
    unmatched: int = 0

    def as_dict(self):
        return {
            "scanned": self.scanned,
            "matched": self.matched,
            "updated": self.updated,
            "skipped_finalized": self.skipped_finalized,
            "unmatched": self.unmatched,
        }


def _table_exists(table_name: str) -> bool:
    row = db.session.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _columns_for(table_name: str) -> set[str]:
    rows = db.session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).fetchall()
    return {r[0] for r in rows}


def _map_disposition_to_status(disposition: str | None) -> str | None:
    value = (disposition or "").strip().upper()
    if value in {"ANSWERED"}:
        return "completed"
    if value in {"BUSY"}:
        return "busy"
    if value in {"NO ANSWER", "NOANSWER"}:
        return "no_answer"
    if value in {"CANCEL", "CANCELED"}:
        return "canceled"
    if value:
        return "failed"
    return None


def _should_upgrade_status(current_status: str, candidate_status: str) -> bool:
    return STATUS_RANK.get(candidate_status, 0) >= STATUS_RANK.get(current_status or "queued", 0)


def _first_non_empty(*values):
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _normalize_identifier(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in INVALID_ID_TOKENS:
        return None
    return text


def _apply_answered_invariant(call_log: CallLog, call_session: CallSession | None):
    answered_statuses = {"answered", "completed"}
    if str(call_log.status or "").strip().lower() in answered_statuses:
        if call_log.answered_at is None and call_log.ended_at is not None:
            # Prefer deriving from known billsec/duration rather than forcing
            # answered_at=end_time, which creates false zero-billsec records.
            sec_hint = int(call_log.billsec or 0)
            if sec_hint <= 0:
                sec_hint = int(call_log.duration_sec or 0)
            if sec_hint > 0:
                call_log.answered_at = call_log.ended_at - timedelta(seconds=sec_hint)
        if call_log.answered_at and call_log.ended_at and call_log.answered_at >= call_log.ended_at:
            sec_hint = int(call_log.billsec or 0) or int(call_log.duration_sec or 0) or 1
            call_log.answered_at = call_log.ended_at - timedelta(seconds=max(1, sec_hint))

    if call_session is not None:
        if str(call_session.status or "").strip().lower() in answered_statuses:
            if call_session.answered_at is None:
                call_session.answered_at = (
                    call_log.answered_at or call_session.ended_at or call_log.ended_at
                )
            if call_session.answered_at and call_session.ended_at and call_session.answered_at >= call_session.ended_at:
                sec_hint = int(call_log.billsec or 0) or int(call_log.duration_sec or 0) or 1
                call_session.answered_at = call_session.ended_at - timedelta(seconds=max(1, sec_hint))


def _find_call_log_for_cdr(row: dict[str, Any], window_start: datetime):
    uniqueid = _normalize_identifier(_first_non_empty(row.get("uniqueid"), row.get("unique_id")))
    linkedid = _normalize_identifier(_first_non_empty(row.get("linkedid"), row.get("linked_id")))
    dst = _first_non_empty(row.get("dst"), row.get("destination"))
    start_dt = _first_non_empty(row.get("start"), row.get("calldate"), row.get("start_time"))

    if uniqueid:
        log = CallLog.query.filter(CallLog.asterisk_uniqueid == str(uniqueid)).order_by(CallLog.id.desc()).first()
        if log:
            return log
    if linkedid:
        log = CallLog.query.filter(CallLog.linkedid == str(linkedid)).order_by(CallLog.id.desc()).first()
        if log:
            return log

    # Fallback: unresolved logs for same destination in recent window.
    if dst:
        query = CallLog.query.filter(
            CallLog.to_number == str(dst),
            CallLog.started_at >= window_start,
        ).order_by(CallLog.id.desc())
        if start_dt:
            query = query.filter(CallLog.started_at <= start_dt + timedelta(minutes=10))
        return query.first()
    return None


def _to_session_status(call_log_status: str | None) -> str | None:
    if call_log_status == "canceled":
        return "cancelled"
    return call_log_status


def _find_call_session_for_call_log(call_log: CallLog):
    if call_log.action_id:
        row = (
            CallSession.query.filter(CallSession.ami_action_id == str(call_log.action_id))
            .order_by(CallSession.id.desc())
            .first()
        )
        if row:
            return row
    if call_log.asterisk_uniqueid:
        row = (
            CallSession.query.filter(CallSession.uniqueid == str(call_log.asterisk_uniqueid))
            .order_by(CallSession.id.desc())
            .first()
        )
        if row:
            return row
    if call_log.linkedid:
        row = (
            CallSession.query.filter(CallSession.linkedid == str(call_log.linkedid))
            .order_by(CallSession.id.desc())
            .first()
        )
        if row:
            return row
    return (
        CallSession.query.filter(
            CallSession.business_id == call_log.business_id,
            CallSession.sip_trunk_id == call_log.sip_trunk_id,
            CallSession.phone_number == call_log.to_number,
        )
        .order_by(CallSession.id.desc())
        .first()
    )


def _coerce_dt(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _to_int_or_none(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def _is_invalid_answer_dt(value):
    if value is None:
        return True
    # Guard against bogus epoch-like values from noisy CDR legs.
    return value <= datetime(1971, 1, 1)


def _parse_userfield_action_id(value):
    text = str(value or "").strip()
    if not text:
        return None
    # Expected format written by dialplan:
    #   call_action_id=<uuid>
    # Also tolerate multi-part values separated by | or ;.
    parts = []
    for token in text.replace(";", "|").split("|"):
        token = token.strip()
        if token:
            parts.append(token)
    for part in parts:
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        if str(key or "").strip().lower() == "call_action_id":
            return _normalize_identifier(raw)
    return None


def _fetch_best_cdr_row_for_call(call_log: CallLog):
    if not _table_exists("cdr"):
        return None
    cdr_columns = _columns_for("cdr")
    if not cdr_columns:
        return None
    if "userfield" not in cdr_columns:
        return None

    time_col = "start" if "start" in cdr_columns else "calldate" if "calldate" in cdr_columns else None
    if time_col is None:
        return None

    select_cols = [
        c
        for c in [
            "uniqueid",
            "linkedid",
            "src",
            "dst",
            "disposition",
            "duration",
            "billsec",
            "start",
            "answer",
            "end",
            "end_time",
            "calldate",
            "userfield",
        ]
        if c in cdr_columns
    ]
    if not select_cols:
        return None

    action_id = _normalize_identifier(call_log.action_id)
    if not action_id:
        _vlog("CDR lookup skipped: missing action_id", call_log_id=call_log.id)
        return None

    # Strict deterministic match: CALL_ACTION_ID embedded in CDR userfield.
    sql = f"""
        SELECT {", ".join(select_cols)}
        FROM cdr
        WHERE userfield LIKE :pattern
        ORDER BY {time_col} DESC
        LIMIT 50
    """
    rows = db.session.execute(
        text(sql),
        {"pattern": f"%call_action_id={action_id}%"},
    ).mappings().all()
    if not rows:
        _vlog("CDR lookup: no rows by action_id", call_log_id=call_log.id, action_id=action_id)
        return None

    for row in rows:
        row_dict = dict(row)
        parsed_action_id = _parse_userfield_action_id(row_dict.get("userfield"))
        if parsed_action_id == action_id:
            _vlog("CDR lookup: matched row by action_id", call_log_id=call_log.id, action_id=action_id)
            return row_dict

    _vlog("CDR lookup: rows found but no exact parsed action_id match", call_log_id=call_log.id, action_id=action_id)
    return None


def apply_cdr_truth_for_call(call_log: CallLog, call_session: CallSession | None = None) -> bool:
    """
    Finalize call records from CDR as source of truth.
    Returns True when a CDR row is applied.
    """
    cdr_row = _fetch_best_cdr_row_for_call(call_log)
    if not cdr_row:
        _vlog("CDR finalize skipped: no matched row", call_log_id=call_log.id, action_id=call_log.action_id)
        return False

    if call_session is None:
        call_session = _find_call_session_for_call_log(call_log)

    uniqueid = _normalize_identifier(cdr_row.get("uniqueid"))
    linkedid = _normalize_identifier(cdr_row.get("linkedid"))
    src = _first_non_empty(cdr_row.get("src"))
    dst = _first_non_empty(cdr_row.get("dst"))
    started_at = _coerce_dt(_first_non_empty(cdr_row.get("start"), cdr_row.get("calldate")))
    cdr_answered_at = _coerce_dt(cdr_row.get("answer"))
    cdr_ended_at = _coerce_dt(_first_non_empty(cdr_row.get("end"), cdr_row.get("end_time")))
    duration = _to_int_or_none(cdr_row.get("duration"))
    billsec = _to_int_or_none(cdr_row.get("billsec"))
    mapped_status = _map_disposition_to_status(_first_non_empty(cdr_row.get("disposition")))
    history_ended_ref = call_log.ended_at or (call_session.ended_at if call_session is not None else None)

    if uniqueid:
        call_log.asterisk_uniqueid = uniqueid
    if linkedid:
        call_log.linkedid = linkedid
    if src:
        call_log.from_number = str(src)
    if dst:
        call_log.to_number = str(dst)
    if started_at:
        call_log.started_at = started_at
    # Priority rule:
    # cdr_answer -> history_answered fallback
    cdr_answer_is_timeline_consistent = True
    if cdr_answered_at and history_ended_ref and cdr_answered_at >= history_ended_ref:
        cdr_answer_is_timeline_consistent = False
        _vlog(
            "CDR answer ignored: inconsistent with known ended_at",
            call_log_id=call_log.id,
            action_id=call_log.action_id,
            cdr_answered_at=(cdr_answered_at.isoformat() if cdr_answered_at else None),
            history_ended_at=(history_ended_ref.isoformat() if history_ended_ref else None),
        )

    if not _is_invalid_answer_dt(cdr_answered_at) and cdr_answer_is_timeline_consistent:
        call_log.answered_at = cdr_answered_at
    elif call_log.answered_at is None and call_session is not None and call_session.answered_at is not None:
        call_log.answered_at = call_session.answered_at
    # cdr_end_time -> history_ended_at fallback
    if cdr_ended_at:
        call_log.ended_at = cdr_ended_at
    elif call_log.ended_at is None and call_session is not None and call_session.ended_at is not None:
        call_log.ended_at = call_session.ended_at
    if duration is not None:
        call_log.duration_sec = duration
    if billsec is not None:
        call_log.billsec = max(0, billsec)
    if mapped_status:
        call_log.status = mapped_status

    if call_session is not None:
        if uniqueid:
            call_session.uniqueid = uniqueid
        if linkedid:
            call_session.linkedid = linkedid
        if started_at:
            call_session.started_at = started_at
        if not _is_invalid_answer_dt(cdr_answered_at) and cdr_answer_is_timeline_consistent:
            call_session.answered_at = cdr_answered_at
        elif call_session.answered_at is None and call_log.answered_at is not None:
            call_session.answered_at = call_log.answered_at
        if cdr_ended_at:
            call_session.ended_at = cdr_ended_at
        elif call_session.ended_at is None and call_log.ended_at is not None:
            call_session.ended_at = call_log.ended_at
        if mapped_status:
            call_session.status = _to_session_status(mapped_status)

    # Billsec fallback chain:
    # 1) If billsec missing/zero but valid answer+end exist => derive from timestamps.
    if int(call_log.billsec or 0) == 0 and call_log.answered_at and call_log.ended_at:
        delta = int((call_log.ended_at - call_log.answered_at).total_seconds())
        if delta > 0:
            call_log.billsec = delta
    # 2) If still zero and runtime had DTMF interaction, infer from duration with conservative offset.
    if int(call_log.billsec or 0) == 0 and int(call_log.duration_sec or 0) > 0:
        has_dtmf = False
        if call_session is not None:
            has_dtmf = (
                FlowRuntimeEvent.query.filter(
                    FlowRuntimeEvent.business_id == int(call_log.business_id),
                    FlowRuntimeEvent.call_session_id == str(call_session.id),
                    FlowRuntimeEvent.event_type == "dtmf.received",
                ).first()
                is not None
            )
        if has_dtmf:
            duration_val = int(call_log.duration_sec or 0)
            offset = 3 if duration_val <= 15 else 5
            call_log.billsec = max(1, duration_val - offset)

    _apply_answered_invariant(call_log, call_session)
    _vlog(
        "CDR finalize applied",
        call_log_id=call_log.id,
        action_id=call_log.action_id,
        status=call_log.status,
        started_at=(call_log.started_at.isoformat() if call_log.started_at else None),
        answered_at=(call_log.answered_at.isoformat() if call_log.answered_at else None),
        ended_at=(call_log.ended_at.isoformat() if call_log.ended_at else None),
        duration_sec=call_log.duration_sec,
        billsec=call_log.billsec,
    )
    return True


def reconcile_call_logs_from_cdr(*, hours_back: int = 24, limit: int = 5000, dry_run: bool = True):
    if not _table_exists("cdr"):
        return None, "cdr table not found"

    cdr_columns = _columns_for("cdr")
    stats = ReconcileStats()
    window_start = datetime.utcnow() - timedelta(hours=max(1, int(hours_back)))

    select_cols = []
    for col in [
        "uniqueid",
        "linkedid",
        "src",
        "dst",
        "disposition",
        "duration",
        "billsec",
        "calldate",
        "start",
        "answer",
        "end",
    ]:
        if col in cdr_columns:
            select_cols.append(col)
    if not select_cols:
        return None, "cdr table has no expected columns"

    time_col = "start" if "start" in cdr_columns else "calldate" if "calldate" in cdr_columns else None
    if time_col is None:
        return None, "cdr table missing time column (start/calldate)"

    sql = f"""
        SELECT {", ".join(select_cols)}
        FROM cdr
        WHERE {time_col} >= :window_start
        ORDER BY {time_col} DESC
        LIMIT :limit
    """
    rows = db.session.execute(
        text(sql),
        {"window_start": window_start, "limit": int(limit)},
    ).mappings().all()

    stats.scanned = len(rows)

    for row in rows:
        cdr_row = dict(row)
        call_log = _find_call_log_for_cdr(cdr_row, window_start)
        if call_log is None:
            stats.unmatched += 1
            continue

        stats.matched += 1
        call_session = _find_call_session_for_call_log(call_log)

        if (
            call_log.status in FINAL_STATUSES
            and call_log.ended_at is not None
            and (
                call_session is None
                or (
                    call_session.status in SESSION_FINAL_STATUSES
                    and call_session.ended_at is not None
                )
            )
        ):
            stats.skipped_finalized += 1
            continue

        changed = False
        uniqueid = _normalize_identifier(_first_non_empty(cdr_row.get("uniqueid")))
        linkedid = _normalize_identifier(_first_non_empty(cdr_row.get("linkedid")))
        src = _first_non_empty(cdr_row.get("src"))
        dst = _first_non_empty(cdr_row.get("dst"))
        disposition = _first_non_empty(cdr_row.get("disposition"))
        duration = cdr_row.get("duration")
        billsec = cdr_row.get("billsec")
        started_at = _first_non_empty(cdr_row.get("start"), cdr_row.get("calldate"))
        answered_at = _first_non_empty(cdr_row.get("answer"))
        ended_at = _first_non_empty(cdr_row.get("end"))

        if uniqueid and call_log.asterisk_uniqueid != str(uniqueid):
            call_log.asterisk_uniqueid = str(uniqueid)
            changed = True
        if linkedid and call_log.linkedid != str(linkedid):
            call_log.linkedid = str(linkedid)
            changed = True
        if src and not call_log.from_number:
            call_log.from_number = str(src)
            changed = True
        if dst and not call_log.to_number:
            call_log.to_number = str(dst)
            changed = True
        if started_at and call_log.started_at is None:
            call_log.started_at = started_at
            changed = True
        if answered_at and call_log.answered_at is None:
            call_log.answered_at = answered_at
            changed = True
        if ended_at and call_log.ended_at is None:
            call_log.ended_at = ended_at
            changed = True
        if duration is not None and (call_log.duration_sec is None or int(duration) > int(call_log.duration_sec or 0)):
            call_log.duration_sec = int(duration)
            changed = True
        if billsec is not None and (call_log.billsec is None or int(billsec) > int(call_log.billsec or 0)):
            call_log.billsec = int(billsec)
            changed = True
        if call_log.billsec is None and call_log.answered_at and call_log.ended_at:
            call_log.billsec = max(0, int((call_log.ended_at - call_log.answered_at).total_seconds()))
            changed = True

        mapped_status = _map_disposition_to_status(disposition)
        if mapped_status and _should_upgrade_status(call_log.status, mapped_status):
            if call_log.status != mapped_status:
                call_log.status = mapped_status
                changed = True

        # Keep call_session in sync if we can correlate one.
        if call_session is not None:
            if call_log.action_id and call_session.ami_action_id != str(call_log.action_id):
                call_session.ami_action_id = str(call_log.action_id)
                changed = True
            if call_log.asterisk_uniqueid and call_session.uniqueid != str(call_log.asterisk_uniqueid):
                call_session.uniqueid = str(call_log.asterisk_uniqueid)
                changed = True
            if call_log.linkedid and call_session.linkedid != str(call_log.linkedid):
                call_session.linkedid = str(call_log.linkedid)
                changed = True

            if started_at and call_session.started_at is None:
                call_session.started_at = started_at
                changed = True
            if answered_at and call_session.answered_at is None:
                call_session.answered_at = answered_at
                changed = True
            if ended_at and call_session.ended_at is None:
                call_session.ended_at = ended_at
                changed = True
            if call_log.hangup_cause and not call_session.hangup_cause:
                call_session.hangup_cause = call_log.hangup_cause
                changed = True

            mapped_session_status = _to_session_status(mapped_status)
            if mapped_session_status:
                if _should_upgrade_status(call_log.status, mapped_status):
                    if call_session.status != mapped_session_status:
                        call_session.status = mapped_session_status
                        changed = True

        before_answered = (
            call_log.answered_at,
            call_session.answered_at if call_session is not None else None,
        )
        _apply_answered_invariant(call_log, call_session)
        after_answered = (
            call_log.answered_at,
            call_session.answered_at if call_session is not None else None,
        )
        if before_answered != after_answered:
            changed = True

        if changed:
            stats.updated += 1

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()

    # Optional CEL awareness for visibility only in this phase.
    cel_exists = _table_exists("cel")
    result = {
        "stats": stats.as_dict(),
        "dry_run": dry_run,
        "window_start": window_start.isoformat(),
        "source": {"cdr": True, "cel": cel_exists},
    }
    return result, None
