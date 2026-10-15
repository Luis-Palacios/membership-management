from datetime import date, datetime
from zoneinfo import ZoneInfo

from membership_management.api.config import api_settings


def church_today() -> date:
    """Today's date where the church is, not in UTC: the single source of "today" for the API."""
    return datetime.now(ZoneInfo(api_settings.church_timezone)).date()
