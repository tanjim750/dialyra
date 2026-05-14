import hashlib
import json
import uuid
import unicodedata
import re
from datetime import datetime
from pathlib import Path

from flask import current_app

from app.api.v2.tts.provider_factory import enabled_providers, get_provider
from app.api.v2.tts.providers.base import TTSProviderError
from app.extensions import db
from app.models import AudioAsset, Business, TTSRequest, WorkspaceMembership
from app.services.audit_service import log_audit_event

TTS_STATUSES = {"queued", "processing", "completed", "failed"}
VIEW_ROLES = {"owner", "admin", "manager", "agent", "viewer"}
MANAGE_ROLES = {"owner", "admin"}


def _storage_root():
    return Path(current_app.config.get("AUDIO_ASSETS_ROOT", "/data/audio-assets"))


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


def _resolve_business(actor_user, business_id, *, manage=False):
    if business_id is None:
        return None, "Missing required field: business_id"
    try:
        normalized = int(business_id)
    except (TypeError, ValueError):
        return None, "Invalid business_id"
    business = Business.query.get(normalized)
    if business is None:
        return None, "Business not found"
    allowed = _can_manage_business(actor_user, business) if manage else _can_view_business(actor_user, business)
    if not allowed:
        return None, "Insufficient permission for this business"
    return business, None


def _slugify(value):
    import re

    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return normalized or "tts-audio"


def _serialize_tts_request(row):
    return {
        "id": row.id,
        "uuid": row.uuid,
        "business_id": row.business_id,
        "text": row.text,
        "language": row.language,
        "voice": row.voice,
        "provider": row.provider,
        "status": row.status,
        "audio_asset_id": row.audio_asset_id,
        "duration": row.duration,
        "generation_time_ms": row.generation_time_ms,
        "cache_key": row.cache_key,
        "error_message": row.error_message,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _normalize_text_for_hash(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.casefold()
    normalized = " ".join(normalized.split())
    return normalized.strip()


def _render_tts_text_template(text: str, variables: dict | None) -> str:
    if not variables or not isinstance(variables, dict):
        return text or ""

    def _replace(match):
        key = (match.group(1) or "").strip()
        if not key:
            return ""
        value = variables.get(key)
        return "" if value is None else str(value)

    return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", _replace, text or "")


def _is_cache_asset_reusable(*, asset, business_id: int) -> bool:
    if asset is None:
        return False
    if int(getattr(asset, "business_id", 0) or 0) != int(business_id):
        return False
    if bool(getattr(asset, "is_deleted", False)):
        return False
    if str(getattr(asset, "status", "") or "").strip().lower() != "ready":
        return False
    path = Path(getattr(asset, "file_path", "") or "")
    if not path.exists() or not path.is_file():
        return False
    return True


def _extract_template_variable_keys(text: str) -> list[str]:
    keys = []
    for match in re.finditer(r"\{\{\s*([^{}]+?)\s*\}\}", text or ""):
        key = (match.group(1) or "").strip()
        if key:
            keys.append(key)
    # preserve order while removing duplicates
    return list(dict.fromkeys(keys))


def _validate_template_variables(variables):
    if variables is None:
        return None
    if not isinstance(variables, dict):
        return "Invalid variables: must be an object/dictionary"
    for key in variables.keys():
        if not isinstance(key, str):
            return "Invalid variables: all variable keys must be strings"
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            return (
                f"Invalid variable key '{key}'. "
                "Allowed pattern: [A-Za-z_][A-Za-z0-9_]*"
            )
    return None


def _resolve_provider_variant(payload: dict) -> str:
    return str(
        payload.get("provider_variant")
        or payload.get("provider_type")
        or payload.get("google_type")
        or ""
    ).strip().lower()


def _generate_provider_audio_and_asset(
    actor_user,
    business,
    text,
    language,
    voice,
    provider_name,
    provider_options=None,
):
    provider, err = get_provider(provider_name)
    if err:
        raise TTSProviderError(err)

    audio_uuid = str(uuid.uuid4())
    file_name = f"{audio_uuid}.wav"
    dest_dir = _storage_root() / str(business.id) / "tts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / file_name
    generation_result = provider.generate_audio(
        text=text,
        language=language,
        voice=voice,
        output_path=str(path),
        provider_options=provider_options or {},
    )
    file_size = path.stat().st_size if path.exists() else None

    name = f"TTS: {(text or '').strip()[:40] or 'prompt'}"
    slug = _slugify(name)
    collision = AudioAsset.query.filter_by(
        business_id=business.id, slug=slug, is_deleted=False
    ).first()
    if collision is not None:
        slug = f"{slug}-{audio_uuid[:8]}"

    asset = AudioAsset(
        uuid=audio_uuid,
        business_id=business.id,
        name=name,
        slug=slug,
        type="tts",
        category="tts_prompt",
        file_name=file_name,
        original_file_name=file_name,
        file_path=str(path),
        public_path=f"/audio-assets/{business.id}/tts/{file_name}",
        duration=generation_result.duration,
        format=generation_result.format or "wav",
        sample_rate=generation_result.sample_rate,
        channels=generation_result.channels,
        file_size=file_size,
        source=generation_result.source or f"tts_{provider_name}",
        language=language,
        voice=voice,
        status="ready",
        metadata_json=json.dumps(
            {
                "origin": "tts",
                "provider": provider_name,
                "language": language,
                "voice": voice,
            }
        ),
        created_by=actor_user.id,
        is_deleted=False,
    )
    db.session.add(asset)
    db.session.flush()
    return asset, generation_result.duration


def _prepare_tts_request(actor_user, payload):
    business, error = _resolve_business(actor_user, payload.get("business_id"), manage=True)
    if error:
        return None, error, None, None

    text_template = (payload.get("text") or "").strip()
    variables = payload.get("variables")
    variables_error = _validate_template_variables(variables)
    if variables_error:
        return None, variables_error, None, None

    required_keys = _extract_template_variable_keys(text_template)
    if required_keys:
        if not isinstance(variables, dict):
            return None, "Missing variables object for templated text", None, None
        missing_keys = [key for key in required_keys if key not in variables]
        if missing_keys:
            return None, f"Missing required variables: {', '.join(missing_keys)}", None, None

    text = _render_tts_text_template(text_template, variables).strip()
    if not text:
        return None, "Missing required field: text", None, None

    language = (payload.get("language") or "en").strip().lower()
    voice = (payload.get("voice") or "").strip()
    provider = (payload.get("provider") or current_app.config.get("TTS_DEFAULT_PROVIDER", "mock")).strip().lower()
    provider_variant = _resolve_provider_variant(payload)
    if not voice:
        if provider == "google":
            voice = "gemini-tts:Kore"
        elif provider == "openai":
            voice = "alloy"
        elif provider == "elevenlabs":
            voice = str(current_app.config.get("ELEVENLABS_TTS_VOICE_ID", "")).strip() or "JBFqnCBsd6RMkjVDRZzb"
        else:
            voice = "female_en_1"
    provider_adapter, err = get_provider(provider)
    if err:
        return None, err, None, None
    if language not in provider_adapter.get_supported_languages():
        return None, "Unsupported language", None, None
    if provider != "google" and voice not in provider_adapter.get_supported_voices():
        return None, "Unsupported voice", None, None

    request_uuid = str(uuid.uuid4())
    # Cache key keeps provider/language/voice semantics while matching text by hash.
    text_hash = hashlib.sha256(
        _normalize_text_for_hash(text).encode("utf-8")
    ).hexdigest()
    cache_key = hashlib.sha256(
        f"{provider}|{provider_variant}|{language}|{voice}|{text_hash}".encode("utf-8")
    ).hexdigest()

    # Cache hit: reuse previously completed TTS output for identical key.
    cached = (
        TTSRequest.query.filter_by(
            business_id=business.id,
            cache_key=cache_key,
            status="completed",
        )
        .order_by(TTSRequest.id.desc())
        .first()
    )
    if cached is not None and cached.audio_asset_id is not None:
        cached_asset = AudioAsset.query.get(cached.audio_asset_id)
        if _is_cache_asset_reusable(asset=cached_asset, business_id=business.id):
            row = TTSRequest(
                uuid=str(uuid.uuid4()),
                business_id=business.id,
                text=text,
                language=language,
                voice=voice,
                provider=provider,
                status="completed",
                audio_asset_id=cached.audio_asset_id,
                duration=cached.duration,
                generation_time_ms=0,
                cache_key=cache_key,
                error_message=None,
                created_by=actor_user.id,
                metadata_json=json.dumps(
                    {
                        "mode": "cache_hit",
                        "cached_from_tts_request_id": cached.id,
                        "cached_audio_asset_id": cached.audio_asset_id,
                        "variables": variables if isinstance(variables, dict) else None,
                    }
                ),
            )
            db.session.add(row)
            db.session.commit()
            log_audit_event(
                "tts.cache_hit",
                business_id=business.id,
                actor_user_id=actor_user.id,
                metadata={"tts_request_id": row.id, "audio_asset_id": row.audio_asset_id},
            )
            db.session.commit()
            return _serialize_tts_request(row), None, None, None

    row = TTSRequest(
        uuid=request_uuid,
        business_id=business.id,
        text=text,
        language=language,
        voice=voice,
        provider=provider,
        status="processing",
        cache_key=cache_key,
        created_by=actor_user.id,
        metadata_json=json.dumps(
            {
                "mode": "sync-provider",
                "provider": provider,
                "provider_variant": provider_variant,
                "variables": variables if isinstance(variables, dict) else None,
            }
        ),
    )
    db.session.add(row)
    db.session.commit()
    return _serialize_tts_request(row), None, row.id, actor_user.id


def _process_tts_request_internal(tts_request_id, actor_user_id):
    row = TTSRequest.query.get(tts_request_id)
    if row is None:
        return None, "TTS request not found"
    business = Business.query.get(row.business_id)
    if business is None:
        row.status = "failed"
        row.error_message = "Business not found"
        db.session.commit()
        return None, "Business not found"

    row.status = "processing"
    db.session.commit()

    started = datetime.utcnow()

    metadata = {}
    try:
        metadata = json.loads(row.metadata_json) if row.metadata_json else {}
    except Exception:  # noqa: BLE001
        metadata = {}
    provider_variant = str((metadata or {}).get("provider_variant") or "").strip().lower()

    try:
        asset, duration = _generate_provider_audio_and_asset(
            type("ActorRef", (), {"id": actor_user_id})(),
            business,
            row.text,
            row.language,
            row.voice or "female_en_1",
            row.provider,
            provider_options={"variant": provider_variant} if provider_variant else {},
        )

        row.audio_asset_id = asset.id
        row.duration = duration
        row.generation_time_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
        row.status = "completed"
        row.error_message = None
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        row = TTSRequest.query.get(row.id)
        if row is not None:
            row.status = "failed"
            row.error_message = str(exc)
            row.generation_time_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
            db.session.commit()
        return None, f"TTS generation failed: {exc}"

    log_audit_event(
        "tts.generated",
        business_id=business.id,
        actor_user_id=actor_user_id,
        metadata={"tts_request_id": row.id, "audio_asset_id": row.audio_asset_id},
    )
    db.session.commit()
    return _serialize_tts_request(row), None


def generate_tts(actor_user, payload):
    result, error, tts_request_id, actor_user_id = _prepare_tts_request(actor_user, payload)
    if error or tts_request_id is None:
        return result, error
    return _process_tts_request_internal(tts_request_id, actor_user_id)


def enqueue_tts(actor_user, payload):
    result, error, tts_request_id, actor_user_id = _prepare_tts_request(actor_user, payload)
    if error:
        return None, error
    if tts_request_id is None:
        # cache-hit path already completed and returned result
        return result, None
    return {
        "id": result["id"],
        "uuid": result["uuid"],
        "status": "queued",
        "tts_request_id": tts_request_id,
        "actor_user_id": actor_user_id,
    }, None


def process_tts_request_by_id(tts_request_id, actor_user_id):
    return _process_tts_request_internal(tts_request_id, actor_user_id)


def generate_tts_for_runtime_business(business, payload, variables=None, created_by=None):
    if business is None:
        return None, "Business not found"

    payload = payload or {}
    node = payload.get("node") if isinstance(payload.get("node"), dict) else {}
    node_config = payload.get("node_config") if isinstance(payload.get("node_config"), dict) else {}

    raw_text = (
        payload.get("text")
        or node_config.get("text")
        or node.get("text")
        or ""
    )
    text = _render_tts_text_template(str(raw_text), variables).strip()
    if not text:
        return None, "Missing required field: text"

    language = str(
        payload.get("language")
        or node_config.get("language")
        or node.get("language")
        or "en"
    ).strip().lower()
    voice = str(
        payload.get("voice")
        or node_config.get("voice")
        or node.get("voice")
        or ""
    ).strip()
    provider = str(
        payload.get("provider")
        or node_config.get("provider")
        or node.get("provider")
        or current_app.config.get("TTS_DEFAULT_PROVIDER", "mock")
    ).strip().lower()
    if not voice:
        if provider == "google":
            voice = "gemini-tts:Kore"
        elif provider == "openai":
            voice = "alloy"
        elif provider == "elevenlabs":
            voice = str(current_app.config.get("ELEVENLABS_TTS_VOICE_ID", "")).strip() or "JBFqnCBsd6RMkjVDRZzb"
        else:
            voice = "female_en_1"
    provider_variant = _resolve_provider_variant(payload) or _resolve_provider_variant(node_config) or _resolve_provider_variant(node)

    provider_adapter, err = get_provider(provider)
    if err:
        return None, err
    if language not in provider_adapter.get_supported_languages():
        return None, "Unsupported language"
    if provider != "google" and voice not in provider_adapter.get_supported_voices():
        return None, "Unsupported voice"

    text_hash = hashlib.sha256(
        _normalize_text_for_hash(text).encode("utf-8")
    ).hexdigest()
    cache_key = hashlib.sha256(
        f"{provider}|{provider_variant}|{language}|{voice}|{text_hash}".encode("utf-8")
    ).hexdigest()

    cached = (
        TTSRequest.query.filter_by(
            business_id=business.id,
            cache_key=cache_key,
            status="completed",
        )
        .order_by(TTSRequest.id.desc())
        .first()
    )
    if cached is not None and cached.audio_asset_id is not None:
        cached_asset = AudioAsset.query.get(cached.audio_asset_id)
        if _is_cache_asset_reusable(asset=cached_asset, business_id=business.id):
            return {
                "source": "cache_hit",
                "audio_asset_id": cached.audio_asset_id,
                "tts_request_id": cached.id,
                "language": cached.language,
                "voice": cached.voice,
                "provider": cached.provider,
            }, None

    started = datetime.utcnow()
    row = TTSRequest(
        uuid=str(uuid.uuid4()),
        business_id=business.id,
        text=text,
        language=language,
        voice=voice,
        provider=provider,
        status="processing",
        cache_key=cache_key,
        created_by=created_by,
        metadata_json=json.dumps(
            {
                "mode": "runtime-flow-node",
                "provider_variant": provider_variant,
            }
        ),
    )
    db.session.add(row)
    db.session.commit()

    try:
        actor_ref = type("ActorRef", (), {"id": created_by})()
        asset, duration = _generate_provider_audio_and_asset(
            actor_ref,
            business,
            text,
            language,
            voice,
            provider,
            provider_options={"variant": provider_variant} if provider_variant else {},
        )
        row.audio_asset_id = asset.id
        row.duration = duration
        row.generation_time_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
        row.status = "completed"
        row.error_message = None
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        row = TTSRequest.query.get(row.id)
        if row is not None:
            row.status = "failed"
            row.error_message = str(exc)
            row.generation_time_ms = int((datetime.utcnow() - started).total_seconds() * 1000)
            db.session.commit()
        return None, f"TTS generation failed: {exc}"

    return {
        "source": "generated",
        "audio_asset_id": row.audio_asset_id,
        "tts_request_id": row.id,
        "language": row.language,
        "voice": row.voice,
        "provider": row.provider,
        "provider_variant": provider_variant,
    }, None



def list_tts_requests(actor_user, business_id=None):
    query = TTSRequest.query
    if business_id is not None:
        business, error = _resolve_business(actor_user, business_id, manage=False)
        if error:
            return None, error
        query = query.filter(TTSRequest.business_id == business.id)
    elif actor_user.role != "superuser":
        owned_ids = [b.id for b in Business.query.filter_by(owner_user_id=actor_user.id).all()]
        member_ids = [
            m.business_id
            for m in WorkspaceMembership.query.filter_by(user_id=actor_user.id, status="active").all()
        ]
        allowed_ids = sorted(set(owned_ids + member_ids))
        if not allowed_ids:
            return [], None
        query = query.filter(TTSRequest.business_id.in_(allowed_ids))

    items = query.order_by(TTSRequest.created_at.desc()).all()
    return [_serialize_tts_request(item) for item in items], None


def get_tts_request(actor_user, request_id):
    row = TTSRequest.query.get(request_id)
    if row is None:
        return None, "TTS request not found"
    business = Business.query.get(row.business_id)
    if business is None:
        return None, "Business not found"
    if not _can_view_business(actor_user, business):
        return None, "Insufficient permission for this business"
    return _serialize_tts_request(row), None


def delete_tts_request(actor_user, request_id):
    row = TTSRequest.query.get(request_id)
    if row is None:
        return None, "TTS request not found"
    business = Business.query.get(row.business_id)
    if business is None:
        return None, "Business not found"
    if not _can_manage_business(actor_user, business):
        return None, "Insufficient permission for this business"

    if row.status not in {"completed", "failed"}:
        row.status = "failed"
    row.error_message = "deleted_by_user"
    db.session.commit()
    log_audit_event(
        "tts.deleted",
        business_id=business.id,
        actor_user_id=actor_user.id,
        metadata={"tts_request_id": row.id},
    )
    db.session.commit()
    return {"message": "TTS request deleted", "id": row.id}, None


def get_supported_voices(provider=None):
    if provider:
        normalized = provider.strip().lower()
        provider_adapter, err = get_provider(normalized)
        if err:
            return None, err
        return {"provider": normalized, "voices": provider_adapter.get_supported_voices()}, None

    providers = sorted(enabled_providers())
    voices = {}
    for p in providers:
        provider_adapter, err = get_provider(p)
        if err:
            voices[p] = []
            continue
        voices[p] = provider_adapter.get_supported_voices()
    return {"providers": providers, "voices": voices}, None


def get_supported_languages(provider=None):
    if provider:
        normalized = provider.strip().lower()
        provider_adapter, err = get_provider(normalized)
        if err:
            return None, err
        return {"provider": normalized, "languages": sorted(provider_adapter.get_supported_languages())}, None

    providers = sorted(enabled_providers())
    language_set = set()
    for p in providers:
        provider_adapter, err = get_provider(p)
        if err:
            continue
        language_set.update(provider_adapter.get_supported_languages())
    return {"providers": providers, "languages": sorted(language_set)}, None
