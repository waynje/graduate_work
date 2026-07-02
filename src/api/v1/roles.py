from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from models.role import RoleCreateRequest, RolePublic, RoleUpdateRequest
from services.auth import AuthService, get_auth_service, get_current_user, require_admin

router = APIRouter()


@router.get(
    "/",
    response_model=list[RolePublic],
    summary="List roles",
)
async def list_roles(
    _: dict = Depends(require_admin),
    service: AuthService = Depends(get_auth_service),
) -> list[RolePublic]:
    items = await service.list_roles()
    return [RolePublic(**item) for item in items]


@router.post(
    "/",
    response_model=RolePublic,
    status_code=HTTPStatus.CREATED,
    summary="Create role",
)
async def create_role(
    request: RoleCreateRequest,
    _: dict = Depends(require_admin),
    service: AuthService = Depends(get_auth_service),
) -> RolePublic:
    role = await service.create_role(name=request.name, description=request.description)
    return RolePublic(**role)


@router.patch(
    "/{role_id}",
    response_model=RolePublic,
    summary="Update role",
)
async def update_role(
    role_id: UUID,
    request: RoleUpdateRequest,
    _: dict = Depends(require_admin),
    service: AuthService = Depends(get_auth_service),
) -> RolePublic:
    role = await service.update_role(role_id=str(role_id), name=request.name, description=request.description)
    return RolePublic(**role)


@router.delete(
    "/{role_id}",
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete role",
)
async def delete_role(
    role_id: UUID,
    _: dict = Depends(require_admin),
    service: AuthService = Depends(get_auth_service),
) -> None:
    await service.delete_role(role_id=str(role_id))


@router.post(
    "/users/{user_id}",
    status_code=HTTPStatus.NO_CONTENT,
    summary="Grant role to user",
)
async def grant_role(
    user_id: UUID,
    role_id: UUID = Query(..., description="Role id"),
    _: dict = Depends(require_admin),
    service: AuthService = Depends(get_auth_service),
) -> None:
    await service.grant_role(user_id=str(user_id), role_id=str(role_id))


@router.delete(
    "/users/{user_id}",
    status_code=HTTPStatus.NO_CONTENT,
    summary="Revoke role from user",
)
async def revoke_role(
    user_id: UUID,
    role_id: UUID = Query(..., description="Role id"),
    _: dict = Depends(require_admin),
    service: AuthService = Depends(get_auth_service),
) -> None:
    await service.revoke_role(user_id=str(user_id), role_id=str(role_id))


@router.get(
    "/check/{role_name}",
    summary="Check current user role",
)
async def check_role(
    role_name: str,
    current_user: dict = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, bool]:
    has_role = await service.check_role(user_id=current_user["id"], required_role=role_name)
    return {"allowed": has_role}
