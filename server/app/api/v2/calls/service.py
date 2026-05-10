from app.services.ami_service import AMIService
from app.services.asterisk_channels import count_active_calls_for_endpoint
from app.models import Business, SipTrunk


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


def originate_call(phone, channel_variables=None):
    return ami_service.originate_call(phone, channel_variables=channel_variables)


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


def originate_call_for_business(phone, business_id, sip_trunk_id, realtime_enabled):
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

    response = originate_call(
        phone,
        channel_variables={
            "SIP_TRUNK_ENDPOINT": endpoint,
            "SIP_TRUNK_ID": trunk.id,
            "BUSINESS_ID": trunk.business_id,
            "SIP_TRUNK_HOST": trunk.host,
            "SIP_TRUNK_PORT": trunk.port,
            "SIP_TRUNK_TYPE": trunk.type,
        },
    )
    return {
        "ami_response": response,
        "sip_trunk_id": trunk.id,
        "sip_endpoint": endpoint,
        "selected_by": selected_by,
        "active_calls_before": active_calls_before,
        "max_concurrent_calls": trunk.max_concurrent_calls,
    }, None
