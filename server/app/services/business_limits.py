import json

from app.models import Business, User


def get_business_settings_dict(business):
    if not business or not business.settings_json:
        return {}
    try:
        parsed = json.loads(business.settings_json)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {}


def get_business_max_users(business):
    settings = get_business_settings_dict(business)
    max_users = settings.get("max_users")
    if max_users is None:
        return None
    try:
        parsed = int(max_users)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def can_add_user_to_business(business_id):
    business = Business.query.get(business_id)
    if business is None:
        return False, "Business not found"

    max_users = get_business_max_users(business)
    if max_users is None:
        return True, None

    active_users_count = User.query.filter_by(business_id=business_id, status="active").count()
    if active_users_count >= max_users:
        return False, "Business max_users limit reached"

    return True, None
