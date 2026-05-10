from datetime import datetime

from app.extensions import db


class AudioAsset(db.Model):
    __tablename__ = "audio_assets"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), nullable=False, unique=True, index=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), nullable=True, index=True)
    type = db.Column(db.String(32), nullable=False, default="upload")
    category = db.Column(db.String(64), nullable=True)

    file_name = db.Column(db.String(255), nullable=False)
    original_file_name = db.Column(db.String(255), nullable=True)
    file_path = db.Column(db.String(1024), nullable=False)
    public_path = db.Column(db.String(1024), nullable=True)
    file_size = db.Column(db.BigInteger, nullable=True)
    format = db.Column(db.String(32), nullable=True)
    duration = db.Column(db.Float, nullable=True)
    sample_rate = db.Column(db.Integer, nullable=True)
    channels = db.Column(db.Integer, nullable=True)

    source = db.Column(db.String(64), nullable=True)
    language = db.Column(db.String(32), nullable=True)
    voice = db.Column(db.String(64), nullable=True)
    status = db.Column(db.String(32), nullable=False, default="processing")

    metadata_json = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Soft-delete trace fields (file may be physically removed later)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    deleted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    delete_reason = db.Column(db.String(255), nullable=True)
