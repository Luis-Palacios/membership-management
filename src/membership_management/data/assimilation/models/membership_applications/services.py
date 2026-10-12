from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from membership_management.data.query_helpers import all_as, first_as

from .queries import (
    get_detailed_membership_application_query,
    get_recently_generated_membership_applications_count_query,
    get_recently_generated_membership_applications_query,
    most_recent_membership_application_query,
)
from .results import (
    MembershipApplicationDetails,
    MembershipApplicationSummary,
    MostRecentMembershipApplication,
    RecentMembershipApplications,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session


DEFAULT_RECENT_WINDOW = timedelta(days=60)


def get_most_recent_membership_application(session: Session) -> MostRecentMembershipApplication | None:
    """
    Get the most recently generated membership application, if any exist.
    """
    return first_as(session, most_recent_membership_application_query, cls=MostRecentMembershipApplication)


def get_recent_membership_applications_count(
    session: Session, window: timedelta = DEFAULT_RECENT_WINDOW
) -> int:
    """
    Get the count of membership applications generated within `window` of the most recently
    generated application (falls back to now if there are none yet).
    """
    end_date, start_date = get_recent_membership_applications_date_range(session, window)

    result = session.execute(
        get_recently_generated_membership_applications_count_query(start_date=start_date, end_date=end_date)
    )
    return result.scalar_one()


def get_recent_membership_applications_date_range(
    session: Session, window: timedelta
) -> tuple[datetime, datetime]:
    end_date: datetime = datetime.now(tz=timezone.utc)
    most_recent: MostRecentMembershipApplication | None = get_most_recent_membership_application(session)
    if most_recent is not None:
        end_date = most_recent.generated_date
    start_date: datetime = end_date - window
    return end_date, start_date


def get_recent_membership_applications(
    session: Session, window: timedelta = DEFAULT_RECENT_WINDOW
) -> RecentMembershipApplications:
    """
    Get membership applications generated within `window` of the most recently
    generated application (falls back to now if there are none yet).
    """
    end_date, start_date = get_recent_membership_applications_date_range(session, window)

    applications: Sequence[MembershipApplicationSummary] = all_as(
        session,
        get_recently_generated_membership_applications_query(start_date=start_date, end_date=end_date),
        cls=MembershipApplicationSummary,
    )
    return RecentMembershipApplications(applications=applications, start_date=start_date, end_date=end_date)


def get_membership_application_detail_by_id(
    session: Session, application_id: int
) -> MembershipApplicationDetails | None:
    """
    Get a membership application by its ID, if it exists.
    """

    return first_as(
        session,
        get_detailed_membership_application_query(membership_application_id=application_id),
        cls=MembershipApplicationDetails,
    )
