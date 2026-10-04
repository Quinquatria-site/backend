"""요청 언어로 평탄화한 일반·상시 공지 조회."""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import Select, and_, func, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from common.errors import ApiError, ErrorCode, ErrorResponse
from common.pagination import Page
from common.query import LanguageQuery, ListQuery
from common.types import ResourceId
from customer.api.dependencies import ReadSession
from customer.api.queries import is_storable_id, paginate
from customer.api.schemas.notices import NoticeResponse
from quinquatria_persistence import (
    Image,
    LanguageCode,
    Notice,
    NoticeImage,
    NoticeTranslation,
    NoticeType,
)

router = APIRouter(
    prefix="/notices",
    tags=["notices"],
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)


def _select_notices(language_code: str) -> Select:
    """요청 언어 이미지를 쓰고, 그 언어에 이미지가 없으면 KO 이미지로 대체한다.

    이미지는 언어별이다(명세 §3.5). 아직 다른 언어 이미지를 만들지 못한 공지도
    빈 화면이 되지 않게 KO로 대체한다. 어느 쪽도 없으면 집계 행이 없어 NULL이다.
    """
    images = (
        select(
            NoticeImage.notice_id,
            NoticeImage.language_code,
            func.array_agg(aggregate_order_by(Image.s3_key, NoticeImage.seq)).label(
                "image_keys"
            ),
        )
        .join(Image, Image.id == NoticeImage.image_id)
        .group_by(NoticeImage.notice_id, NoticeImage.language_code)
        .subquery("notice_images")
    )
    requested = images.alias("requested_images")
    fallback = images.alias("ko_images")
    return select(
        Notice.id,
        Notice.type,
        Notice.created_at,
        func.coalesce(requested.c.image_keys, fallback.c.image_keys).label(
            "notice_image_uri"
        ),
        NoticeTranslation.language_code,
        NoticeTranslation.title,
        NoticeTranslation.content,
    ).select_from(
        Notice.__table__.outerjoin(
            requested,
            and_(
                requested.c.notice_id == Notice.id,
                requested.c.language_code == language_code,
            ),
        ).outerjoin(
            fallback,
            and_(
                fallback.c.notice_id == Notice.id,
                fallback.c.language_code == LanguageCode.KO.value,
            ),
        )
    )


def _translated_notices(notice_type: NoticeType, query: LanguageQuery) -> Select:
    return (
        _select_notices(query.language_code.value)
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
        _select_notices(query.language_code.value)
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
        _select_notices(query.language_code.value)
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
