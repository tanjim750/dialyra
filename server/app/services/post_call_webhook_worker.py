import json
import os
import queue
import threading
import time
from datetime import datetime, timedelta

import requests

from app.extensions import db
from app.models import PostCallWebhookJob

_worker_thread = None
_worker_lock = threading.Lock()
_wake_queue = queue.Queue(maxsize=1)


def _retry_schedule_seconds(app):
    raw = str(app.config.get("POSTCALL_WEBHOOK_RETRY_SCHEDULE_SEC", "10,30,120") or "").strip()
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            val = int(part)
        except (TypeError, ValueError):
            continue
        if val > 0:
            out.append(val)
    return out or [10, 30, 120]


def _next_retry_at(app, attempt_count):
    schedule = _retry_schedule_seconds(app)
    idx = max(0, min(attempt_count - 1, len(schedule) - 1))
    return datetime.utcnow() + timedelta(seconds=schedule[idx])


def _build_auth(job):
    try:
        auth = json.loads(job.auth_json or "{}")
    except Exception:  # noqa: BLE001
        auth = {}
    if not isinstance(auth, dict):
        auth = {}
    auth_type = str(auth.get("type") or "none").strip().lower()
    if auth_type != "basic":
        return None
    username = str(auth.get("username") or "")
    password = str(auth.get("password") or "")
    return (username, password)


def _build_headers(job):
    try:
        headers = json.loads(job.headers_json or "{}")
    except Exception:  # noqa: BLE001
        headers = {}
    if not isinstance(headers, dict):
        headers = {}
    if "Idempotency-Key" not in headers:
        headers["Idempotency-Key"] = str(job.idempotency_key or "")
    return headers


def _build_payload(job):
    if not str(job.payload_json or "").strip():
        return None
    try:
        return json.loads(job.payload_json)
    except Exception:  # noqa: BLE001
        return job.payload_json


def _reserve_jobs(app):
    batch_size = int(app.config.get("POSTCALL_WEBHOOK_WORKER_BATCH_SIZE", 20) or 20)
    now = datetime.utcnow()
    rows = (
        PostCallWebhookJob.query.filter(
            PostCallWebhookJob.status.in_(["pending", "retry_scheduled"]),
        )
        .filter(
            db.or_(
                PostCallWebhookJob.next_retry_at.is_(None),
                PostCallWebhookJob.next_retry_at <= now,
            )
        )
        .order_by(PostCallWebhookJob.created_at.asc(), PostCallWebhookJob.id.asc())
        .limit(max(1, batch_size))
        .all()
    )
    if not rows:
        return []
    for row in rows:
        row.status = "processing"
        row.updated_at = datetime.utcnow()
    db.session.commit()
    return rows


def _complete_job_success(job, status_code, body):
    job.status = "completed"
    job.attempt_count = int(job.attempt_count or 0) + 1
    job.last_response_code = int(status_code)
    job.last_response_body = (body or "")[:2000]
    job.last_error = None
    now = datetime.utcnow()
    job.last_attempt_at = now
    job.completed_at = now
    job.next_retry_at = None


def _complete_job_failure(app, job, status_code=None, body=None, error=None):
    max_attempts = int(app.config.get("POSTCALL_WEBHOOK_MAX_ATTEMPTS", 4) or 4)
    next_attempt = int(job.attempt_count or 0) + 1
    job.attempt_count = next_attempt
    job.last_response_code = int(status_code) if status_code is not None else None
    job.last_response_body = (body or "")[:2000] if body is not None else None
    job.last_error = str(error or f"http_status_{status_code}")[:1000]
    job.last_attempt_at = datetime.utcnow()
    if next_attempt >= max(1, max_attempts):
        job.status = "failed"
        job.next_retry_at = None
    else:
        job.status = "retry_scheduled"
        job.next_retry_at = _next_retry_at(app, next_attempt)


def _process_job(app, job):
    timeout_sec = max(1, min(30, int(job.timeout_seconds or 5)))
    method = str(job.method or "POST").strip().upper()
    headers = _build_headers(job)
    auth = _build_auth(job)
    payload = _build_payload(job)
    try:
        if isinstance(payload, (dict, list)):
            resp = requests.request(
                method=method,
                url=job.url,
                headers=headers,
                auth=auth,
                json=payload,
                timeout=timeout_sec,
            )
        else:
            resp = requests.request(
                method=method,
                url=job.url,
                headers=headers,
                auth=auth,
                data=payload,
                timeout=timeout_sec,
            )
        ok = 200 <= int(resp.status_code) < 300
        if ok:
            _complete_job_success(job, resp.status_code, resp.text)
        else:
            _complete_job_failure(app, job, status_code=resp.status_code, body=resp.text)
    except requests.RequestException as exc:
        _complete_job_failure(app, job, error=f"{exc.__class__.__name__}: {exc}")


def _worker_loop(app):
    poll_sec = float(app.config.get("POSTCALL_WEBHOOK_WORKER_POLL_SEC", 1.5) or 1.5)
    with app.app_context():
        while True:
            try:
                jobs = _reserve_jobs(app)
                if not jobs:
                    try:
                        _wake_queue.get(timeout=max(0.2, poll_sec))
                        _wake_queue.task_done()
                    except queue.Empty:
                        pass
                    continue
                for job in jobs:
                    _process_job(app, job)
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()
                time.sleep(0.5)


def wake_post_call_webhook_worker():
    try:
        _wake_queue.put_nowait("wake")
    except queue.Full:
        return


def start_post_call_webhook_worker(app):
    global _worker_thread
    if not bool(app.config.get("POSTCALL_WEBHOOK_WORKER_ENABLED", True)):
        return
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return
        _worker_thread = threading.Thread(
            target=_worker_loop,
            args=(app,),
            name="postcall-webhook-worker",
            daemon=True,
        )
        _worker_thread.start()


def get_post_call_webhook_worker_health(app):
    return {
        "enabled": bool(app.config.get("POSTCALL_WEBHOOK_WORKER_ENABLED", True)),
        "worker_alive": bool(_worker_thread and _worker_thread.is_alive()),
        "wake_queue_depth": _wake_queue.qsize(),
        "poll_sec": float(app.config.get("POSTCALL_WEBHOOK_WORKER_POLL_SEC", 1.5) or 1.5),
        "batch_size": int(app.config.get("POSTCALL_WEBHOOK_WORKER_BATCH_SIZE", 20) or 20),
        "max_attempts": int(app.config.get("POSTCALL_WEBHOOK_MAX_ATTEMPTS", 4) or 4),
        "retry_schedule_sec": str(
            app.config.get("POSTCALL_WEBHOOK_RETRY_SCHEDULE_SEC", "10,30,120") or "10,30,120"
        ),
    }
