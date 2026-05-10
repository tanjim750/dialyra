from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.extensions import db
from app.models import CallLog

FINAL_STATUSES = {"completed", "failed", "no_answer", "busy", "canceled"}
STATUS_RANK = {
    "queued": 0,
    "ringing": 1,
    "answered": 2,
    "completed": 3,
    "failed": 3,
    "no_answer": 3,
    "busy": 3,
    "canceled": 3,
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


def _find_call_log_for_cdr(row: dict[str, Any], window_start: datetime):
    uniqueid = _first_non_empty(row.get("uniqueid"), row.get("unique_id"))
    linkedid = _first_non_empty(row.get("linkedid"), row.get("linked_id"))
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
        if call_log.status in FINAL_STATUSES and call_log.ended_at is not None:
            stats.skipped_finalized += 1
            continue

        changed = False
        uniqueid = _first_non_empty(cdr_row.get("uniqueid"))
        linkedid = _first_non_empty(cdr_row.get("linkedid"))
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

        mapped_status = _map_disposition_to_status(disposition)
        if mapped_status and _should_upgrade_status(call_log.status, mapped_status):
            if call_log.status != mapped_status:
                call_log.status = mapped_status
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
