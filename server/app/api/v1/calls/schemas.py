def validate_originate_payload(payload):
    if not isinstance(payload, dict):
        return "Invalid JSON payload"

    phone = payload.get("phone")
    if not phone:
        return "Missing required field: phone"

    return None
