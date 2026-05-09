from __future__ import annotations

from app.models import WorkspaceMembership


def get_primary_membership(user_id):
    return (
        WorkspaceMembership.query.filter_by(user_id=user_id, status="active")
        .order_by(WorkspaceMembership.joined_at.asc())
        .first()
    )


def get_primary_business_id(user_id):
    membership = get_primary_membership(user_id)
    if membership is None:
        return None
    return membership.business_id

