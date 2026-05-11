from datetime import datetime

from app.extensions import db


class CallEvent(db.Model):
    __tablename__ = "call_events"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(db.Integer, db.ForeignKey("businesses.id"), nullable=True, index=True)
    call_log_id = db.Column(db.Integer, db.ForeignKey("call_logs.id"), nullable=True, index=True)
    call_session_id = db.Column(
        db.Integer, db.ForeignKey("call_sessions.id"), nullable=True, index=True
    )

    event_name = db.Column(db.String(64), nullable=False, index=True)
    event_fingerprint = db.Column(db.String(64), nullable=False, unique=True, index=True)
    event_payload_json = db.Column(db.Text, nullable=False)

    action_id = db.Column(db.String(64), nullable=True, index=True)
    uniqueid = db.Column(db.String(64), nullable=True, index=True)
    linkedid = db.Column(db.String(64), nullable=True, index=True)

    processing_status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    process_attempts = db.Column(db.Integer, nullable=False, default=0)
    last_error = db.Column(db.Text, nullable=True)
    processed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
