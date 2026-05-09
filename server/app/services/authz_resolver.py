from __future__ import annotations

from flask import g, request

from app.models import WorkspaceMembership


def resolve_target_business_id(default_business_id=None, param_name="business_id"):
    if getattr(g, "target_business", None) is not None:
        return g.target_business.id

    if request.view_args and param_name in request.view_args:
        raw_value = request.view_args.get(param_name)
    else:
        payload = request.get_json(silent=True) or {}
        raw_value = payload.get(param_name)

    if raw_value is None:
        return default_business_id

    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def get_active_membership(user_id, business_id):
    if not business_id:
        return None
    return WorkspaceMembership.query.filter_by(
        user_id=user_id, business_id=business_id, status="active"
    ).first()

