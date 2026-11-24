from datetime import date, datetime
from zoneinfo import ZoneInfo

from membership_management.api.config import api_settings


def church_today() -> date:
    """Today's date where the church is, not in UTC: the single source of "today" for the API."""
    return datetime.now(ZoneInfo(api_settings.church_timezone)).date()


def church_now() -> datetime:
    """The wall-clock date and time where the church is, without a time zone: for comparing with a
    church date plus a time of day (a care log plan's `occurred_on` and `occurred_at_time`)."""
    return datetime.now(ZoneInfo(api_settings.church_timezone)).replace(tzinfo=None)


def church_date(moment: datetime) -> date:
    """The date `moment` falls on where the church is."""
    return moment.astimezone(ZoneInfo(api_settings.church_timezone)).date()
