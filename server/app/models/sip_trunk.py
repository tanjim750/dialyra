from datetime import datetime

from app.extensions import db


class SipTrunk(db.Model):
    __tablename__ = "sip_trunks"
    __table_args__ = (
        db.UniqueConstraint("business_id", "name", name="uq_sip_trunks_business_name"),
    )

    id = db.Column(db.Integer, primary_key=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )
    name = db.Column(db.String(255), nullable=False)
    provider_name = db.Column(db.String(255), nullable=True)
    type = db.Column(db.String(20), nullable=False, default="registration")
    host = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=5060)
    username = db.Column(db.String(255), nullable=True)
    password_encrypted = db.Column(db.Text, nullable=True)
    auth_type = db.Column(db.String(20), nullable=False, default="userpass")
    transport = db.Column(db.String(20), nullable=False, default="udp")
    from_user = db.Column(db.String(255), nullable=True)
    from_domain = db.Column(db.String(255), nullable=True)
    context = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="inactive")
    max_concurrent_calls = db.Column(db.Integer, nullable=False, default=50)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    settings_json = db.Column(db.Text, nullable=True)
    apply_status = db.Column(db.String(20), nullable=False, default="pending")
    last_apply_error = db.Column(db.Text, nullable=True)
    previous_config_json = db.Column(db.Text, nullable=True)
    last_applied_at = db.Column(db.DateTime, nullable=True)
    last_rollback_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    business = db.relationship("Business", backref=db.backref("sip_trunks", lazy=True))
