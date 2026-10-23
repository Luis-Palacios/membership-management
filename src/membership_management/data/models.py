"""Every model on MemberManagementBase.metadata, imported in one place.

Alembic autogenerate only sees models that have been imported: a domain missing here gets its
existing tables dropped in the next generated migration. Add each new domain's models package here.
"""

import membership_management.data.guests.models
import membership_management.data.members.models
import membership_management.data.small_groups.models  # noqa: F401
