def validate_originate_payload(payload):
    if not isinstance(payload, dict):
        return "Invalid JSON payload"

    phone = payload.get("phone")
    if not phone:
        return "Missing required field: phone"

    sip_trunk_id = payload.get("sip_trunk_id")
    if sip_trunk_id is not None:
        try:
            if int(sip_trunk_id) <= 0:
                return "sip_trunk_id must be a positive integer"
        except (TypeError, ValueError):
            return "sip_trunk_id must be an integer"

    return None
