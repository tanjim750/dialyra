import json
import logging
import uuid

from flask import current_app

LOGGER = logging.getLogger(__name__)

_REDIS_CLIENT = None
_REDIS_DISABLED = False


def _redis_available():
    global _REDIS_CLIENT, _REDIS_DISABLED
    if _REDIS_DISABLED:
        return False
    if _REDIS_CLIENT is not None:
        return True
    redis_url = str(current_app.config.get("REDIS_URL", "") or "").strip()
    if not redis_url:
        _REDIS_DISABLED = True
        return False
    try:
        import redis  # lazy import

        _REDIS_CLIENT = redis.Redis.from_url(redis_url, decode_responses=True)
        _REDIS_CLIENT.ping()
        return True
    except Exception as exc:  # noqa: BLE001
        _REDIS_DISABLED = True
        LOGGER.warning("Post-call intent store Redis unavailable: %s", exc)
        return False


def _intents_key(call_action_id):
    return f"postcall:intents:{str(call_action_id).strip()}"


def _lock_key(call_action_id):
    return f"postcall:flushlock:{str(call_action_id).strip()}"


def append_intent(call_action_id, intent_payload):
    if not str(call_action_id or "").strip() or not isinstance(intent_payload, dict):
        return False
    if not _redis_available():
        return False
    ttl_sec = int(current_app.config.get("POSTCALL_INTENT_TTL_SEC", 86400) or 86400)
    key = _intents_key(call_action_id)
    try:
        raw = json.dumps(intent_payload, ensure_ascii=False)
        _REDIS_CLIENT.rpush(key, raw)
        _REDIS_CLIENT.expire(key, max(60, ttl_sec))
        return True
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Post-call intent append failed for %s: %s", call_action_id, exc)
        return False


def list_intents(call_action_id):
    if not str(call_action_id or "").strip():
        return []
    if not _redis_available():
        return []
    key = _intents_key(call_action_id)
    try:
        rows = _REDIS_CLIENT.lrange(key, 0, -1) or []
        out = []
        for raw in rows:
            try:
                item = json.loads(raw)
                if isinstance(item, dict):
                    out.append(item)
            except Exception:  # noqa: BLE001
                continue
        return out
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Post-call intent list failed for %s: %s", call_action_id, exc)
        return []


def clear_intents(call_action_id):
    if not str(call_action_id or "").strip():
        return False
    if not _redis_available():
        return False
    key = _intents_key(call_action_id)
    try:
        _REDIS_CLIENT.delete(key)
        return True
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Post-call intent clear failed for %s: %s", call_action_id, exc)
        return False


def acquire_flush_lock(call_action_id):
    if not str(call_action_id or "").strip():
        return None
    if not _redis_available():
        return None
    ttl_sec = int(current_app.config.get("POSTCALL_FLUSH_LOCK_TTL_SEC", 60) or 60)
    key = _lock_key(call_action_id)
    owner = str(uuid.uuid4())
    try:
        ok = _REDIS_CLIENT.set(key, owner, nx=True, ex=max(5, ttl_sec))
        return owner if ok else None
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Post-call flush lock acquire failed for %s: %s", call_action_id, exc)
        return None


def release_flush_lock(call_action_id, owner):
    if not str(call_action_id or "").strip() or not str(owner or "").strip():
        return False
    if not _redis_available():
        return False
    key = _lock_key(call_action_id)
    try:
        current = _REDIS_CLIENT.get(key)
        if current == owner:
            _REDIS_CLIENT.delete(key)
            return True
        return False
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Post-call flush lock release failed for %s: %s", call_action_id, exc)
        return False

