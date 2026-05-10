from .base import NodeExecutionResult, node_config


def _match_rule(variables, rule):
    field = str(rule.get("field") or "").strip()
    operator = str(rule.get("operator") or "equals").strip().lower()
    expected = rule.get("value")
    actual = variables.get(field)

    if operator == "equals":
        return actual == expected
    if operator == "not_equals":
        return actual != expected
    if operator == "contains":
        return str(expected) in str(actual or "")
    if operator == "greater_than":
        try:
            return float(actual) > float(expected)
        except (TypeError, ValueError):
            return False
    if operator == "less_than":
        try:
            return float(actual) < float(expected)
        except (TypeError, ValueError):
            return False
    if operator == "exists":
        return field in variables and variables.get(field) is not None
    if operator == "not_exists":
        return field not in variables or variables.get(field) is None
    if operator == "in":
        if isinstance(expected, list):
            return actual in expected
        return False
    if operator == "not_in":
        if isinstance(expected, list):
            return actual not in expected
        return True
    return False


def execute(actor_business, node_payload, variables):
    cfg = node_config(node_payload)
    rules = cfg.get("rules") if isinstance(cfg.get("rules"), list) else []
    match_mode = str(cfg.get("match_mode") or "all").strip().lower()

    matches = [_match_rule(variables, rule) for rule in rules if isinstance(rule, dict)]
    matched = all(matches) if match_mode == "all" else any(matches) if matches else False
    variables["__condition_matched"] = bool(matched)

    return NodeExecutionResult(
        runtime_action={
            "type": "noop",
            "node_type": "condition",
            "matched": bool(matched),
        },
        metadata={
            "auto_result_type": "condition_matched" if matched else "condition_not_matched",
            "auto_value": "1" if matched else "0",
            "condition_matched": bool(matched),
        },
    )
