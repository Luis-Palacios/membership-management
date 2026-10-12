from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException

from membership_management.api.dependencies import SessionDep
from membership_management.api.jwt_auth import get_current_claims
from membership_management.api.rate_limit import default_user_rate_limit, rate_limit
from membership_management.api.schemas.applications import (
    ApplicationApproval,
    ApplicationRejection,
    ApplicationStatus,
    MembershipApplicationBase,
    MembershipApplicationDetailSchema,
)
from membership_management.data.assimilation.models.membership_applications.services import (
    get_membership_application_detail_by_id,
    get_recent_membership_applications,
)

if TYPE_CHECKING:
    from membership_management.data.assimilation.models.membership_applications.results import (
        MembershipApplicationDetails,
    )

router = APIRouter(
    prefix="/applications",
    tags=["applications"],
    dependencies=[Depends(get_current_claims), Depends(default_user_rate_limit)],
)


@router.get("/recents", name="get_recent_applications", description="Get recent membership applications")
def get_recent_applications(
    db: SessionDep, status: ApplicationStatus | None = None
) -> list[MembershipApplicationBase]:
    result = get_recent_membership_applications(db)
    # TODO: Implement status filter
    applications: list[MembershipApplicationBase] = [
        MembershipApplicationBase(
            application_id=membership_application.id,
            person_id=membership_application.person_id,
            person_full_name=membership_application.first_name + " " + membership_application.last_name,
            generated_date=membership_application.generated_date,
            fulfilment_date=membership_application.fulfilment_date,
            is_fulfilled=membership_application.fulfilment_date is not None,
        )
        for membership_application in result.applications
    ]
    return applications


@router.get(
    "/recents/count",
    name="get_recent_applications_count",
    description="Get the count of recent membership applications",
)
def get_recent_applications_count(db: SessionDep) -> int:
    from membership_management.data.assimilation.models.membership_applications.services import (
        get_recent_membership_applications_count,
    )

    return get_recent_membership_applications_count(db)


@router.post(
    "/approve",
    name="approve_application",
    description="Approve a membership application",
    dependencies=[Depends(rate_limit("10/minute", scope="approve"))],
)
async def approve_application(application: ApplicationApproval) -> dict[str, str]:
    return {
        "message": (
            f"Application {application.application_id} approved with comments: "
            f"{application.approval_comments}"
        )
    }


@router.post(
    "/reject",
    name="reject_application",
    description="Reject a membership application",
    dependencies=[Depends(rate_limit("10/minute", scope="reject"))],
)
async def reject_application(application: ApplicationRejection) -> dict[str, str]:
    return {
        "message": (
            f"Application {application.application_id} rejected for reason: {application.rejected_reason}"
        )
    }


@router.get("/{application_id}")
def get_application(application_id: int, db: SessionDep) -> MembershipApplicationDetailSchema:
    membership_application: MembershipApplicationDetails | None = get_membership_application_detail_by_id(
        db, application_id=application_id
    )

    if membership_application is None:
        raise HTTPException(status_code=404, detail=f"Application with ID {application_id} not found.")

    return MembershipApplicationDetailSchema(
        application_id=membership_application.id,
        person_id=membership_application.person_id,
        person_full_name=membership_application.first_name + " " + membership_application.last_name,
        generated_date=membership_application.generated_date,
        fulfilment_date=membership_application.fulfilment_date,
        is_fulfilled=membership_application.fulfilment_date is not None,
        first_name=membership_application.first_name,
        last_name=membership_application.last_name,
        life_before=membership_application.life_before,
        conversion=membership_application.conversion,
        life_after=membership_application.life_after,
    )
