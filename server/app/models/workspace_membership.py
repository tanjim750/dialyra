from datetime import datetime

from app.extensions import db


class WorkspaceMembership(db.Model):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        db.UniqueConstraint("business_id", "user_id", name="uq_workspace_business_user"),
        db.CheckConstraint(
            "role IN ('owner', 'admin', 'manager', 'agent', 'viewer')",
            name="ck_workspace_memberships_role_v2",
        ),
        db.CheckConstraint(
            "status IN ('active', 'inactive', 'suspended')",
            name="ck_workspace_memberships_status_v2",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default="viewer")
    status = db.Column(db.String(20), nullable=False, default="active")
    joined_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    business = db.relationship(
        "Business", backref=db.backref("memberships", lazy=True, cascade="all, delete-orphan")
    )
    user = db.relationship(
        "User", backref=db.backref("workspace_memberships", lazy=True, cascade="all, delete-orphan")
    )
