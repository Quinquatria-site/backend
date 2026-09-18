"""요청 언어로 평탄화한 일반·상시 공지 조회."""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import Select, and_, select

from common.errors import ApiError, ErrorCode, ErrorResponse
from common.pagination import Page
from common.query import LanguageQuery, ListQuery
from common.types import ResourceId
from customer.api.dependencies import ReadSession
from customer.api.queries import is_storable_id, paginate
from customer.api.schemas.notices import NoticeResponse
from quinquatria_persistence import Notice, NoticeTranslation, NoticeType

router = APIRouter(
    prefix="/notices",
    tags=["notices"],
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)


def _select_notices() -> Select:
    return select(
        Notice.id,
        Notice.type,
        Notice.created_at,
        NoticeTranslation.language_code,
        NoticeTranslation.title,
        NoticeTranslation.content,
    )


def _translated_notices(notice_type: NoticeType, query: LanguageQuery) -> Select:
    return (
        _select_notices()
        .join(NoticeTranslation, NoticeTranslation.notice_id == Notice.id)
        .where(
            Notice.type == notice_type,
            NoticeTranslation.language_code == query.language_code.value,
        )
        .order_by(Notice.created_at.desc(), Notice.id.desc())
    )


@router.get("")
async def list_general_notices(
    query: Annotated[ListQuery, Query()], session: ReadSession
) -> Page[NoticeResponse]:
    statement = _translated_notices(NoticeType.GENERAL, query)
    return await paginate(session, statement, query, NoticeResponse)


@router.get("/permanent")
async def list_permanent_notices(
    query: Annotated[ListQuery, Query()], session: ReadSession
) -> Page[NoticeResponse]:
    statement = _translated_notices(NoticeType.PERMANENT, query)
    return await paginate(session, statement, query, NoticeResponse)


@router.get(
    "/latest",
    response_model=NoticeResponse,
    responses={
        204: {"description": "일반 공지가 없습니다."},
        404: {"model": ErrorResponse},
    },
)
async def get_latest_general_notice(
    query: Annotated[LanguageQuery, Query()], session: ReadSession
) -> NoticeResponse | Response:
    result = await session.execute(
        _select_notices()
        .outerjoin(
            NoticeTranslation,
            and_(
                NoticeTranslation.notice_id == Notice.id,
                NoticeTranslation.language_code == query.language_code.value,
            ),
        )
        .where(Notice.type == NoticeType.GENERAL)
        .order_by(Notice.created_at.desc(), Notice.id.desc())
        .limit(1)
    )
    notice = result.mappings().one_or_none()
    if notice is None:
        return Response(status_code=HTTPStatus.NO_CONTENT)
    if notice["language_code"] is None:
        raise ApiError(ErrorCode.TRANSLATION_NOT_FOUND)
    return NoticeResponse.model_validate(notice)


@router.get("/{notice_id}", responses={404: {"model": ErrorResponse}})
async def get_notice(
    notice_id: ResourceId,
    query: Annotated[LanguageQuery, Query()],
    session: ReadSession,
) -> NoticeResponse:
    if not is_storable_id(notice_id):
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)

    result = await session.execute(
        _select_notices()
        .outerjoin(
            NoticeTranslation,
            and_(
                NoticeTranslation.notice_id == Notice.id,
                NoticeTranslation.language_code == query.language_code.value,
            ),
        )
        .where(Notice.id == notice_id)
    )
    notice = result.mappings().one_or_none()
    if notice is None:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    if notice["language_code"] is None:
        raise ApiError(ErrorCode.TRANSLATION_NOT_FOUND)
    return NoticeResponse.model_validate(notice)
