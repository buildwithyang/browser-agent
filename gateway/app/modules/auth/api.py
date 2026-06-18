from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.responses import RedirectResponse

from app.modules.auth.schema import (
    ApiResponse,
    AuthMeData,
    AuthUser,
    ExtensionTokenIssued,
    ExtensionTokenListData,
)
from app.modules.auth.service import AuthService
from app.modules.auth.token_service import ExtensionTokenService

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(request: Request) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Auth service is not initialized")
    return cast(AuthService, service)


def require_auth_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthUser:
    user = auth_service.get_current_user(request.session)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def get_extension_token_service(request: Request) -> ExtensionTokenService:
    service = getattr(request.app.state, "extension_token_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Extension token service is not initialized")
    return cast(ExtensionTokenService, service)


@router.get("/login")
def login(request: Request, auth_service: AuthService = Depends(get_auth_service)):
    try:
        authorization_url = auth_service.build_authorization_url(request.session)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return RedirectResponse(authorization_url)


@router.get("/callback")
def callback(
    request: Request,
    code: str = Query(..., min_length=1),
    state: str = Query(..., min_length=1),
    auth_service: AuthService = Depends(get_auth_service),
):
    try:
        auth_service.complete_callback(session=request.session, code=code, state=state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    settings = request.app.state.settings
    # AUTH_FRONTEND_REDIRECT_URL 是认证完成后的最终落点，要使用浏览器实际访问前端的地址。
    return RedirectResponse(settings.auth_frontend_redirect_url)


@router.get("/me", response_model=ApiResponse[AuthMeData])
def me(request: Request, auth_service: AuthService = Depends(get_auth_service)):
    user = auth_service.get_current_user(request.session)
    return ApiResponse(data=AuthMeData(user=user))


@router.post("/logout", response_model=ApiResponse[AuthMeData])
def logout(request: Request, auth_service: AuthService = Depends(get_auth_service)):
    auth_service.logout(request.session)
    return ApiResponse(data=AuthMeData(user=None))


@router.post("/extension-token", response_model=ApiResponse[ExtensionTokenIssued])
def issue_extension_token(
    user: AuthUser = Depends(require_auth_user),
    service: ExtensionTokenService = Depends(get_extension_token_service),
):
    issued = service.issue(user_id=user.user_id, label="浏览器扩展")
    return ApiResponse(data=issued)


@router.get("/extension-tokens", response_model=ApiResponse[ExtensionTokenListData])
def list_extension_tokens(
    user: AuthUser = Depends(require_auth_user),
    service: ExtensionTokenService = Depends(get_extension_token_service),
):
    return ApiResponse(data=ExtensionTokenListData(items=service.list_for_user(user.user_id)))


@router.delete("/extension-tokens/{token_id}", response_model=ApiResponse[ExtensionTokenListData])
def revoke_extension_token(
    token_id: str,
    user: AuthUser = Depends(require_auth_user),
    service: ExtensionTokenService = Depends(get_extension_token_service),
):
    service.revoke(user_id=user.user_id, token_id=token_id)
    return ApiResponse(data=ExtensionTokenListData(items=service.list_for_user(user.user_id)))
