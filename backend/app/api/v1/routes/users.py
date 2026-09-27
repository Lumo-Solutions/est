from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_roles
from app.core.config import Settings, get_settings
from app.core.context import RequestContext
from app.core.enums import Role
from app.schemas.users import UserOut
from app.services import users as users_service

router = APIRouter(prefix="/users", tags=["users"])

# Read-only user directory, used to power an "add project member" picker
# and a general users-and-roles view. Same role list as reason-codes/
# vendor-regions (lead/proc/bd/md) -- broad enough to cover everyone who
# can actually add a project member (POST /projects/{id}/members is
# bd/md/lead) or benefits from seeing who holds which role, but not a
# plain estimator, who has no use for a user directory.
_READ_ROLES = (
    Role.LEAD_ESTIMATOR.value,
    Role.PROCUREMENT_HEAD.value,
    Role.BD_DIRECTOR.value,
    Role.MANAGING_DIRECTOR.value,
)


@router.get("", response_model=list[UserOut])
async def list_users_endpoint(
    ctx: RequestContext = Depends(require_roles(*_READ_ROLES)),
    settings: Settings = Depends(get_settings),
) -> list[UserOut]:
    rows = await users_service.list_tenant_users(ctx, settings)
    return [UserOut.model_validate(r) for r in rows]
