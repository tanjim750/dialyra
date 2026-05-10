import uuid
import wave
from datetime import datetime
from pathlib import Path
import json

from flask import current_app
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import AudioAsset, Business, WorkspaceMembership
from app.services.ami_service import AMIService
from app.services.audit_service import log_audit_event

DEFAULT_ALLOWED_EXTENSIONS = {"wav", "gsm", "ulaw", "alaw", "mp3"}
ALLOWED_MIME_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/basic",
    "application/octet-stream",
}
UPLOADABLE_TYPES = {"upload", "tts", "system", "generated"}
UPLOADABLE_STATUS = {"processing", "ready", "failed", "deleted"}
DEFAULT_ALLOWED_CATEGORIES = {"ivr_prompt", "hold_music", "campaign_audio"}
VIEW_ROLES = {"owner", "admin", "manager", "agent", "viewer"}
MANAGE_ROLES = {"owner", "admin"}


def _storage_root():
    return Path(current_app.config.get("AUDIO_ASSETS_ROOT", "/data/audio-assets"))


def _asset_to_dict(asset):
    return {
        "id": asset.id,
        "uuid": asset.uuid,
        "business_id": asset.business_id,
        "name": asset.name,
        "slug": asset.slug,
        "type": asset.type,
        "category": asset.category,
        "file_name": asset.file_name,
        "original_file_name": asset.original_file_name,
        "file_path": asset.file_path,
        "public_path": asset.public_path,
        "duration": asset.duration,
        "format": asset.format,
        "sample_rate": asset.sample_rate,
        "channels": asset.channels,
        "file_size": asset.file_size,
        "source": asset.source,
        "language": asset.language,
        "voice": asset.voice,
        "status": asset.status,
        "is_deleted": bool(asset.is_deleted),
        "deleted_at": asset.deleted_at.isoformat() if asset.deleted_at else None,
        "deleted_by": asset.deleted_by,
        "delete_reason": asset.delete_reason,
        "created_by": asset.created_by,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }

def _load_metadata(asset):
    if not asset.metadata_json:
        return {}
    try:
        parsed = json.loads(asset.metadata_json)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {}


def _save_metadata(asset, metadata):
    asset.metadata_json = json.dumps(metadata)


def _active_membership(actor_user_id, business_id):
    return WorkspaceMembership.query.filter_by(
        user_id=actor_user_id, business_id=business_id, status="active"
    ).first()


def _can_view_business(actor_user, business):
    if actor_user.role == "superuser":
        return True
    if actor_user.role == "stuff" and business.owner_user_id == actor_user.id:
        return True
    membership = _active_membership(actor_user.id, business.id)
    return membership is not None and membership.role in VIEW_ROLES


def _can_manage_business(actor_user, business):
    if actor_user.role == "superuser":
        return True
    if actor_user.role == "stuff" and business.owner_user_id == actor_user.id:
        return True
    membership = _active_membership(actor_user.id, business.id)
    return membership is not None and membership.role in MANAGE_ROLES


def _extract_wav_meta(path):
    try:
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.getnframes()
            sample_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            duration = float(frames) / float(sample_rate) if sample_rate else None
            return duration, sample_rate, channels
    except Exception:
        return None, None, None


def _slugify(value):
    import re

    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return normalized or "audio-asset"


def _allowed_categories():
    extra = current_app.config.get("AUDIO_ASSET_EXTRA_CATEGORIES", "")
    if not extra:
        return set(DEFAULT_ALLOWED_CATEGORIES)
    values = {item.strip().lower() for item in str(extra).split(",") if item.strip()}
    return set(DEFAULT_ALLOWED_CATEGORIES).union(values)


def _allowed_extensions():
    raw = current_app.config.get("AUDIO_ASSET_ALLOWED_EXTENSIONS", "")
    if not raw:
        return set(DEFAULT_ALLOWED_EXTENSIONS)
    values = {item.strip().lower() for item in str(raw).split(",") if item.strip()}
    return values or set(DEFAULT_ALLOWED_EXTENSIONS)


def _resolve_business_for_upload(actor_user, business_id):
    if business_id is None:
        return None, "Missing required field: business_id"
    try:
        normalized = int(business_id)
    except (TypeError, ValueError):
        return None, "Invalid business_id"
    business = Business.query.get(normalized)
    if business is None:
        return None, "Business not found"
    if not _can_manage_business(actor_user, business):
        return None, "Insufficient permission for this business"
    return business, None


def _uploaded_file_size(file_storage):
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return None
    pos = stream.tell()
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(pos)
    return int(size)


def upload_audio_asset(actor_user, form_data, file_storage):
    business, error = _resolve_business_for_upload(actor_user, form_data.get("business_id"))
    if error:
        return None, error
    if file_storage is None:
        return None, "Missing required file"

    original_name = file_storage.filename or ""
    safe_original = secure_filename(original_name)
    if not safe_original:
        return None, "Invalid file name"
    ext = safe_original.rsplit(".", 1)[-1].lower() if "." in safe_original else ""
    if ext not in _allowed_extensions():
        return None, "Unsupported file format"
    enforce_mime = bool(current_app.config.get("AUDIO_ASSET_ENFORCE_MIME", True))
    mimetype = (getattr(file_storage, "mimetype", "") or "").strip().lower()
    if enforce_mime and mimetype and mimetype not in ALLOWED_MIME_TYPES:
        return None, f"Unsupported MIME type: {mimetype}"

    max_size_mb = int(current_app.config.get("AUDIO_ASSET_MAX_FILE_SIZE_MB", 20))
    max_size_bytes = max(1, max_size_mb) * 1024 * 1024
    upload_size = _uploaded_file_size(file_storage)
    if upload_size is not None and upload_size > max_size_bytes:
        return None, f"File size exceeds limit ({max_size_mb} MB)"

    name = (form_data.get("name") or "").strip() or safe_original
    slug = _slugify(name)
    asset_type = (form_data.get("type") or "upload").strip().lower()
    category = (form_data.get("category") or "").strip().lower() or None
    language = (form_data.get("language") or "").strip() or None
    voice = (form_data.get("voice") or "").strip() or None
    source = (form_data.get("source") or "manual_upload").strip() or None
    status = (form_data.get("status") or "ready").strip().lower()

    if asset_type not in UPLOADABLE_TYPES:
        return None, "Invalid audio type"
    if status not in UPLOADABLE_STATUS:
        return None, "Invalid audio status"
    if not category:
        return None, "category is required"
    if category not in _allowed_categories():
        return None, "Invalid category"

    exists = AudioAsset.query.filter_by(
        business_id=business.id, slug=slug, is_deleted=False
    ).first()
    if exists is not None:
        return None, "Audio slug already exists in this business"

    asset_uuid = str(uuid.uuid4())
    file_name = f"{asset_uuid}.{ext}"
    dest_dir = _storage_root() / str(business.id) / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file_name
    file_storage.save(dest_path)

    file_size = dest_path.stat().st_size if dest_path.exists() else None
    duration = None
    sample_rate = None
    channels = None
    if ext == "wav":
        duration, sample_rate, channels = _extract_wav_meta(dest_path)

    relative_public = f"/audio-assets/{business.id}/uploads/{file_name}"
    asset = AudioAsset(
        uuid=asset_uuid,
        business_id=business.id,
        name=name,
        slug=slug,
        type=asset_type,
        category=category,
        file_name=file_name,
        original_file_name=safe_original,
        file_path=str(dest_path),
        public_path=relative_public,
        duration=duration,
        format=ext,
        sample_rate=sample_rate,
        channels=channels,
        file_size=file_size,
        source=source,
        language=language,
        voice=voice,
        status=status,
        created_by=actor_user.id,
        is_deleted=False,
    )
    db.session.add(asset)
    db.session.commit()

    log_audit_event(
        "audio_asset.uploaded",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"audio_asset_id": asset.id, "name": asset.name},
    )
    db.session.commit()

    return _asset_to_dict(asset), None


def list_audio_assets(actor_user, business_id=None, include_deleted=False):
    query = AudioAsset.query

    if actor_user.role == "superuser":
        if business_id is not None:
            try:
                query = query.filter(AudioAsset.business_id == int(business_id))
            except (TypeError, ValueError):
                return None, "Invalid business_id"
    else:
        owned_ids = [b.id for b in Business.query.filter_by(owner_user_id=actor_user.id).all()]
        member_ids = [
            m.business_id
            for m in WorkspaceMembership.query.filter_by(user_id=actor_user.id, status="active").all()
        ]
        allowed_ids = sorted(set(owned_ids + member_ids))
        if not allowed_ids:
            return [], None
        query = query.filter(AudioAsset.business_id.in_(allowed_ids))
        if business_id is not None:
            try:
                normalized = int(business_id)
            except (TypeError, ValueError):
                return None, "Invalid business_id"
            if normalized not in allowed_ids:
                return None, "Insufficient permission for this business"
            query = query.filter(AudioAsset.business_id == normalized)

    if not include_deleted:
        query = query.filter(AudioAsset.is_deleted.is_(False))

    items = query.order_by(AudioAsset.created_at.desc()).all()
    return [_asset_to_dict(item) for item in items], None


def get_audio_asset(actor_user, asset_id):
    asset = AudioAsset.query.get(asset_id)
    if asset is None:
        return None, "Audio asset not found"
    business = Business.query.get(asset.business_id)
    if business is None:
        return None, "Business not found"
    if not _can_view_business(actor_user, business):
        return None, "Insufficient permission for this business"
    return _asset_to_dict(asset), None


def update_audio_asset(actor_user, asset_id, payload):
    asset = AudioAsset.query.get(asset_id)
    if asset is None:
        return None, "Audio asset not found"
    business = Business.query.get(asset.business_id)
    if business is None:
        return None, "Business not found"
    if not _can_manage_business(actor_user, business):
        return None, "Insufficient permission for this business"
    if asset.is_deleted:
        return None, "Cannot update deleted audio asset"

    if "name" in payload:
        next_name = (payload.get("name") or "").strip()
        if not next_name:
            return None, "name cannot be empty"
        next_slug = _slugify(next_name)
        duplicate = AudioAsset.query.filter(
            AudioAsset.business_id == business.id,
            AudioAsset.slug == next_slug,
            AudioAsset.is_deleted.is_(False),
            AudioAsset.id != asset.id,
        ).first()
        if duplicate is not None:
            return None, "Audio slug already exists in this business"
        asset.name = next_name
        asset.slug = next_slug

    if "type" in payload:
        next_type = (payload.get("type") or "").strip().lower()
        if next_type not in UPLOADABLE_TYPES:
            return None, "Invalid audio type"
        asset.type = next_type

    if "category" in payload:
        next_category = (payload.get("category") or "").strip().lower()
        if not next_category:
            return None, "category is required"
        if next_category not in _allowed_categories():
            return None, "Invalid category"
        asset.category = next_category

    if "status" in payload:
        next_status = (payload.get("status") or "").strip().lower()
        if next_status not in UPLOADABLE_STATUS:
            return None, "Invalid audio status"
        asset.status = next_status

    if "language" in payload:
        asset.language = (payload.get("language") or "").strip() or None
    if "voice" in payload:
        asset.voice = (payload.get("voice") or "").strip() or None
    if "source" in payload:
        asset.source = (payload.get("source") or "").strip() or None

    db.session.commit()
    log_audit_event(
        "audio_asset.updated",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"audio_asset_id": asset.id},
    )
    db.session.commit()
    return _asset_to_dict(asset), None


def resolve_audio_asset_file(actor_user, asset_id, purpose="stream"):
    asset = AudioAsset.query.get(asset_id)
    if asset is None:
        return None, "Audio asset not found"
    business = Business.query.get(asset.business_id)
    if business is None:
        return None, "Business not found"
    if not _can_view_business(actor_user, business):
        log_audit_event(
            "audio_asset.access_denied",
            business_id=business.id,
            actor_user_id=actor_user.id,
            metadata={"audio_asset_id": asset.id, "purpose": purpose},
        )
        db.session.commit()
        return None, "Insufficient permission for this business"
    if asset.is_deleted or asset.status == "deleted":
        return None, "Audio asset is deleted"
    path = Path(asset.file_path) if asset.file_path else None
    if path is None or not path.exists() or not path.is_file():
        return None, "Audio file not found"
    log_audit_event(
        "audio_asset.accessed",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"audio_asset_id": asset.id, "purpose": purpose},
    )
    db.session.commit()
    return {
        "asset": asset,
        "path": path,
        "download_name": asset.original_file_name or asset.file_name,
        "mimetype": _guess_mimetype(asset.format),
    }, None


def _guess_mimetype(audio_format):
    value = (audio_format or "").strip().lower()
    if value == "wav":
        return "audio/wav"
    if value == "mp3":
        return "audio/mpeg"
    if value in {"ulaw", "alaw", "gsm"}:
        return "audio/basic"
    return "application/octet-stream"


def delete_audio_asset(actor_user, asset_id, delete_reason=None):
    asset = AudioAsset.query.get(asset_id)
    if asset is None:
        return None, "Audio asset not found"

    business = Business.query.get(asset.business_id)
    if business is None:
        return None, "Business not found"
    if not _can_manage_business(actor_user, business):
        return None, "Insufficient permission for this business"

    if asset.is_deleted:
        return {
            "message": "Audio asset already deleted",
            "audio_asset_id": asset.id,
            "is_deleted": True,
        }, None

    # Physical file deletion first.
    path = Path(asset.file_path) if asset.file_path else None
    try:
        if path and path.exists():
            path.unlink()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log_audit_event(
            "audio_asset.delete_failed",
            business_id=business.id,
            actor_user_id=actor_user.id,
            metadata={"audio_asset_id": asset.id, "error": str(exc)},
        )
        db.session.commit()
        return None, f"Failed to delete audio file: {exc}"

    asset.is_deleted = True
    asset.status = "deleted"
    asset.deleted_at = datetime.utcnow()
    asset.deleted_by = actor_user.id
    asset.delete_reason = (delete_reason or "").strip() or None
    db.session.commit()

    log_audit_event(
        "audio_asset.deleted",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={
            "audio_asset_id": asset.id,
            "file_deleted": True,
            "reason": asset.delete_reason,
        },
    )
    db.session.commit()

    return {
        "message": "Audio asset soft deleted and file removed",
        "audio_asset_id": asset.id,
        "is_deleted": True,
        "deleted_at": asset.deleted_at.isoformat() if asset.deleted_at else None,
    }, None


def sync_audio_asset_to_asterisk(actor_user, asset_id):
    asset = AudioAsset.query.get(asset_id)
    if asset is None:
        return None, "Audio asset not found"
    business = Business.query.get(asset.business_id)
    if business is None:
        return None, "Business not found"
    if not _can_manage_business(actor_user, business):
        return None, "Insufficient permission for this business"
    if asset.is_deleted:
        return None, "Audio asset is deleted"

    path = Path(asset.file_path) if asset.file_path else None
    if path is None or not path.exists():
        return None, "Audio file not found"

    metadata = _load_metadata(asset)
    sync_info = {
        "status": "synced",
        "synced_at": datetime.utcnow().isoformat(),
        "synced_by": actor_user.id,
        "file_path": asset.file_path,
    }
    metadata["asterisk_sync"] = sync_info
    _save_metadata(asset, metadata)
    db.session.commit()

    log_audit_event(
        "audio_asset.synced_to_asterisk",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"audio_asset_id": asset.id},
    )
    db.session.commit()
    return {
        "audio_asset_id": asset.id,
        "status": "synced",
        "details": sync_info,
    }, None


def test_audio_asset_playback(actor_user, asset_id):
    asset = AudioAsset.query.get(asset_id)
    if asset is None:
        return None, "Audio asset not found"
    business = Business.query.get(asset.business_id)
    if business is None:
        return None, "Business not found"
    if not _can_manage_business(actor_user, business):
        return None, "Insufficient permission for this business"
    if asset.is_deleted:
        return None, "Audio asset is deleted"

    path = Path(asset.file_path) if asset.file_path else None
    if path is None or not path.exists():
        return None, "Audio file not found"

    test_channel = (current_app.config.get("AUDIO_PLAYBACK_TEST_CHANNEL") or "").strip()
    if not test_channel:
        return None, "AUDIO_PLAYBACK_TEST_CHANNEL is not configured"

    # Playback() should receive a filename without extension.
    playback_target = str(path)
    if "." in playback_target:
        playback_target = playback_target.rsplit(".", 1)[0]

    ami_ok = False
    ami_details = ""
    ami = AMIService()
    try:
        response = ami.originate_application_playback(
            test_channel,
            playback_target,
            timeout_ms=int(current_app.config.get("AUDIO_PLAYBACK_TEST_TIMEOUT_MS", 10000)),
        )
        lowered = (response or "").lower()
        ami_ok = "response: success" in lowered and "error" not in lowered
        ami_details = (response or "")[:500]
    except Exception as exc:  # noqa: BLE001
        ami_details = str(exc)

    test_info = {
        "tested_at": datetime.utcnow().isoformat(),
        "tested_by": actor_user.id,
        "file_exists": True,
        "test_channel": test_channel,
        "playback_target": playback_target,
        "ami_ok": ami_ok,
        "ami_details": ami_details,
    }
    metadata = _load_metadata(asset)
    metadata["playback_test"] = test_info
    _save_metadata(asset, metadata)
    db.session.commit()

    log_audit_event(
        "audio_asset.playback_tested",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"audio_asset_id": asset.id, "ami_ok": ami_ok},
    )
    db.session.commit()

    return {
        "audio_asset_id": asset.id,
        "status": "ok" if ami_ok else "warning",
        "details": test_info,
    }, None
