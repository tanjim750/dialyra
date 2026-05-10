from . import (
    condition,
    gather_input,
    goto,
    hangup,
    noop,
    play_audio,
    record_control,
    say_text,
    set_variable,
    transfer_call,
    wait,
    webhook,
)

EXECUTORS = {
    "play_audio": play_audio.execute,
    "say_text": say_text.execute,
    "tts": say_text.execute,
    "gather_input": gather_input.execute,
    "condition": condition.execute,
    "set_variable": set_variable.execute,
    "goto": goto.execute,
    "webhook": webhook.execute,
    "transfer_call": transfer_call.execute,
    "wait": wait.execute,
    "record_control": record_control.execute,
    "hangup": hangup.execute,
}


def execute_node(actor_business, node_payload, variables):
    node_type = str(node_payload.get("node_type") or "").strip().lower()
    fn = EXECUTORS.get(node_type, noop.execute)
    return fn(actor_business, node_payload, variables)
