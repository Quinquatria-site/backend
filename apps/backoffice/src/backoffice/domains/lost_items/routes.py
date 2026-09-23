"""분실물 관리 라우트. `api/router.py`가 보호 라우터에 등록한다."""

from collections.abc import Sequence
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backoffice.auth.dependencies import ObjectStoreDep, SessionDep, SettingsDep
from backoffice.crud.images import image_keys, replace_image
from backoffice.crud.resources import get_or_404, paginate
from backoffice.crud.translations import delete_translation, upsert_translations
from backoffice.domains.lost_items.schemas import (
    LostItemCreate,
    LostItemOut,
    LostItemPatch,
    LostItemQuery,
    LostItemTranslationOut,
)
from common.errors import ErrorResponse
from common.pagination import Page
from common.query import NoQuery
from common.types import ResourceId
from quinquatria_persistence.enums import ImageResourceType, LanguageCode
from quinquatria_persistence.models import LostItem, LostItemTranslation

router = APIRouter(
    prefix="/lost-items",
    tags=["lost-items"],
    responses={422: {"model": ErrorResponse}},
)

_IMAGE = ImageResourceType.LOST_ITEM_IMAGE
_WITH_TRANSLATIONS = selectinload(LostItem.translations)


async def _serialize(
    session: AsyncSession, items: Sequence[LostItem]
) -> list[LostItemOut]:
    """이미지 key는 페이지 단위로 한 번에 읽는다.

    같은 세션에서 upsert한 번역은 relationship 정렬이 다시 적용되지 않으므로
    명세 §5.2 순서(`language_code`, `id`)로 직접 정렬한다.
    """
    keys = await image_keys(session, (item.image_id for item in items))
    return [
        LostItemOut(
            id=item.id,
            image_url=None if item.image_id is None else keys[item.image_id],
            is_returned=item.is_returned,
            created_at=item.created_at,
            translations=[
                LostItemTranslationOut(
                    id=translation.id,
                    lost_item_id=item.id,
                    language_code=translation.language_code,
                    title=translation.title,
                    description=translation.description,
                    found_location=translation.found_location,
                )
                for translation in sorted(
                    item.translations,
                    key=lambda row: (row.language_code.value, row.id),
                )
            ],
        )
        for item in items
    ]


async def _one(session: AsyncSession, item: LostItem) -> LostItemOut:
    return (await _serialize(session, [item]))[0]


@router.get("")
async def list_lost_items(
    query: Annotated[LostItemQuery, Query()], session: SessionDep
) -> Page[LostItemOut]:
    statement = (
        select(LostItem)
        .options(_WITH_TRANSLATIONS)
        .order_by(LostItem.created_at.desc(), LostItem.id.desc())
    )
    if query.is_returned is not None:
        statement = statement.where(LostItem.is_returned == query.is_returned)

    async def serialize(items: Sequence[LostItem]) -> list[LostItemOut]:
        return await _serialize(session, items)

    return await paginate(session, statement, query, serialize)


@router.get("/{lost_item_id}", responses={404: {"model": ErrorResponse}})
async def get_lost_item(
    lost_item_id: ResourceId,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
) -> LostItemOut:
    item = await get_or_404(session, LostItem, lost_item_id, _WITH_TRANSLATIONS)
    return await _one(session, item)


@router.post(
    "",
    status_code=HTTPStatus.CREATED,
    responses={409: {"model": ErrorResponse}},
)
async def create_lost_item(
    body: LostItemCreate,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> LostItemOut:
    item = LostItem(is_returned=body.is_returned, translations=[])
    item.image_id = await replace_image(
        session,
        store,
        current_image_id=None,
        object_key=body.image_url,
        resource_type=_IMAGE,
        max_bytes=settings.max_image_bytes,
    )
    upsert_translations(item.translations, body.translations, LostItemTranslation)
    session.add(item)
    await session.flush()
    # `created_at`은 DB 기본값이라 flush 뒤에 다시 읽어야 한다.
    await session.refresh(item, ["created_at"])
    return await _one(session, item)


@router.patch(
    "/{lost_item_id}",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def update_lost_item(
    lost_item_id: ResourceId,
    body: LostItemPatch,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> LostItemOut:
    """이미지 검증이 실패하면 앞서 반영한 필드·번역도 함께 rollback된다.

    행을 잠가 같은 언어를 동시에 insert하는 요청을 직렬화한다. 잠그지 않으면
    unique 위반이 500이 된다. 결과는 명세대로 last-write-wins다.
    """
    item = await get_or_404(
        session, LostItem, lost_item_id, _WITH_TRANSLATIONS, for_update=True
    )
    changes = body.changes()
    if "is_returned" in changes:
        item.is_returned = body.is_returned
    if body.translations is not None:
        upsert_translations(item.translations, body.translations, LostItemTranslation)
    if "image_url" in changes:
        item.image_id = await replace_image(
            session,
            store,
            current_image_id=item.image_id,
            object_key=body.image_url,
            resource_type=_IMAGE,
            max_bytes=settings.max_image_bytes,
        )
    await session.flush()
    return await _one(session, item)


@router.delete(
    "/{lost_item_id}",
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    responses={404: {"model": ErrorResponse}},
)
async def delete_lost_item(
    lost_item_id: ResourceId,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> Response:
    """번역은 FK `ON DELETE CASCADE`로, 이미지는 `DETACHED` 전이로 정리한다."""
    item = await get_or_404(session, LostItem, lost_item_id)
    await replace_image(
        session,
        store,
        current_image_id=item.image_id,
        object_key=None,
        resource_type=_IMAGE,
        max_bytes=settings.max_image_bytes,
    )
    await session.delete(item)
    await session.flush()
    return Response(status_code=HTTPStatus.NO_CONTENT)


@router.delete(
    "/{lost_item_id}/translations/{language_code}",
    status_code=HTTPStatus.NO_CONTENT,
    response_class=Response,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def delete_lost_item_translation(
    lost_item_id: ResourceId,
    language_code: LanguageCode,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
) -> Response:
    await delete_translation(
        session,
        owner=LostItem,
        owner_id=lost_item_id,
        translation=LostItemTranslation,
        owner_fk=LostItemTranslation.lost_item_id,
        language_code=language_code,
    )
    return Response(status_code=HTTPStatus.NO_CONTENT)
