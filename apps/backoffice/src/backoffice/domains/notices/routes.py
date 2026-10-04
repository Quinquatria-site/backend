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
    NoticeTranslationIn,
    NoticeTranslationOut,
)
from backoffice.images.store import ObjectStore
from backoffice.revalidation.events import RevalidationTag, mark_changed
from common.errors import ApiError, ErrorCode, ErrorResponse
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


_IMAGES = "notice_image_uri"


def _image_ids(notice: Notice, language_code: LanguageCode | None = None) -> list[int]:
    """언어 순서, 언어 안의 노출 순서대로 이미지 id를 낸다. 언어를 주면 그 언어만."""
    rows = sorted(
        notice.images, key=lambda row: (_LANGUAGE_ORDER[row.language_code], row.seq)
    )
    return [
        row.image_id
        for row in rows
        if language_code is None or row.language_code == language_code
    ]


def _serialize(notice: Notice, keys: dict[int, str]) -> NoticeOut:
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
                notice_image_uri=[
                    keys[image_id] for image_id in _image_ids(notice, row.language_code)
                ]
                or None,
            )
            for row in translations
        ],
    )


async def _respond(session: AsyncSession, notice: Notice) -> NoticeOut:
    return _serialize(notice, await image_keys(session, _image_ids(notice)))


def _ensure_distinct_keys(items: Sequence[NoticeTranslationIn]) -> None:
    """한 object key는 한 언어의 배열에만 둘 수 있다 (명세 §4.6, §5.7).

    같은 그림을 여러 언어에 쓰려면 언어마다 따로 업로드한다. 미리 막지 않으면
    두 번째 언어의 연결이 `IMAGE_ALREADY_ATTACHED`(409)로 끝나 원인이 흐려진다.
    """
    keys = [key for item in items for key in item.notice_image_uri or ()]
    if len(set(keys)) != len(keys):
        raise ApiError(ErrorCode.INVALID_IMAGE)


async def _set_images(
    session: AsyncSession,
    store: ObjectStore,
    notice: Notice,
    language_code: LanguageCode,
    object_keys: Sequence[str] | None,
    *,
    max_bytes: int,
) -> None:
    """한 언어의 `NoticeImage` 행을 새 배열 순서로 맞춘다. 다른 언어는 두지 않는다.

    남는 행은 `seq`만 바꿔 재사용한다. 장소 이미지와 같은 이유로, 지우고 다시
    넣으면 한 flush 안에서 `image_id` unique(지연 불가)에 걸릴 수 있다.
    """
    new_ids = await replace_images(
        session,
        store,
        current_image_ids=_image_ids(notice, language_code),
        object_keys=object_keys,
        resource_type=ImageResourceType.NOTICE_IMAGE,
        max_bytes=max_bytes,
    )
    rows = {
        row.image_id: row for row in notice.images if row.language_code == language_code
    }
    for row in list(notice.images):
        if row.language_code == language_code and row.image_id not in new_ids:
            notice.images.remove(row)
    for seq, image_id in enumerate(new_ids, start=1):
        row = rows.get(image_id)
        if row is None:
            notice.images.append(
                NoticeImage(language_code=language_code, image_id=image_id, seq=seq)
            )
        else:
            row.seq = seq


async def _detach_all(
    session: AsyncSession, store: ObjectStore, image_ids: Sequence[int], max_bytes: int
) -> None:
    await replace_images(
        session,
        store,
        current_image_ids=image_ids,
        object_keys=None,
        resource_type=ImageResourceType.NOTICE_IMAGE,
        max_bytes=max_bytes,
    )


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
        ids = [image_id for notice in notices for image_id in _image_ids(notice)]
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
    _ensure_distinct_keys(body.translations)
    notice = Notice(
        type=body.type,
        # 읽기만 한 빈 컬렉션은 저장되지 않아 flush 뒤 lazy="raise"에 걸린다.
        images=[],
        translations=[
            NoticeTranslation(**item.model_dump(exclude={_IMAGES}))
            for item in body.translations
        ],
    )
    session.add(notice)
    # 이미지 행이 FK로 가리킬 번역을 먼저 넣는다.
    await session.flush()
    for item in body.translations:
        await _set_images(
            session,
            store,
            notice,
            item.language_code,
            item.notice_image_uri,
            max_bytes=settings.max_image_bytes,
        )
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
    for name, value in body.changes().items():
        setattr(notice, name, value)
    if body.translations is not None:
        _ensure_distinct_keys(body.translations)
        upsert_translations(
            notice.translations,
            body.translations,
            NoticeTranslation,
            exclude=frozenset({_IMAGES}),
        )
        # 새 언어의 이미지 행이 FK로 가리킬 번역을 먼저 넣는다.
        await session.flush()
        for item in body.translations:
            # 생략은 유지, `null`은 해제다 (명세 §5.7).
            if _IMAGES in item.model_fields_set:
                await _set_images(
                    session,
                    store,
                    notice,
                    item.language_code,
                    item.notice_image_uri,
                    max_bytes=settings.max_image_bytes,
                )
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
    await _detach_all(session, store, _image_ids(notice), settings.max_image_bytes)
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
    store: ObjectStoreDep,
    settings: SettingsDep,
    query: Annotated[NoQuery, Query()],
) -> Response:
    """번역과 함께 그 언어의 이미지 연결도 지운다.

    연결 행은 FK cascade가 지우지만 이미지는 `ATTACHED`로 남아 cleanup이
    회수하지 못하므로, 번역 삭제가 성공한 뒤 같은 transaction에서 해제한다.
    """
    notice = await get_or_404(
        session, Notice, notice_id, selectinload(Notice.images), for_update=True
    )
    image_ids = _image_ids(notice, language_code)
    await delete_translation(
        session,
        owner=Notice,
        owner_id=notice_id,
        translation=NoticeTranslation,
        owner_fk=NoticeTranslation.notice_id,
        language_code=language_code,
    )
    await _detach_all(session, store, image_ids, settings.max_image_bytes)
    mark_changed(session, RevalidationTag.NOTICES)
    return Response(status_code=HTTPStatus.NO_CONTENT)
