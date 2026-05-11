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

    flow_id = payload.get("flow_id")
    if flow_id is not None:
        try:
            if int(flow_id) <= 0:
                return "flow_id must be a positive integer"
        except (TypeError, ValueError):
            return "flow_id must be an integer"

    campaign_flow_id = payload.get("campaign_flow_id")
    if campaign_flow_id is not None:
        try:
            if int(campaign_flow_id) <= 0:
                return "campaign_flow_id must be a positive integer"
        except (TypeError, ValueError):
            return "campaign_flow_id must be an integer"

    campaign_id = payload.get("campaign_id")
    if campaign_id is not None:
        try:
            if int(campaign_id) <= 0:
                return "campaign_id must be a positive integer"
        except (TypeError, ValueError):
            return "campaign_id must be an integer"

    return None
