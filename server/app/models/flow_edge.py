from datetime import datetime

from app.extensions import db


class FlowEdge(db.Model):
    __tablename__ = "flow_edges"

    id = db.Column(db.Integer, primary_key=True)
    flow_id = db.Column(db.Integer, db.ForeignKey("flows.id"), nullable=False, index=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )
    source_node_id = db.Column(db.Integer, db.ForeignKey("flow_nodes.id"), nullable=False, index=True)
    target_node_id = db.Column(db.Integer, db.ForeignKey("flow_nodes.id"), nullable=False, index=True)
    condition_type = db.Column(db.String(50), nullable=False, default="always", index=True)
    condition_value = db.Column(db.String(255), nullable=True)
    priority = db.Column(db.Integer, nullable=False, default=100)
    label = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
