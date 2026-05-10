from datetime import datetime

from app.extensions import db


class FlowVersion(db.Model):
    __tablename__ = "flow_versions"

    id = db.Column(db.Integer, primary_key=True)
    flow_id = db.Column(db.Integer, db.ForeignKey("flows.id"), nullable=False, index=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )
    version_number = db.Column(db.Integer, nullable=False)
    snapshot_json = db.Column(db.Text, nullable=False)
    published_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    published_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
