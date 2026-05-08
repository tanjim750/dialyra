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

            sock.recv(4096)  # consume login response

            sock.send(data.encode())

            response = sock.recv(8192).decode(errors="replace")
            return response
        finally:
            sock.close()

    def originate_call(self, phone_number):
        action_id = str(uuid.uuid4())

        print(
            f"Initiating call to {phone_number} via AMI at {self.host}:{self.port}..."
        )

        action = (
            f"Action: Originate\r\n"
            f"ActionID: {action_id}\r\n"
            f"Channel: Local/{phone_number}@outbound\r\n"
            f"Context: outbound\r\n"
            f"Exten: {phone_number}\r\n"
            f"Priority: 1\r\n"
            f"CallerID: Dialyra <1000>\r\n"
            f"Async: true\r\n\r\n"
        )

        return self._send(action)
