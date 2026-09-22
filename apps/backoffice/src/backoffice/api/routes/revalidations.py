"""프론트 수신기의 접수 응답을 확인하는 수동 재검증 API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backoffice.revalidation.schemas import RevalidationRequest, RevalidationResponse
from backoffice.revalidation.sender import RevalidationFailed, RevalidationSender
from common.errors import ApiError, ErrorCode
from common.query import NoQuery

router = APIRouter()


def get_revalidation_sender(request: Request) -> RevalidationSender:
    return request.app.state.revalidation_sender


@router.post("/revalidations", status_code=202, response_model_exclude_none=True)
async def revalidate(
    body: RevalidationRequest,
    sender: Annotated[RevalidationSender, Depends(get_revalidation_sender)],
    query: Annotated[NoQuery, Query()],
) -> RevalidationResponse:
    try:
        await sender.send(body, source="manual")
    except RevalidationFailed:
        raise ApiError(ErrorCode.INTERNAL_SERVER_ERROR) from None
    return RevalidationResponse(**body.model_dump(exclude_none=True))
