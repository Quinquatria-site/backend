"""장소 CRUD (명세 §5.4, §6)."""

from collections.abc import Sequence
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Query, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backoffice.auth.dependencies import ObjectStoreDep, SessionDep, SettingsDep
from backoffice.crud.images import image_keys, replace_images
from backoffice.crud.resources import get_or_404, paginate
from backoffice.crud.translations import delete_translation, upsert_translations
from backoffice.domains.catalog.common import (
    detach_images,
    id_equals,
    lock_parent,
    no_content,
)
from backoffice.domains.catalog.schemas import (
    PlaceCreate,
    PlaceOut,
    PlacePatch,
    PlaceTranslationOut,
    by_language,
    ensure_hours_ordered,
)
from backoffice.images.store import ObjectStore
from common.errors import ApiError, ErrorCode, ErrorDetail
from common.pagination import Page
from common.query import NoQuery, PageQuery
from common.types import ResourceId
from quinquatria_persistence.enums import ImageResourceType, LanguageCode
from quinquatria_persistence.models import (
    Category,
    Menu,
    Place,
    PlaceImage,
    PlaceTranslation,
)

router = APIRouter(prefix="/places")

_LOADED = (selectinload(Place.translations), selectinload(Place.images))


def _ordered_image_ids(place: Place) -> list[int]:
    return [row.image_id for row in sorted(place.images, key=lambda row: row.seq)]


def _out(place: Place, keys: dict[int, str]) -> PlaceOut:
    image_ids = _ordered_image_ids(place)
    return PlaceOut(
        id=place.id,
        category_id=place.category_id,
        category_sequence=place.category_sequence,
        x=place.x,
        y=place.y,
        start_hour=place.start_hour,
        end_hour=place.end_hour,
        place_image_uri=[keys[image_id] for image_id in image_ids] or None,
        translations=[
            PlaceTranslationOut.model_validate(row)
            for row in by_language(place.translations)
        ],
    )


_SEQUENCE_UNIQUE = "uq_place_category_id_category_sequence"


async def _respond(session: AsyncSession, place: Place) -> PlaceOut:
    """구역 번호 중복은 미리 조회하지 않고 DB unique 제약으로 판정한다.

    조회 후 쓰기는 동시 요청 사이에 틈이 생긴다. 제약 하나로 판정해야 순차
    요청과 동시 요청이 같은 422로 끝난다 (명세 §5.4, §8).
    """
    try:
        await session.flush()
    except IntegrityError as error:
        diag = getattr(error.orig, "diag", None)
        if diag is None or diag.constraint_name != _SEQUENCE_UNIQUE:
            raise
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                ErrorDetail(
                    field="category_sequence",
                    reason="같은 카테고리의 다른 장소가 쓰는 번호입니다.",
                )
            ],
        ) from error
    return _out(place, await image_keys(session, _ordered_image_ids(place)))


async def _set_images(
    session: AsyncSession,
    store: ObjectStore,
    place: Place,
    object_keys: Sequence[str] | None,
    *,
    max_bytes: int,
) -> None:
    """`PlaceImage` 행을 새 배열 순서로 맞춘다.

    남는 이미지의 행은 `seq`만 바꿔 재사용한다. 지우고 다시 넣으면 한 flush
    안에서 `image_id` unique(지연 불가)에 걸릴 수 있다. `seq` unique는
    deferrable이라 중간 중복이 허용된다.
    """
    new_ids = await replace_images(
        session,
        store,
        current_image_ids=_ordered_image_ids(place),
        object_keys=object_keys,
        resource_type=ImageResourceType.PLACE_IMAGE,
        max_bytes=max_bytes,
    )
    rows = {row.image_id: row for row in place.images}
    for row in list(place.images):
        if row.image_id not in new_ids:
            place.images.remove(row)
    for seq, image_id in enumerate(new_ids, start=1):
        row = rows.get(image_id)
        if row is None:
            place.images.append(PlaceImage(image_id=image_id, seq=seq))
        else:
            row.seq = seq


@router.post("", status_code=HTTPStatus.CREATED)
async def create_place(
    body: PlaceCreate,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> PlaceOut:
    ensure_hours_ordered(body.start_hour, body.end_hour)
    await lock_parent(session, Category, body.category_id)
    place = Place(
        category_id=body.category_id,
        category_sequence=body.category_sequence,
        x=body.x,
        y=body.y,
        start_hour=body.start_hour,
        end_hour=body.end_hour,
        # 읽기만 한 빈 컬렉션은 저장되지 않아 flush 뒤 lazy="raise"에 걸린다.
        images=[],
        translations=[
            PlaceTranslation(**item.model_dump()) for item in body.translations
        ],
    )
    await _set_images(
        session,
        store,
        place,
        body.place_image_uri,
        max_bytes=settings.max_image_bytes,
    )
    session.add(place)
    return await _respond(session, place)


@router.patch("/{place_id}")
async def update_place(
    place_id: ResourceId,
    body: PlacePatch,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
    store: ObjectStoreDep,
    settings: SettingsDep,
) -> PlaceOut:
    place = await get_or_404(session, Place, place_id, *_LOADED, for_update=True)
    changes = body.changes()
    ensure_hours_ordered(
        body.start_hour or place.start_hour, body.end_hour or place.end_hour
    )
    if body.category_id is not None and body.category_id != place.category_id:
        await lock_parent(session, Category, body.category_id)
    if "place_image_uri" in changes:
        del changes["place_image_uri"]
        await _set_images(
            session,
            store,
            place,
            body.place_image_uri,
            max_bytes=settings.max_image_bytes,
        )
    for name, value in changes.items():
        setattr(place, name, value)
    if body.translations is not None:
        upsert_translations(place.translations, body.translations, PlaceTranslation)
    return await _respond(session, place)


@router.delete("/{place_id}", status_code=HTTPStatus.NO_CONTENT)
async def delete_place(
    place_id: ResourceId, query: Annotated[NoQuery, Query()], session: SessionDep
) -> Response:
    """번역·메뉴·메뉴 번역·이미지 연결 행은 DB FK cascade가 지운다.

    장소를 `FOR UPDATE`로 잠근 뒤 메뉴 이미지를 모은다. 메뉴 생성·수정은 장소를
    `FOR KEY SHARE`로 잠그므로 그 사이에 이미지를 가진 메뉴가 끼어들 수 없다.
    """
    place = await get_or_404(
        session, Place, place_id, selectinload(Place.images), for_update=True
    )
    menu_image_ids = await session.scalars(
        select(Menu.image_id).where(Menu.place_id == place.id)
    )
    await detach_images(session, [*_ordered_image_ids(place), *menu_image_ids])
    await session.execute(delete(Place).where(Place.id == place.id))
    return no_content()


@router.delete(
    "/{place_id}/translations/{language_code}", status_code=HTTPStatus.NO_CONTENT
)
async def delete_place_translation(
    place_id: ResourceId,
    language_code: LanguageCode,
    query: Annotated[NoQuery, Query()],
    session: SessionDep,
) -> Response:
    await delete_translation(
        session,
        owner=Place,
        owner_id=place_id,
        translation=PlaceTranslation,
        owner_fk=PlaceTranslation.place_id,
        language_code=language_code,
    )
    return no_content()


class PlaceQuery(PageQuery):
    category_id: ResourceId | None = None


@router.get("")
async def list_places(
    query: Annotated[PlaceQuery, Query()], session: SessionDep
) -> Page[PlaceOut]:
    statement = (
        select(Place)
        .options(*_LOADED)
        .order_by(Place.category_id, Place.category_sequence, Place.id)
    )
    if query.category_id is not None:
        statement = statement.where(id_equals(Place.category_id, query.category_id))

    async def serialize(places: Sequence[Place]) -> list[PlaceOut]:
        ids = [image_id for place in places for image_id in _ordered_image_ids(place)]
        keys = await image_keys(session, ids)
        return [_out(place, keys) for place in places]

    return await paginate(session, statement, query, serialize)


@router.get("/{place_id}")
async def get_place(
    place_id: ResourceId, query: Annotated[NoQuery, Query()], session: SessionDep
) -> PlaceOut:
    place = await get_or_404(session, Place, place_id, *_LOADED)
    return await _respond(session, place)
