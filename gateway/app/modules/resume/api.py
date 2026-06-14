from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request

from app.modules.auth.api import require_auth_user
from app.modules.auth.schema import AuthUser
from app.modules.resume.schema import (
    ApiResponse,
    CompleteUploadRequest,
    ResumeData,
    ResumeDetailResponseData,
    ResumeListResponseData,
    UploadUrlRequest,
    UploadUrlResponseData,
)
from app.modules.resume.service import ResumeService

# 所有简历接口都强制登录：写接口要花平台的 LLM/存储成本，必须按用户隔离。
router = APIRouter(
    prefix="/resumes",
    tags=["resumes"],
    dependencies=[Depends(require_auth_user)],
)


def get_resume_service(request: Request) -> ResumeService:
    service = getattr(request.app.state, "resume_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="Resume service is not initialized")
    return cast(ResumeService, service)


@router.post("/upload-url", response_model=ApiResponse[UploadUrlResponseData])
def generate_upload_url(
    payload: UploadUrlRequest,
    user: AuthUser = Depends(require_auth_user),
    service: ResumeService = Depends(get_resume_service),
):
    object_key = service.generate_object_key(user_id=user.user_id, filename=payload.filename)
    try:
        upload_url = service.generate_upload_url(
            object_key=object_key, content_type=payload.content_type
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ApiResponse(
        data=UploadUrlResponseData(
            object_key=object_key,
            upload_url=upload_url,
            asset_url=service.build_asset_url(object_key),
        )
    )


@router.post("/complete-upload", response_model=ApiResponse[ResumeDetailResponseData])
def complete_upload(
    payload: CompleteUploadRequest,
    user: AuthUser = Depends(require_auth_user),
    service: ResumeService = Depends(get_resume_service),
):
    try:
        resume = service.complete_upload(
            user_id=user.user_id,
            object_key=payload.object_key,
            filename=payload.filename,
            content_type=payload.content_type,
            file_size=payload.file_size,
            etag=payload.etag,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ApiResponse(data=ResumeDetailResponseData(resume=resume))


@router.get("", response_model=ApiResponse[ResumeListResponseData])
def list_resumes(
    user: AuthUser = Depends(require_auth_user),
    service: ResumeService = Depends(get_resume_service),
):
    try:
        items = service.list_resumes(user_id=user.user_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ApiResponse(data=ResumeListResponseData(items=items))


@router.post("/{resume_id}/activate", response_model=ApiResponse[ResumeDetailResponseData])
def activate_resume(
    resume_id: str,
    user: AuthUser = Depends(require_auth_user),
    service: ResumeService = Depends(get_resume_service),
):
    try:
        resume = service.activate(user_id=user.user_id, resume_id=resume_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ApiResponse(data=ResumeDetailResponseData(resume=resume))


@router.delete("/{resume_id}", response_model=ApiResponse[ResumeData | None])
def delete_resume(
    resume_id: str,
    user: AuthUser = Depends(require_auth_user),
    service: ResumeService = Depends(get_resume_service),
):
    try:
        service.delete(user_id=user.user_id, resume_id=resume_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ApiResponse(data=None)
