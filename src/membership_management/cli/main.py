from __future__ import annotations

from membership_management.data.assimilation.database import SessionLocal
from membership_management.data.assimilation.models.membership_applications.services import (
    get_recent_membership_applications,
)


def get_current_membership_applications() -> None:
    """
    Get all current membership applications from the database.
    """

    with SessionLocal() as s:
        result = get_recent_membership_applications(s)
        print(
            "Found "
            f"{len(result.applications)} membership applications generated "
            f"between {result.start_date} and {result.end_date}."
        )
        print("Membership applications:")
        for membership_application in result.applications:
            print(membership_application)


if __name__ == "__main__":
    get_current_membership_applications()
