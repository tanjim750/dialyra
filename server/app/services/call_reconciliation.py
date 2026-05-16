from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.extensions import db
from app.models import CallLog, CallSession

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
    if (
        str(call_log.status or "").strip().lower() in answered_statuses
        and call_log.answered_at is None
        and call_log.ended_at is not None
    ):
        call_log.answered_at = call_log.ended_at

    if call_session is not None:
        if (
            str(call_session.status or "").strip().lower() in answered_statuses
            and call_session.answered_at is None
        ):
            call_session.answered_at = (
                call_log.answered_at or call_session.ended_at or call_log.ended_at
            )


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
