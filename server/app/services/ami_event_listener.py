import logging
import os
import socket
import threading
import time

from app.api.v2.calls.event_service import process_call_event
from app.extensions import db

LOGGER = logging.getLogger(__name__)
TARGET_EVENTS = {"OriginateResponse", "DialBegin", "DialEnd", "BridgeEnter", "Hangup"}

_listener_thread = None
_listener_lock = threading.Lock()
_pipeline_verbose = False


def _build_login_payload(username, secret):
    return (
        "Action: Login\r\n"
        f"Username: {username}\r\n"
        f"Secret: {secret}\r\n"
        "Events: on\r\n\r\n"
    )


def _parse_message(lines):
    payload = {}
    for line in lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        payload[key.strip()] = value.strip()
    return payload


def _iter_ami_messages(sock_file):
    buffer = []
    while True:
        line = sock_file.readline()
        if not line:
            return
        text = line.decode(errors="replace").strip("\r\n")
        if text == "":
            if buffer:
                yield _parse_message(buffer)
                buffer = []
            continue
        buffer.append(text)


def _process_event(payload):
    event_name = payload.get("Event")
    if event_name not in TARGET_EVENTS:
        return
    if _pipeline_verbose:
        LOGGER.info(
            "CALL-PIPELINE: AMI listener received | %s",
            {
                "event": event_name,
                "action_id": payload.get("ActionID"),
                "uniqueid": payload.get("Uniqueid") or payload.get("DestUniqueid"),
                "linkedid": payload.get("Linkedid"),
                "channel": payload.get("Channel"),
            },
        )
    result, error = process_call_event(payload, business_id=None)
    if error:
        LOGGER.debug("AMI event not applied (%s): %s", event_name, error)
        db.session.rollback()
    else:
        LOGGER.debug(
            "AMI event applied: event=%s call_log_id=%s status=%s",
            event_name,
            result.get("call_log_id"),
            result.get("status"),
        )


def _listener_loop(app):
    host = app.config.get("AMI_HOST")
    port = int(app.config.get("AMI_PORT"))
    username = app.config.get("AMI_USERNAME")
    secret = app.config.get("AMI_SECRET")
    timeout = float(app.config.get("AMI_TIMEOUT", 5))
    reconnect_delay = float(app.config.get("AMI_EVENT_RECONNECT_DELAY_SEC", 2))
    global _pipeline_verbose
    _pipeline_verbose = bool(app.config.get("CALL_PIPELINE_VERBOSE", False))

    with app.app_context():
        while True:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                sock.connect((host, port))
                sock.settimeout(None)
                sock.sendall(_build_login_payload(username, secret).encode())
                sock_file = sock.makefile("rb")
                LOGGER.info("AMI event listener connected to %s:%s", host, port)

                for message in _iter_ami_messages(sock_file):
                    if message.get("Response") == "Error":
                        LOGGER.warning("AMI listener received error response: %s", message)
                        continue
                    _process_event(message)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("AMI event listener disconnected: %s", exc)
                time.sleep(reconnect_delay)
            finally:
                try:
                    sock.close()
                except Exception:  # noqa: BLE001
                    pass


def start_ami_event_listener(app):
    global _listener_thread

    enabled = bool(app.config.get("AMI_EVENT_LISTENER_ENABLED", False))
    if not enabled:
        return

    # In debug reloader mode, parent process has WERKZEUG_RUN_MAIN=false.
    # Start listener only in reloader child or non-debug runtime.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    with _listener_lock:
        if _listener_thread and _listener_thread.is_alive():
            return
        _listener_thread = threading.Thread(
            target=_listener_loop,
            args=(app,),
            name="ami-event-listener",
            daemon=True,
        )
        _listener_thread.start()
        LOGGER.info("AMI event listener thread started")
