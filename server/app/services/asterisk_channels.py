import re


def _extract_output_lines(ami_response):
    if not ami_response:
        return []
    lines = []
    for raw_line in str(ami_response).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Output:"):
            line = line[len("Output:") :].strip()
        if not line:
            continue
        if line.startswith("Response:") or line.startswith("Message:"):
            continue
        lines.append(line)
    return lines


def _endpoint_pattern(endpoint_name):
    escaped = re.escape(endpoint_name)
    return re.compile(rf"(@{escaped}\b|/{escaped}(?:-|$)|\b{escaped}\b)")


def get_live_channel_rows(ami_service):
    response = ami_service.run_command("core show channels concise")
    lines = _extract_output_lines(response)
    rows = []
    for line in lines:
        uniqueid = ""
        if "!" in line:
            parts = line.split("!")
            channel = parts[0].strip()
            state = parts[5].strip() if len(parts) > 5 else ""
            uniqueid = parts[11].strip() if len(parts) > 11 else ""
        else:
            channel = line
            state = ""
        rows.append({"channel": channel, "state": state, "uniqueid": uniqueid, "raw": line})
    return rows


def count_active_calls_for_endpoint(endpoint_name, ami_service):
    pattern = _endpoint_pattern(endpoint_name)
    rows = get_live_channel_rows(ami_service)

    matched = []
    for row in rows:
        channel = row["channel"]
        if channel.startswith("Local/"):
            continue
        if "PJSIP/" not in row["raw"]:
            continue
        if not pattern.search(row["raw"]):
            continue
        matched.append(row)

    return {"active_calls": len(matched), "matched_channels": matched}


def find_live_channel_by_uniqueid(uniqueid, ami_service):
    target = str(uniqueid or "").strip()
    if not target:
        return None
    rows = get_live_channel_rows(ami_service)
    for row in rows:
        if row.get("uniqueid") == target:
            return row
        if f"!{target}!" in row.get("raw", ""):
            return row
    return None


def find_live_channel_by_number(number, ami_service):
    target = str(number or "").strip()
    if not target:
        return {"channel_row": None, "ambiguous": False, "match_count": 0}
    rows = get_live_channel_rows(ami_service)
    matches = []
    # Match on non-Local channels only; require explicit number presence.
    for row in rows:
        channel = str(row.get("channel") or "")
        raw = str(row.get("raw") or "")
        if channel.startswith("Local/"):
            continue
        if target in raw or target in channel:
            matches.append(row)
    if not matches:
        return {"channel_row": None, "ambiguous": False, "match_count": 0}
    if len(matches) > 1:
        return {"channel_row": None, "ambiguous": True, "match_count": len(matches)}
    return {"channel_row": matches[0], "ambiguous": False, "match_count": 1}
