from http import HTTPStatus
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import RedirectResponse

from core.config import Settings, get_settings
from models.auth import (
    LoginHistoryItem,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    SocialLoginCallbackRequest,
    SocialLoginUrlResponse,
    TokenPair,
    UpdateMeRequest,
    UserPublic,
)
from services.auth import (
    AuthService,
    get_auth_service,
    get_current_user,
)

router = APIRouter()


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=HTTPStatus.CREATED,
    summary="Register user",
    description="Creates a new user and assigns default role.",
)
async def register(
    request: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
) -> UserPublic:
    user = await service.register_user(login=request.login, password=request.password)
    return UserPublic(**user)


@router.post(
    "/login",
    response_model=TokenPair,
    summary="User login",
    description="Authenticates user credentials and returns access/refresh token pair.",
)
async def login(
    request: LoginRequest,
    service: AuthService = Depends(get_auth_service),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
) -> TokenPair:
    tokens = await service.authenticate_user(
        login=request.login,
        password=request.password,
        user_agent=user_agent,
        ip=x_forwarded_for,
    )
    return TokenPair(**tokens)


@router.get(
    "/social/google/login-url",
    response_model=SocialLoginUrlResponse,
    summary="Get Google OAuth login URL",
    description="Returns a Google OAuth authorization URL and one-time state.",
)
async def social_google_login_url(service: AuthService = Depends(get_auth_service)) -> SocialLoginUrlResponse:
    payload = await service.get_google_login_url()
    return SocialLoginUrlResponse(**payload)


@router.post(
    "/social/google/callback",
    response_model=TokenPair,
    summary="Authenticate via Google OAuth code",
    description="Exchanges Google code for user identity and returns JWT token pair.",
)
async def social_google_callback(
    request: SocialLoginCallbackRequest,
    service: AuthService = Depends(get_auth_service),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
) -> TokenPair:
    tokens = await service.authenticate_google_user(
        code=request.code,
        state=request.state,
        user_agent=user_agent,
        ip=x_forwarded_for,
    )
    return TokenPair(**tokens)


@router.get(
    "/social/google/callback",
    include_in_schema=False,
)
async def social_google_callback_redirect(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
) -> RedirectResponse:
    redirect_base_url = settings.auth_google_post_login_redirect_url
    if error:
        return RedirectResponse(url=f"{redirect_base_url}?oauth_error={error}", status_code=HTTPStatus.TEMPORARY_REDIRECT)
    if not code or not state:
        return RedirectResponse(
            url=f"{redirect_base_url}?oauth_error=missing_code_or_state",
            status_code=HTTPStatus.TEMPORARY_REDIRECT,
        )
    try:
        tokens = await service.authenticate_google_user(
            code=code,
            state=state,
            user_agent=user_agent,
            ip=x_forwarded_for,
        )
    except Exception as exc:
        detail = getattr(exc, "detail", "oauth_callback_failed")
        return RedirectResponse(
            url=f"{redirect_base_url}?oauth_error={detail}",
            status_code=HTTPStatus.TEMPORARY_REDIRECT,
        )

    query = urlencode(
        {
            "oauth_status": "success",
            "token_type": tokens["token_type"],
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
        }
    )
    return RedirectResponse(url=f"{redirect_base_url}?{query}", status_code=HTTPStatus.TEMPORARY_REDIRECT)


@router.post(
    "/refresh",
    response_model=TokenPair,
    summary="Refresh token pair",
    description="Uses refresh token rotation to issue a new token pair.",
)
async def refresh(
    request: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
    user_agent: str | None = Header(default=None, alias="User-Agent"),
    x_forwarded_for: str | None = Header(default=None, alias="X-Forwarded-For"),
) -> TokenPair:
    tokens = await service.refresh(refresh_token=request.refresh_token, user_agent=user_agent, ip=x_forwarded_for)
    return TokenPair(**tokens)


@router.post(
    "/logout",
    status_code=HTTPStatus.NO_CONTENT,
    summary="Logout current session",
    description="Revokes current access and provided refresh token.",
)
async def logout(
    request: LogoutRequest,
    current_user: dict = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> None:
    await service.logout(access_payload=current_user["payload"], refresh_token=request.refresh_token)


@router.post(
    "/logout-all",
    status_code=HTTPStatus.NO_CONTENT,
    summary="Logout from all sessions",
    description="Invalidates all active sessions using token version bump.",
)
async def logout_all(
    current_user: dict = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> None:
    await service.logout_all(access_payload=current_user["payload"])


@router.get(
    "/me",
    response_model=UserPublic,
    summary="Current user profile",
)
async def me(current_user: dict = Depends(get_current_user)) -> UserPublic:
    return UserPublic(
        id=current_user["id"],
        login=current_user["login"],
        is_active=current_user["is_active"],
        is_superuser=current_user["is_superuser"],
        roles=current_user["roles"],
    )


@router.patch(
    "/me",
    response_model=UserPublic,
    summary="Update current user profile",
)
async def me_update(
    request: UpdateMeRequest,
    current_user: dict = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> UserPublic:
    updated = await service.update_me(user_id=current_user["id"], login=request.login, password=request.password)
    return UserPublic(**updated)


@router.get(
    "/me/login-history",
    response_model=list[LoginHistoryItem],
    summary="Get login history",
)
async def login_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> list[LoginHistoryItem]:
    rows = await service.get_login_history(user_id=current_user["id"], limit=limit, offset=offset)
    return [LoginHistoryItem(**row) for row in rows]
