from app.services.ami_service import AMIService


ami_service = AMIService()


def originate_call(phone):
    return ami_service.originate_call(phone)
