import uuid
from datetime import datetime, timedelta

from app.extensions import db
from app.services.ami_service import AMIService
from app.services.asterisk_channels import count_active_calls_for_endpoint
from app.models import Business, CallLog, SipTrunk
from sqlalchemy import case, func


ami_service = AMIService()


def _slug(value):
    import re

    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return normalized or "trunk"


def _trunk_endpoint_name(trunk, realtime_enabled):
    business_part = trunk.business_id if trunk.business_id is not None else "global"
    if realtime_enabled:
        return f"dialyra_b{business_part}_t{trunk.id}_{_slug(trunk.name)}_ep"
    return f"dialyra-b{business_part}-t{trunk.id}-{_slug(trunk.name)}-endpoint"


def originate_call(phone, channel_variables=None, action_id=None):
    return ami_service.originate_call(
        phone, channel_variables=channel_variables, action_id=action_id
    )


def _eligible_business_trunks(business_id):
    return (
        SipTrunk.query.filter_by(
            business_id=int(business_id),
            scope="business",
            is_active=True,
            status="active",
        )
        .order_by(SipTrunk.id.asc())
        .all()
    )


def _eligible_global_trunks():
    return (
        SipTrunk.query.filter_by(
            scope="global",
            is_active=True,
            status="active",
        )
        .order_by(SipTrunk.id.asc())
        .all()
    )


def _pick_min_load_trunk(trunks, realtime_enabled):
    ranked = []
    for trunk in trunks:
        endpoint = _trunk_endpoint_name(trunk, realtime_enabled=realtime_enabled)
        try:
            active_calls = count_active_calls_for_endpoint(endpoint, ami_service)["active_calls"]
        except Exception:
            active_calls = 0
        remaining = max(0, int(trunk.max_concurrent_calls or 0) - active_calls)
        ranked.append((trunk, endpoint, active_calls, remaining))

    with_capacity = [item for item in ranked if item[3] > 0]
    if not with_capacity:
        return None, ranked

    with_capacity.sort(key=lambda item: (item[2], -(item[3]), item[0].id))
    return with_capacity[0], ranked


def originate_call_for_business(
    phone,
    business_id,
    sip_trunk_id,
    realtime_enabled,
    actor_user_id=None,
):
    business = Business.query.get(int(business_id))
    if business is None:
        return None, "Business not found"

    trunk = None
    endpoint = None
    active_calls_before = 0
    selected_by = "requested"
    if sip_trunk_id is not None:
        try:
            normalized_trunk_id = int(sip_trunk_id)
        except (TypeError, ValueError):
            return None, "Invalid sip_trunk_id"
        trunk = SipTrunk.query.filter_by(id=normalized_trunk_id, is_active=True).first()
        if trunk is None:
            return None, "SIP trunk not found for this business"
        if trunk.scope == "business" and trunk.business_id != int(business_id):
            return None, "SIP trunk not found for this business"
        if trunk.scope == "global" and not business.allow_global_sip_fallback:
            return (
                None,
                "GLOBAL_SIP_NOT_ALLOWED: Global SIP fallback is not enabled for this business",
            )
        endpoint = _trunk_endpoint_name(trunk, realtime_enabled=realtime_enabled)
        try:
            active_calls_before = count_active_calls_for_endpoint(endpoint, ami_service)["active_calls"]
        except Exception:
            active_calls_before = 0
        if active_calls_before >= int(trunk.max_concurrent_calls or 0):
            return (
                None,
                "NO_TRUNK_CAPACITY: No slot available on selected SIP trunk",
            )
    else:
        business_trunks = _eligible_business_trunks(business_id)
        if business_trunks:
            picked, _ranked = _pick_min_load_trunk(
                business_trunks, realtime_enabled=realtime_enabled
            )
            if picked is None:
                return (
                    None,
                    "NO_TRUNK_CAPACITY: No slot available on any business SIP trunk",
                )
            trunk, endpoint, active_calls_before, _remaining = picked
            selected_by = "auto_business"
        else:
            if not business.allow_global_sip_fallback:
                return (
                    None,
                    "NO_SIP_AVAILABLE: Business has no active SIP trunk and global fallback is disabled",
                )
            global_trunks = _eligible_global_trunks()
            if not global_trunks:
                return (
                    None,
                    "NO_SIP_AVAILABLE: No active global SIP trunk available",
                )
            picked, _ranked = _pick_min_load_trunk(
                global_trunks, realtime_enabled=realtime_enabled
            )
            if picked is None:
                return (
                    None,
                    "NO_TRUNK_CAPACITY: No slot available on any global SIP trunk",
                )
            trunk, endpoint, active_calls_before, _remaining = picked
            selected_by = "auto_global_fallback"

    action_id = str(uuid.uuid4())
    call_uuid = str(uuid.uuid4())

    call_log = CallLog(
        uuid=call_uuid,
        action_id=action_id,
        business_id=int(business_id),
        sip_trunk_id=trunk.id,
        actor_user_id=actor_user_id,
        direction="outbound",
        to_number=str(phone),
        dialed_number=str(phone),
        status="queued",
        started_at=datetime.utcnow(),
    )
    db.session.add(call_log)
    db.session.commit()

    response = originate_call(
        phone,
        channel_variables={
            "SIP_TRUNK_ENDPOINT": endpoint,
            "SIP_TRUNK_ID": trunk.id,
            "BUSINESS_ID": trunk.business_id,
            "SIP_TRUNK_HOST": trunk.host,
            "SIP_TRUNK_PORT": trunk.port,
            "SIP_TRUNK_TYPE": trunk.type,
            "CALL_LOG_UUID": call_uuid,
        },
        action_id=action_id,
    )
    return {
        "ami_response": response,
        "call_log_uuid": call_uuid,
        "action_id": action_id,
        "sip_trunk_id": trunk.id,
        "sip_endpoint": endpoint,
        "selected_by": selected_by,
        "active_calls_before": active_calls_before,
        "max_concurrent_calls": trunk.max_concurrent_calls,
    }, None


def _serialize_call_log(row):
    return {
        "id": row.id,
        "uuid": row.uuid,
        "action_id": row.action_id,
        "asterisk_uniqueid": row.asterisk_uniqueid,
        "linkedid": row.linkedid,
        "business_id": row.business_id,
        "sip_trunk_id": row.sip_trunk_id,
        "actor_user_id": row.actor_user_id,
        "direction": row.direction,
        "from_number": row.from_number,
        "to_number": row.to_number,
        "dialed_number": row.dialed_number,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "answered_at": row.answered_at.isoformat() if row.answered_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "duration_sec": row.duration_sec,
        "billsec": row.billsec,
        "hangup_cause": row.hangup_cause,
        "hangup_cause_text": row.hangup_cause_text,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _allowed_business_ids_for_actor(actor_user):
    if actor_user.role == "superuser":
        return None
    owned_ids = [b.id for b in Business.query.filter_by(owner_user_id=actor_user.id).all()]
    from app.models import WorkspaceMembership

    member_ids = [
        m.business_id
        for m in WorkspaceMembership.query.filter_by(user_id=actor_user.id, status="active").all()
    ]
    return sorted(set(owned_ids + member_ids))


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def list_call_history(actor_user, filters):
    query = CallLog.query

    allowed_ids = _allowed_business_ids_for_actor(actor_user)
    if allowed_ids is not None:
        if not allowed_ids:
            return {"items": [], "pagination": {"page": 1, "page_size": 20, "total": 0}}, None
        query = query.filter(CallLog.business_id.in_(allowed_ids))

    business_id = filters.get("business_id")
    if business_id is not None:
        try:
            business_id = int(business_id)
        except (TypeError, ValueError):
            return None, "Invalid business_id"
        if allowed_ids is not None and business_id not in allowed_ids:
            return None, "Insufficient permission for this business"
        query = query.filter(CallLog.business_id == business_id)

    sip_trunk_id = filters.get("sip_trunk_id")
    if sip_trunk_id is not None:
        try:
            query = query.filter(CallLog.sip_trunk_id == int(sip_trunk_id))
        except (TypeError, ValueError):
            return None, "Invalid sip_trunk_id"

    status = (filters.get("status") or "").strip().lower()
    if status:
        query = query.filter(CallLog.status == status)

    number = (filters.get("number") or "").strip()
    if number:
        like = f"%{number}%"
        query = query.filter(
            (CallLog.to_number.ilike(like))
            | (CallLog.from_number.ilike(like))
            | (CallLog.dialed_number.ilike(like))
        )

    date_from = _parse_dt(filters.get("date_from"))
    if filters.get("date_from") and date_from is None:
        return None, "Invalid date_from (expected ISO datetime)"
    if date_from:
        query = query.filter(CallLog.started_at >= date_from)

    date_to = _parse_dt(filters.get("date_to"))
    if filters.get("date_to") and date_to is None:
        return None, "Invalid date_to (expected ISO datetime)"
    if date_to:
        query = query.filter(CallLog.started_at <= date_to)

    try:
        page = max(1, int(filters.get("page") or 1))
        page_size = int(filters.get("page_size") or 20)
    except (TypeError, ValueError):
        return None, "Invalid pagination params"
    page_size = max(1, min(200, page_size))

    total = query.count()
    items = (
        query.order_by(CallLog.started_at.desc(), CallLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "items": [_serialize_call_log(item) for item in items],
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }, None


def get_call_history_by_id(actor_user, call_id):
    try:
        normalized_id = int(call_id)
    except (TypeError, ValueError):
        return None, "Invalid call id"

    row = CallLog.query.get(normalized_id)
    if row is None:
        return None, "Call history not found"

    allowed_ids = _allowed_business_ids_for_actor(actor_user)
    if allowed_ids is not None and row.business_id not in allowed_ids:
        return None, "Insufficient permission for this business"

    return _serialize_call_log(row), None


def get_call_metrics(actor_user, filters):
    query = CallLog.query

    allowed_ids = _allowed_business_ids_for_actor(actor_user)
    if allowed_ids is not None:
        if not allowed_ids:
            empty = {
                "summary": {
                    "total_calls": 0,
                    "answered": 0,
                    "failed": 0,
                    "asr": 0.0,
                    "avg_duration_sec": 0.0,
                    "peak_concurrent_estimate": 0,
                },
                "by_business": [],
                "by_trunk": [],
            }
            return empty, None
        query = query.filter(CallLog.business_id.in_(allowed_ids))

    business_id = filters.get("business_id")
    if business_id is not None:
        try:
            business_id = int(business_id)
        except (TypeError, ValueError):
            return None, "Invalid business_id"
        if allowed_ids is not None and business_id not in allowed_ids:
            return None, "Insufficient permission for this business"
        query = query.filter(CallLog.business_id == business_id)

    sip_trunk_id = filters.get("sip_trunk_id")
    if sip_trunk_id is not None:
        try:
            query = query.filter(CallLog.sip_trunk_id == int(sip_trunk_id))
        except (TypeError, ValueError):
            return None, "Invalid sip_trunk_id"

    date_from = _parse_dt(filters.get("date_from"))
    if filters.get("date_from") and date_from is None:
        return None, "Invalid date_from (expected ISO datetime)"
    if date_from:
        query = query.filter(CallLog.started_at >= date_from)

    date_to = _parse_dt(filters.get("date_to"))
    if filters.get("date_to") and date_to is None:
        return None, "Invalid date_to (expected ISO datetime)"
    if date_to:
        query = query.filter(CallLog.started_at <= date_to)

    base_subquery = query.subquery()
    status_col = base_subquery.c.status
    duration_col = base_subquery.c.duration_sec
    business_col = base_subquery.c.business_id
    trunk_col = base_subquery.c.sip_trunk_id

    answered_expr = func.sum(case((status_col.in_(["answered", "completed"]), 1), else_=0))
    failed_expr = func.sum(
        case((status_col.in_(["failed", "busy", "no_answer", "canceled"]), 1), else_=0)
    )

    summary_row = db.session.query(
        func.count().label("total_calls"),
        answered_expr.label("answered"),
        failed_expr.label("failed"),
        func.avg(duration_col).label("avg_duration_sec"),
    ).select_from(base_subquery).first()

    total_calls = int(summary_row.total_calls or 0)
    answered = int(summary_row.answered or 0)
    failed = int(summary_row.failed or 0)
    avg_duration = float(summary_row.avg_duration_sec or 0.0)
    asr = round((answered / total_calls) * 100, 2) if total_calls else 0.0

    by_business_rows = (
        db.session.query(
            business_col.label("business_id"),
            func.count().label("total_calls"),
            answered_expr.label("answered"),
            failed_expr.label("failed"),
            func.avg(duration_col).label("avg_duration_sec"),
        )
        .select_from(base_subquery)
        .group_by(business_col)
        .order_by(business_col.asc())
        .all()
    )
    by_business = []
    for row in by_business_rows:
        row_total = int(row.total_calls or 0)
        row_answered = int(row.answered or 0)
        by_business.append(
            {
                "business_id": row.business_id,
                "total_calls": row_total,
                "answered": row_answered,
                "failed": int(row.failed or 0),
                "asr": round((row_answered / row_total) * 100, 2) if row_total else 0.0,
                "avg_duration_sec": float(row.avg_duration_sec or 0.0),
            }
        )

    by_trunk_rows = (
        db.session.query(
            trunk_col.label("sip_trunk_id"),
            func.count().label("total_calls"),
            answered_expr.label("answered"),
            failed_expr.label("failed"),
            func.avg(duration_col).label("avg_duration_sec"),
        )
        .select_from(base_subquery)
        .group_by(trunk_col)
        .order_by(trunk_col.asc())
        .all()
    )
    by_trunk = []
    for row in by_trunk_rows:
        row_total = int(row.total_calls or 0)
        row_answered = int(row.answered or 0)
        by_trunk.append(
            {
                "sip_trunk_id": row.sip_trunk_id,
                "total_calls": row_total,
                "answered": row_answered,
                "failed": int(row.failed or 0),
                "asr": round((row_answered / row_total) * 100, 2) if row_total else 0.0,
                "avg_duration_sec": float(row.avg_duration_sec or 0.0),
            }
        )

    peak_concurrent_estimate = _compute_peak_concurrency(
        query=query,
        date_from=date_from,
        date_to=date_to,
    )

    return {
        "summary": {
            "total_calls": total_calls,
            "answered": answered,
            "failed": failed,
            "asr": asr,
            "avg_duration_sec": avg_duration,
            "peak_concurrent_estimate": peak_concurrent_estimate,
        },
        "by_business": by_business,
        "by_trunk": by_trunk,
    }, None


def _compute_peak_concurrency(query, date_from=None, date_to=None):
    rows = query.with_entities(
        CallLog.started_at,
        CallLog.ended_at,
        CallLog.duration_sec,
    ).all()
    if not rows:
        return 0

    now = datetime.utcnow()
    window_start = date_from
    window_end = date_to or now

    if window_start is None:
        starts = [r.started_at for r in rows if r.started_at is not None]
        window_start = min(starts) if starts else now

    events = []
    for row in rows:
        start = row.started_at
        if start is None:
            continue

        end = row.ended_at
        if end is None and row.duration_sec is not None:
            try:
                end = start + timedelta(seconds=max(0, int(row.duration_sec)))
            except (TypeError, ValueError):
                end = None
        if end is None:
            end = now

        # Keep only overlap with requested window.
        if end < window_start or start > window_end:
            continue
        if start < window_start:
            start = window_start
        if end > window_end:
            end = window_end
        if end < start:
            continue

        # [start, end): at same timestamp, process end(-1) before start(+1)
        events.append((start, +1))
        events.append((end, -1))

    if not events:
        return 0

    events.sort(key=lambda item: (item[0], item[1]))
    current = 0
    peak = 0
    for _ts, delta in events:
        current += delta
        if current > peak:
            peak = current
    return max(0, peak)
