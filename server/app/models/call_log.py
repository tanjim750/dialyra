from datetime import datetime

from app.extensions import db


class CallLog(db.Model):
    __tablename__ = "call_logs"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), nullable=False, unique=True, index=True)
    action_id = db.Column(db.String(64), nullable=True, index=True)
    asterisk_uniqueid = db.Column(db.String(64), nullable=True, index=True)
    linkedid = db.Column(db.String(64), nullable=True, index=True)

    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )
    sip_trunk_id = db.Column(
        db.Integer, db.ForeignKey("sip_trunks.id"), nullable=True, index=True
    )
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    direction = db.Column(db.String(20), nullable=False, default="outbound")
    from_number = db.Column(db.String(64), nullable=True)
    to_number = db.Column(db.String(64), nullable=False, index=True)
    dialed_number = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="queued", index=True)

    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    answered_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    duration_sec = db.Column(db.Integer, nullable=True)
    billsec = db.Column(db.Integer, nullable=True)

    hangup_cause = db.Column(db.String(32), nullable=True)
    hangup_cause_text = db.Column(db.String(255), nullable=True)
    raw_event_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
