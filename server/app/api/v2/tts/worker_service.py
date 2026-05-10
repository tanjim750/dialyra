import os
import queue
import threading

from app.api.v2.tts.service import process_tts_request_by_id

_queue = queue.Queue()
_worker_thread = None
_worker_lock = threading.Lock()


def enqueue_tts_job(tts_request_id, actor_user_id):
    _queue.put((int(tts_request_id), int(actor_user_id)))


def _worker_loop(app):
    with app.app_context():
        while True:
            tts_request_id, actor_user_id = _queue.get()
            try:
                process_tts_request_by_id(tts_request_id, actor_user_id)
            finally:
                _queue.task_done()


def start_tts_worker(app):
    global _worker_thread
    if not bool(app.config.get("TTS_ASYNC_ENABLED", False)):
        return

    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return
        _worker_thread = threading.Thread(
            target=_worker_loop,
            args=(app,),
            name="tts-worker",
            daemon=True,
        )
        _worker_thread.start()


def get_tts_worker_health():
    return {
        "worker_alive": bool(_worker_thread and _worker_thread.is_alive()),
        "queued_jobs": _queue.qsize(),
    }
