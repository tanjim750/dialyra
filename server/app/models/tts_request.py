from datetime import datetime

from app.extensions import db


class TTSRequest(db.Model):
    __tablename__ = "tts_requests"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), nullable=False, unique=True, index=True)
    business_id = db.Column(
        db.Integer, db.ForeignKey("businesses.id"), nullable=False, index=True
    )
    text = db.Column(db.Text, nullable=False)
    language = db.Column(db.String(32), nullable=False, default="en")
    voice = db.Column(db.String(64), nullable=True)
    provider = db.Column(db.String(64), nullable=False, default="mock")
    status = db.Column(db.String(32), nullable=False, default="queued", index=True)

    audio_asset_id = db.Column(
        db.Integer, db.ForeignKey("audio_assets.id"), nullable=True, index=True
    )
    duration = db.Column(db.Float, nullable=True)
    generation_time_ms = db.Column(db.Integer, nullable=True)
    cache_key = db.Column(db.String(128), nullable=True, index=True)
    error_message = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
