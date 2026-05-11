from datetime import datetime

from app.extensions import db


class CallSession(db.Model):
    __tablename__ = "call_sessions"

    id = db.Column(db.Integer, primary_key=True)

    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )
    flow_id = db.Column(db.Integer, db.ForeignKey("flows.id"), nullable=True, index=True)
    flow_version_id = db.Column(
        db.Integer, db.ForeignKey("flow_versions.id"), nullable=True, index=True
    )
    campaign_id = db.Column(db.Integer, nullable=True, index=True)
    contact_id = db.Column(db.Integer, nullable=True, index=True)
    sip_trunk_id = db.Column(
        db.Integer, db.ForeignKey("sip_trunks.id"), nullable=True, index=True
    )

    call_direction = db.Column(db.String(20), nullable=False, default="outbound", index=True)
    status = db.Column(db.String(32), nullable=False, default="queued", index=True)
    phone_number = db.Column(db.String(64), nullable=False, index=True)
    caller_id = db.Column(db.String(128), nullable=True)
    channel = db.Column(db.String(255), nullable=True)
    uniqueid = db.Column(db.String(64), nullable=True, index=True)
    linkedid = db.Column(db.String(64), nullable=True, index=True)
    ami_action_id = db.Column(db.String(64), nullable=True, unique=True, index=True)

    variables_json = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)

    started_at = db.Column(db.DateTime, nullable=True, index=True)
    answered_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    hangup_cause = db.Column(db.String(64), nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
