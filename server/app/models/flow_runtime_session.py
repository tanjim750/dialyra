from datetime import datetime

from app.extensions import db


class FlowRuntimeSession(db.Model):
    __tablename__ = "flow_runtime_sessions"

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )
    call_session_id = db.Column(db.String(128), nullable=False, index=True)
    flow_id = db.Column(db.Integer, db.ForeignKey("flows.id"), nullable=False, index=True)
    flow_version_id = db.Column(db.Integer, db.ForeignKey("flow_versions.id"), nullable=False, index=True)
    current_node_id = db.Column(db.Integer, db.ForeignKey("flow_nodes.id"), nullable=True, index=True)
    status = db.Column(db.String(20), nullable=False, default="running", index=True)
    variables_json = db.Column(db.Text, nullable=True)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    ended_at = db.Column(db.DateTime, nullable=True, index=True)
