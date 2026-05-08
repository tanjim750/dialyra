from datetime import datetime
import uuid as uuid_lib

from app.extensions import db


class Business(db.Model):
    __tablename__ = "businesses"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(
        db.String(36),
        nullable=False,
        unique=True,
        index=True,
        default=lambda: str(uuid_lib.uuid4()),
    )
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), nullable=False, unique=True, index=True)
    owner_name = db.Column(db.String(255), nullable=False)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(255), nullable=False)
    timezone = db.Column(db.String(100), nullable=False, default="Asia/Dhaka")
    country = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="active")
    logo_path = db.Column(db.String(500), nullable=True)
    settings_json = db.Column(db.Text, nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        index=True,
    )

    owner_user = db.relationship("User", foreign_keys=[owner_user_id], lazy="joined")
