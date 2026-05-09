from ami_service.ami_service import AMIService as LegacyAMIService


class AMIService(LegacyAMIService):
    """Compatibility wrapper so future code imports from app.services."""

    def ping(self):
        action = "Action: Ping\r\n\r\n"
        return self._send(action)

    def run_command(self, command):
        action = f"Action: Command\r\nCommand: {command}\r\n\r\n"
        return self._send(action)
