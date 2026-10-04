"""공지 관리 라우트. `api/router.py`가 보호 라우터에 등록한다."""

from collections.abc import Sequence
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backoffice.auth.dependencies import ObjectStoreDep, SessionDep, SettingsDep
from backoffice.crud.images import image_keys, replace_images
from backoffice.crud.resources import get_or_404, paginate
from backoffice.crud.translations import delete_translation, upsert_translations
from backoffice.domains.notices.schemas import (
    NoticeCreate,
    NoticeListQuery,
    NoticeOut,
    NoticePatch,
    NoticeTranslationOut,
)
from backoffice.images.store import ObjectStore
from backoffice.revalidation.events import RevalidationTag, mark_changed
from common.errors import ErrorResponse
from common.pagination import Page
from common.query import NoQuery
from common.types import ResourceId
from quinquatria_persistence import (
    ImageResourceType,
    LanguageCode,
    Notice,
    NoticeImage,
    NoticeTranslation,
)

router = APIRouter(tags=["notices"], responses={422: {"model": ErrorResponse}})

_NOT_FOUND = {404: {"model": ErrorResponse}}

_LANGUAGE_ORDER = {code: index for index, code in enumerate(LanguageCode)}

_LOADED = (selectinload(Notice.translations), selectinload(Notice.images))


def _ordered_image_ids(notice: Notice) -> list[int]:
    return [row.image_id for row in sorted(notice.images, key=lambda row: row.seq)]


def _serialize(notice: Notice, keys: dict[int, str]) -> NoticeOut:
    """같은 세션에서 추가한 번역은 목록 끝에 붙으므로 응답 직전에 정렬한다."""
    translations = sorted(
        notice.translations,
        key=lambda row: (_LANGUAGE_ORDER[row.language_code], row.id),
    )
    image_ids = _ordered_image_ids(notice)
    return NoticeOut(
        id=notice.id,
        type=notice.type,
        created_at=notice.created_at,
        notice_image_uri=[keys[image_id] for image_id in image_ids] or None,
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


async def _respond(session: AsyncSession, notice: Notice) -> NoticeOut:
    return _serialize(notice, await image_keys(session, _ordered_image_ids(notice)))


async def _set_images(
    session: AsyncSession,
    store: ObjectStore,
    notice: Notice,
    object_keys: Sequence[str] | None,
    *,
    max_bytes: int,
) -> None:
    """`NoticeImage` 행을 새 배열 순서로 맞춘다.

    남는 행은 `seq`만 바꿔 재사용한다. 장소 이미지와 같은 이유로, 지우고 다시
    넣으면 한 flush 안에서 `image_id` unique(지연 불가)에 걸릴 수 있다.
    """
    new_ids = await replace_images(
        session,
        store,
        current_image_ids=_ordered_image_ids(notice),
        object_keys=object_keys,
        resource_type=ImageResourceType.NOTICE_IMAGE,
        max_bytes=max_bytes,
    )
    rows = {row.image_id: row for row in notice.images}
    for row in list(notice.images):
        if row.image_id not in new_ids:
            notice.images.remove(row)
    for seq, image_id in enumerate(new_ids, start=1):
        row = rows.get(image_id)
        if row is None:
            notice.images.append(NoticeImage(image_id=image_id, seq=seq))
        else:
            row.seq = seq


@router.get("/notices")
async def list_notices(
    query: Annotated[NoticeListQuery, Query()], session: SessionDep
) -> Page[NoticeOut]:
    statement = (
        select(Notice)
        .options(*_LOADED)
        .order_by(Notice.created_at.desc(), Notice.id.desc())
    )
    if query.type is not None:
        statement = statement.where(Notice.type == query.type)

    async def serialize(notices: Sequence[Notice]) -> list[NoticeOut]:
        ids = [
            image_id for notice in notices for image_id in _ordered_image_ids(notice)
        ]
        keys = await image_keys(session, ids)
        return [_serialize(notice, keys) for notice in notices]

    return await paginate(session, statement, query, serialize)


@router.post("/notices", status_code=HTTPStatus.CREATED)
async def create_notice(
    body: NoticeCreate,
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
    query: Annotated[NoQuery, Query()],
) -> NoticeOut:
    notice = Notice(
        type=body.type,
        # 읽기만 한 빈 컬렉션은 저장되지 않아 flush 뒤 lazy="raise"에 걸린다.
        images=[],
        translations=[
            NoticeTranslation(**item.model_dump()) for item in body.translations
        ],
    )
    await _set_images(
        session,
        store,
        notice,
        body.notice_image_uri,
        max_bytes=settings.max_image_bytes,
    )
    session.add(notice)
    await session.flush()
    await session.refresh(notice, ["created_at"])
    mark_changed(session, RevalidationTag.NOTICES)
    return await _respond(session, notice)


@router.get("/notices/{notice_id}", responses=_NOT_FOUND)
async def get_notice(
    notice_id: ResourceId, session: SessionDep, query: Annotated[NoQuery, Query()]
) -> NoticeOut:
    notice = await get_or_404(session, Notice, notice_id, *_LOADED)
    return await _respond(session, notice)


@router.patch("/notices/{notice_id}", responses=_NOT_FOUND)
async def update_notice(
    notice_id: ResourceId,
    body: NoticePatch,
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
    query: Annotated[NoQuery, Query()],
) -> NoticeOut:
    """행 잠금으로 같은 공지의 동시 PATCH가 같은 언어를 이중 insert하지 않게 한다."""
    notice = await get_or_404(session, Notice, notice_id, *_LOADED, for_update=True)
    changes = body.changes()
    if "notice_image_uri" in changes:
        del changes["notice_image_uri"]
        await _set_images(
            session,
            store,
            notice,
            body.notice_image_uri,
            max_bytes=settings.max_image_bytes,
        )
    for name, value in changes.items():
        setattr(notice, name, value)
    if body.translations is not None:
        upsert_translations(notice.translations, body.translations, NoticeTranslation)
    await session.flush()
    mark_changed(session, RevalidationTag.NOTICES)
    return await _respond(session, notice)


@router.delete(
    "/notices/{notice_id}",
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    responses=_NOT_FOUND,
)
async def delete_notice(
    notice_id: ResourceId,
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
    query: Annotated[NoQuery, Query()],
) -> Response:
    """번역은 FK `ON DELETE CASCADE`로, 이미지는 `DETACHED` 전이로 정리한다.

    PATCH와 같은 순서로 행을 먼저 잠가, 읽어 둔 이미지가 그사이 교체되지 않게 한다.
    """
    notice = await get_or_404(
        session, Notice, notice_id, selectinload(Notice.images), for_update=True
    )
    await _set_images(session, store, notice, None, max_bytes=settings.max_image_bytes)
    await session.delete(notice)
    await session.flush()
    mark_changed(session, RevalidationTag.NOTICES)
    return Response(status_code=HTTPStatus.NO_CONTENT)


@router.delete(
    "/notices/{notice_id}/translations/{language_code}",
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    responses={**_NOT_FOUND, 409: {"model": ErrorResponse}},
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
    mark_changed(session, RevalidationTag.NOTICES)
    return Response(status_code=HTTPStatus.NO_CONTENT)
