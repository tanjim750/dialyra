from ami_service.ami_service import AMIService as LegacyAMIService


class AMIService(LegacyAMIService):
    """Compatibility wrapper so future code imports from app.services."""

    pass
