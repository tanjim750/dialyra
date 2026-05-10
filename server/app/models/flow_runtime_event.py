from datetime import datetime

from app.extensions import db


class FlowRuntimeEvent(db.Model):
    __tablename__ = "flow_runtime_events"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )
    call_session_id = db.Column(db.String(128), nullable=False, index=True)
    flow_runtime_session_id = db.Column(
        db.Integer, db.ForeignKey("flow_runtime_sessions.id"), nullable=True, index=True
    )
    node_id = db.Column(db.Integer, db.ForeignKey("flow_nodes.id"), nullable=True, index=True)
    event_type = db.Column(db.String(64), nullable=False, index=True)
    event_data = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
