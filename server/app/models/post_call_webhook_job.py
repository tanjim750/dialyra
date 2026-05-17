from datetime import datetime

from app.extensions import db


class PostCallWebhookJob(db.Model):
    __tablename__ = "post_call_webhook_jobs"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )

    call_action_id = db.Column(db.String(64), nullable=False, index=True)
    call_session_id = db.Column(db.String(128), nullable=False, index=True)
    call_log_uuid = db.Column(db.String(64), nullable=True, index=True)

    node_id = db.Column(db.Integer, db.ForeignKey("flow_nodes.id"), nullable=True, index=True)
    node_key = db.Column(db.String(128), nullable=True, index=True)
    sequence_no = db.Column(db.Integer, nullable=False, default=1)

    method = db.Column(db.String(16), nullable=False)
    url = db.Column(db.Text, nullable=False)
    auth_json = db.Column(db.Text, nullable=True)
    headers_json = db.Column(db.Text, nullable=True)
    payload_json = db.Column(db.Text, nullable=True)
    timeout_seconds = db.Column(db.Integer, nullable=False, default=5)

    idempotency_key = db.Column(db.String(255), nullable=False, unique=True, index=True)
    status = db.Column(db.String(32), nullable=False, default="pending", index=True)
    attempt_count = db.Column(db.Integer, nullable=False, default=0)
    next_retry_at = db.Column(db.DateTime, nullable=True, index=True)

    last_error = db.Column(db.Text, nullable=True)
    last_response_code = db.Column(db.Integer, nullable=True)
    last_response_body = db.Column(db.Text, nullable=True)
    last_attempt_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

