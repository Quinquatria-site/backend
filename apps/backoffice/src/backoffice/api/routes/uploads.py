"""명세 §4.5의 이미지 업로드 URL 발급."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from backoffice.auth.dependencies import ObjectStoreDep, SessionDep, SettingsDep
from backoffice.images.service import (
    REQUIRED_HEADER_IF_NONE_MATCH,
    UPLOAD_METHOD,
    issue_upload_url,
)
from common.query import NoQuery
from quinquatria_persistence.enums import ImageResourceType

router = APIRouter()


class PresignedUrlRequest(BaseModel):
    """`content_type`만 문자열로 받는다.

    enum으로 선언하면 Pydantic이 422 VALIDATION_ERROR를 내는데, 명세 §4.5는
    허용하지 않는 MIME을 INVALID_IMAGE로 정했다. `resource_type`은 §2.3의
    일반 enum 규칙을 따르므로 enum 그대로 둔다.
    """

    model_config = ConfigDict(extra="forbid")

    resource_type: ImageResourceType
    content_type: str
    size: int


class PresignedUrlResponse(BaseModel):
    upload_url: str
    method: str
    object_key: str
    expires_in: int
    required_headers: dict[str, str]


@router.post("/uploads/images/presigned-url")
async def create_presigned_url(
    body: PresignedUrlRequest,
    settings: SettingsDep,
    session: SessionDep,
    store: ObjectStoreDep,
    query: Annotated[NoQuery, Query()],
) -> PresignedUrlResponse:
    ticket = await issue_upload_url(
        session,
        store,
        resource_type=body.resource_type,
        content_type=body.content_type,
        size=body.size,
        ttl_seconds=settings.presigned_url_ttl_seconds,
        max_bytes=settings.max_image_bytes,
    )
    return PresignedUrlResponse(
        upload_url=ticket.upload_url,
        method=UPLOAD_METHOD,
        object_key=ticket.object_key,
        expires_in=ticket.expires_in,
        required_headers={
            "Content-Type": ticket.content_type.value,
            "If-None-Match": REQUIRED_HEADER_IF_NONE_MATCH,
        },
    )
