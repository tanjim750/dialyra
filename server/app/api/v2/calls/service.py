from app.services.ami_service import AMIService
from app.models import SipTrunk


ami_service = AMIService()


def _slug(value):
    import re

    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return normalized or "trunk"


def _trunk_endpoint_name(trunk, realtime_enabled):
    if realtime_enabled:
        return f"dialyra_b{trunk.business_id}_t{trunk.id}_{_slug(trunk.name)}_ep"
    return f"dialyra-b{trunk.business_id}-t{trunk.id}-{_slug(trunk.name)}-endpoint"


def originate_call(phone, channel_variables=None):
    return ami_service.originate_call(phone, channel_variables=channel_variables)


def originate_call_for_business(phone, business_id, sip_trunk_id, realtime_enabled):
    trunk = (
        SipTrunk.query.filter_by(
            id=int(sip_trunk_id),
            business_id=int(business_id),
            is_active=True,
        ).first()
    )
    if trunk is None:
        return None, "SIP trunk not found for this business"

    endpoint = _trunk_endpoint_name(trunk, realtime_enabled=realtime_enabled)
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
    return {"ami_response": response, "sip_trunk_id": trunk.id, "sip_endpoint": endpoint}, None
