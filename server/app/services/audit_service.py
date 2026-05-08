import json

from app.extensions import db
from app.models import AuditLog


def log_audit_event(action, business_id=None, actor_user_id=None, metadata=None):
    event = AuditLog(
        action=action,
        business_id=business_id,
        actor_user_id=actor_user_id,
        metadata_json=json.dumps(metadata or {}),
    )
    db.session.add(event)
