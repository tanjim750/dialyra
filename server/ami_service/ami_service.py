import os
import socket
import uuid


class AMIService:
    def __init__(self):
        self.host = os.getenv("AMI_HOST", "127.0.0.1")
        self.port = int(os.getenv("AMI_PORT", "5038"))
        self.username = os.getenv("AMI_USERNAME")
        self.secret = os.getenv("AMI_SECRET")
        self.timeout = float(os.getenv("AMI_TIMEOUT", "5"))
        self.fastagi_call_token_ttl_sec = int(os.getenv("FASTAGI_CALL_TOKEN_TTL_SEC", "900"))

    def _send(self, data: str):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((self.host, self.port))

            # LOGIN
            login = (
                "Action: Login\r\n"
                f"Username: {self.username}\r\n"
                f"Secret: {self.secret}\r\n"
                "Events: off\r\n\r\n"
            )
            sock.send(login.encode())

            self._recv_until_complete(sock)  # consume login response

            sock.send(data.encode())

            response = self._recv_until_complete(sock)
            return response
        finally:
            sock.close()

    def _recv_until_complete(self, sock):
        chunks = []
        saw_data = False
        while True:
            try:
                chunk = sock.recv(8192)
            except socket.timeout:
                # No more data arriving; return what we collected so far.
                break

            if not chunk:
                break

            saw_data = True
            text = chunk.decode(errors="replace")
            chunks.append(text)
            joined = "".join(chunks)

            # AMI command responses terminate with END marker.
            if "--END COMMAND--" in joined:
                break

            # CoreShowChannels AMI action terminator.
            if "Event: CoreShowChannelsComplete" in joined:
                break

            # Simple success/error responses (e.g. Originate accepted).
            if "Response:" in joined and "\r\n\r\n" in joined and "Event:" not in joined:
                break

        if not saw_data:
            return ""
        return "".join(chunks)

    def originate_call(self, phone_number, channel_variables=None, action_id=None):
        action_id = action_id or str(uuid.uuid4())

        print(
            f"Initiating call to {phone_number} via AMI at {self.host}:{self.port}..."
        )

        variable_lines = ""
        if channel_variables:
            for key, value in channel_variables.items():
                if value is None:
                    continue
                # Use inherited channel vars so values survive Local -> PJSIP leg.
                variable_lines += f"Variable: __{key}={value}\r\n"

        action = (
            f"Action: Originate\r\n"
            f"ActionID: {action_id}\r\n"
            f"Channel: Local/{phone_number}@outbound/n\r\n"
            f"Application: Wait\r\n"
            f"Data: 3600\r\n"
            f"CallerID: Dialyra <1000>\r\n"
            f"{variable_lines}"
            f"Async: true\r\n\r\n"
        )

        return self._send(action)

    def originate_application_playback(
        self,
        channel,
        playback_target,
        *,
        action_id=None,
        timeout_ms=10000,
    ):
        action_id = action_id or str(uuid.uuid4())
        action = (
            f"Action: Originate\r\n"
            f"ActionID: {action_id}\r\n"
            f"Channel: {channel}\r\n"
            f"Application: Playback\r\n"
            f"Data: {playback_target}\r\n"
            f"Timeout: {int(timeout_ms)}\r\n"
            f"Async: true\r\n\r\n"
        )
        return self._send(action)

    def hangup_channel(self, channel, action_id=None):
        action_id = action_id or str(uuid.uuid4())
        action = (
            "Action: Hangup\r\n"
            f"ActionID: {action_id}\r\n"
            f"Channel: {channel}\r\n\r\n"
        )
        return self._send(action)
