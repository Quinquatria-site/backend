"""공지 관리 라우트. `api/router.py`가 보호 라우터에 등록한다."""

from collections.abc import Sequence
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backoffice.auth.dependencies import SessionDep
from backoffice.crud.resources import get_or_404, paginate
from backoffice.crud.translations import delete_translation, upsert_translations
from backoffice.domains.notices.schemas import (
    NoticeCreate,
    NoticeListQuery,
    NoticeOut,
    NoticePatch,
    NoticeTranslationOut,
)
from common.pagination import Page
from common.query import NoQuery
from common.types import ResourceId
from quinquatria_persistence import LanguageCode, Notice, NoticeTranslation

router = APIRouter(tags=["notices"])

_LANGUAGE_ORDER = {code: index for index, code in enumerate(LanguageCode)}


def _serialize(notice: Notice) -> NoticeOut:
    """같은 세션에서 추가한 번역은 목록 끝에 붙으므로 응답 직전에 정렬한다."""
    translations = sorted(
        notice.translations,
        key=lambda row: (_LANGUAGE_ORDER[row.language_code], row.id),
    )
    return NoticeOut(
        id=notice.id,
        type=notice.type,
        created_at=notice.created_at,
        translations=[
            NoticeTranslationOut(
                id=row.id,
                notice_id=notice.id,
                language_code=row.language_code,
                title=row.title,
                content=row.content,
            )
            for row in translations
        ],
    )


async def _serialize_page(notices: Sequence[Notice]) -> list[NoticeOut]:
    return [_serialize(notice) for notice in notices]


@router.get("/notices")
async def list_notices(
    query: Annotated[NoticeListQuery, Query()], session: SessionDep
) -> Page[NoticeOut]:
    statement = (
        select(Notice)
        .options(selectinload(Notice.translations))
        .order_by(Notice.created_at.desc(), Notice.id.desc())
    )
    if query.type is not None:
        statement = statement.where(Notice.type == query.type)
    return await paginate(session, statement, query, _serialize_page)


@router.post("/notices", status_code=HTTPStatus.CREATED)
async def create_notice(
    body: NoticeCreate, session: SessionDep, query: Annotated[NoQuery, Query()]
) -> NoticeOut:
    notice = Notice(
        type=body.type,
        translations=[
            NoticeTranslation(**item.model_dump()) for item in body.translations
        ],
    )
    session.add(notice)
    await session.flush()
    await session.refresh(notice, ["created_at"])
    return _serialize(notice)


@router.get("/notices/{notice_id}")
async def get_notice(
    notice_id: ResourceId, session: SessionDep, query: Annotated[NoQuery, Query()]
) -> NoticeOut:
    notice = await get_or_404(
        session, Notice, notice_id, selectinload(Notice.translations)
    )
    return _serialize(notice)


@router.patch("/notices/{notice_id}")
async def update_notice(
    notice_id: ResourceId,
    body: NoticePatch,
    session: SessionDep,
    query: Annotated[NoQuery, Query()],
) -> NoticeOut:
    """행 잠금으로 같은 공지의 동시 PATCH가 같은 언어를 이중 insert하지 않게 한다."""
    notice = await get_or_404(
        session,
        Notice,
        notice_id,
        selectinload(Notice.translations),
        for_update=True,
    )
    for name, value in body.changes().items():
        setattr(notice, name, value)
    if body.translations is not None:
        upsert_translations(notice.translations, body.translations, NoticeTranslation)
    await session.flush()
    return _serialize(notice)


@router.delete(
    "/notices/{notice_id}",
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
)
async def delete_notice(
    notice_id: ResourceId, session: SessionDep, query: Annotated[NoQuery, Query()]
) -> Response:
    """번역은 FK의 `ON DELETE CASCADE`가 지운다."""
    notice = await get_or_404(session, Notice, notice_id)
    await session.delete(notice)
    await session.flush()
    return Response(status_code=HTTPStatus.NO_CONTENT)


@router.delete(
    "/notices/{notice_id}/translations/{language_code}",
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
)
async def delete_notice_translation(
    notice_id: ResourceId,
    language_code: LanguageCode,
    session: SessionDep,
    query: Annotated[NoQuery, Query()],
) -> Response:
    await delete_translation(
        session,
        owner=Notice,
        owner_id=notice_id,
        translation=NoticeTranslation,
        owner_fk=NoticeTranslation.notice_id,
        language_code=language_code,
    )
    return Response(status_code=HTTPStatus.NO_CONTENT)
