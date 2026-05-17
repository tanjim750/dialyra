import json
import logging

from app.extensions import db
from app.models import PostCallWebhookJob
from app.services.post_call_intent_store import (
    acquire_flush_lock,
    clear_intents,
    list_intents,
    release_flush_lock,
)
from app.services.post_call_webhook_worker import wake_post_call_webhook_worker

LOGGER = logging.getLogger(__name__)


def _s(value):
    text = str(value or "").strip()
    return text or None


def _json(value):
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _normalize_timeout(value):
    try:
        val = int(float(value))
    except (TypeError, ValueError):
        val = 5
    return max(1, min(30, val))


def flush_deferred_webhook_intents(call_log, call_session=None):
    """
    Flush deferred webhook intents from Redis to post_call_webhook_jobs.
    Returns stats dict.
    """
    action_id = _s(getattr(call_log, "action_id", None))
    if not action_id:
        return {
            "ok": False,
            "reason": "missing_action_id",
            "queued_count": 0,
            "duplicate_count": 0,
            "intent_count": 0,
            "redis_cleared": False,
        }

    lock_owner = acquire_flush_lock(action_id)
    if not lock_owner:
        return {
            "ok": False,
            "reason": "lock_not_acquired",
            "queued_count": 0,
            "duplicate_count": 0,
            "intent_count": 0,
            "redis_cleared": False,
        }

    try:
        intents = list_intents(action_id)
        if not intents:
            return {
                "ok": True,
                "reason": "no_intents",
                "queued_count": 0,
                "duplicate_count": 0,
                "intent_count": 0,
                "redis_cleared": False,
            }

        dedupe_keys = set()
        prepared = []
        for idx, intent in enumerate(intents, start=1):
            if not isinstance(intent, dict):
                continue
            node_key = _s(intent.get("node_key"))
            seq = intent.get("sequence_no")
            try:
                seq = int(seq)
            except (TypeError, ValueError):
                seq = idx
            idem = _s(intent.get("idempotency_hint")) or f"{action_id}:{node_key or 'webhook'}:{seq}"
            if idem in dedupe_keys:
                continue
            dedupe_keys.add(idem)
            prepared.append((intent, idem, seq))

        if not prepared:
            return {
                "ok": True,
                "reason": "no_valid_intents",
                "queued_count": 0,
                "duplicate_count": 0,
                "intent_count": len(intents),
                "redis_cleared": False,
            }

        existing = {
            row[0]
            for row in db.session.query(PostCallWebhookJob.idempotency_key)
            .filter(PostCallWebhookJob.idempotency_key.in_([x[1] for x in prepared]))
            .all()
        }

        queued_count = 0
        duplicate_count = 0
        default_session_id = _s(getattr(call_session, "id", None)) or "unknown"

        for intent, idem, seq in prepared:
            if idem in existing:
                duplicate_count += 1
                continue

            ctx = intent.get("context") if isinstance(intent.get("context"), dict) else {}
            node_id = intent.get("node_id")
            try:
                node_id = int(node_id) if node_id is not None else None
            except (TypeError, ValueError):
                node_id = None

            job = PostCallWebhookJob(
                business_id=int(getattr(call_log, "business_id")),
                call_action_id=action_id,
                call_session_id=_s(ctx.get("call_session_id")) or default_session_id,
                call_log_uuid=_s(getattr(call_log, "uuid", None)),
                node_id=node_id,
                node_key=_s(intent.get("node_key")),
                sequence_no=seq,
                method=str(intent.get("method") or "POST").strip().upper(),
                url=str(intent.get("url") or "").strip(),
                auth_json=_json(intent.get("auth")),
                headers_json=_json(intent.get("headers")),
                payload_json=_json(intent.get("payload")),
                timeout_seconds=_normalize_timeout(intent.get("timeout_seconds")),
                idempotency_key=idem,
                status="pending",
            )
            if not job.url:
                duplicate_count += 1
                continue
            db.session.add(job)
            queued_count += 1

        db.session.commit()
        if queued_count > 0:
            wake_post_call_webhook_worker()
        redis_cleared = clear_intents(action_id)
        return {
            "ok": True,
            "reason": "flushed",
            "queued_count": queued_count,
            "duplicate_count": duplicate_count,
            "intent_count": len(intents),
            "redis_cleared": bool(redis_cleared),
        }
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        LOGGER.exception("Post-call webhook intent flush failed for action_id=%s: %s", action_id, exc)
        return {
            "ok": False,
            "reason": "flush_exception",
            "error": str(exc),
            "queued_count": 0,
            "duplicate_count": 0,
            "intent_count": 0,
            "redis_cleared": False,
        }
    finally:
        release_flush_lock(action_id, lock_owner)
