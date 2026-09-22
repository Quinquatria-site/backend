"""리소스 이미지 필드의 연결·교체·해제 (명세 §4.6)."""

from datetime import UTC, datetime

import pytest

from backoffice.crud.images import image_keys, replace_image, replace_images
from common.errors import ApiError, ErrorCode
from quinquatria_persistence.enums import (
    ImageContentType,
    ImageResourceType,
    ImageStatus,
)
from quinquatria_persistence.models import Image

from ._images import FakeObjectStore, put_object

WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 64
MAX_BYTES = 10 * 1024 * 1024
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
LOST = ImageResourceType.LOST_ITEM_IMAGE
PLACE = ImageResourceType.PLACE_IMAGE
_PREFIX = {LOST: "images/lost-item/", PLACE: "images/place/"}


@pytest.fixture
def store() -> FakeObjectStore:
    return FakeObjectStore()


async def _image(
    database,
    store: FakeObjectStore,
    name: str,
    *,
    resource_type: ImageResourceType = LOST,
    status: ImageStatus = ImageStatus.UPLOADING,
) -> tuple[int, str]:
    """업로드된 객체와 원장 행을 함께 만든다."""
    key = f"{_PREFIX[resource_type]}{name}.webp"
    put_object(store, key, body=WEBP, content_type="image/webp")
    async with database.transaction() as session:
        image = Image(
            s3_key=key,
            resource_type=resource_type,
            content_type=ImageContentType.WEBP,
            declared_size=len(WEBP),
            byte_size=len(WEBP) if status is ImageStatus.ATTACHED else None,
            status=status,
        )
        session.add(image)
        await session.flush()
        return image.id, key


async def _status(database, image_id: int) -> tuple[ImageStatus, datetime | None]:
    async with database.session() as session:
        image = await session.get(Image, image_id)
        return image.status, image.detached_at


async def _replace(database, store, **kwargs):
    async with database.transaction() as session:
        return await replace_image(
            session, store, resource_type=LOST, max_bytes=MAX_BYTES, now=NOW, **kwargs
        )


async def _replace_many(database, store, **kwargs):
    async with database.transaction() as session:
        return await replace_images(
            session, store, resource_type=PLACE, max_bytes=MAX_BYTES, now=NOW, **kwargs
        )


async def test_new_key_is_attached(database, store) -> None:
    image_id, key = await _image(database, store, "new")

    result = await _replace(database, store, current_image_id=None, object_key=key)

    assert result == image_id
    assert await _status(database, image_id) == (ImageStatus.ATTACHED, None)


async def test_resending_current_key_changes_nothing(database, store) -> None:
    image_id, key = await _image(database, store, "same", status=ImageStatus.ATTACHED)

    result = await _replace(database, store, current_image_id=image_id, object_key=key)

    assert result == image_id
    assert await _status(database, image_id) == (ImageStatus.ATTACHED, None)


async def test_new_key_detaches_previous_image(database, store) -> None:
    old_id, _ = await _image(database, store, "old", status=ImageStatus.ATTACHED)
    new_id, new_key = await _image(database, store, "new")

    result = await _replace(
        database, store, current_image_id=old_id, object_key=new_key
    )

    assert result == new_id
    assert await _status(database, new_id) == (ImageStatus.ATTACHED, None)
    assert await _status(database, old_id) == (ImageStatus.DETACHED, NOW)


async def test_null_detaches_current_image(database, store) -> None:
    old_id, _ = await _image(database, store, "old", status=ImageStatus.ATTACHED)

    result = await _replace(database, store, current_image_id=old_id, object_key=None)

    assert result is None
    assert await _status(database, old_id) == (ImageStatus.DETACHED, NOW)


async def test_null_without_current_image_is_noop(database, store) -> None:
    assert (
        await _replace(database, store, current_image_id=None, object_key=None) is None
    )


async def test_key_used_by_another_resource_is_conflict(database, store) -> None:
    _, key = await _image(database, store, "taken", status=ImageStatus.ATTACHED)

    with pytest.raises(ApiError) as caught:
        await _replace(database, store, current_image_id=None, object_key=key)

    assert caught.value.code is ErrorCode.IMAGE_ALREADY_ATTACHED


async def test_array_keeps_order_and_detaches_only_removed(database, store) -> None:
    kept_id, kept_key = await _image(
        database, store, "kept", resource_type=PLACE, status=ImageStatus.ATTACHED
    )
    dropped_id, _ = await _image(
        database, store, "dropped", resource_type=PLACE, status=ImageStatus.ATTACHED
    )
    added_id, added_key = await _image(database, store, "added", resource_type=PLACE)

    result = await _replace_many(
        database,
        store,
        current_image_ids=[kept_id, dropped_id],
        object_keys=[added_key, kept_key],
    )

    assert result == [added_id, kept_id]
    assert await _status(database, kept_id) == (ImageStatus.ATTACHED, None)
    assert await _status(database, added_id) == (ImageStatus.ATTACHED, None)
    assert await _status(database, dropped_id) == (ImageStatus.DETACHED, NOW)


async def test_array_null_detaches_all(database, store) -> None:
    first_id, _ = await _image(
        database, store, "first", resource_type=PLACE, status=ImageStatus.ATTACHED
    )
    second_id, _ = await _image(
        database, store, "second", resource_type=PLACE, status=ImageStatus.ATTACHED
    )

    result = await _replace_many(
        database, store, current_image_ids=[first_id, second_id], object_keys=None
    )

    assert result == []
    assert await _status(database, first_id) == (ImageStatus.DETACHED, NOW)
    assert await _status(database, second_id) == (ImageStatus.DETACHED, NOW)


async def test_image_keys_maps_ids_and_skips_none(database, store) -> None:
    first_id, first_key = await _image(database, store, "first")
    second_id, second_key = await _image(database, store, "second")

    async with database.session() as session:
        keys = await image_keys(session, [first_id, None, second_id, first_id])

    assert keys == {first_id: first_key, second_id: second_key}


async def test_image_keys_without_ids_is_empty(database) -> None:
    async with database.session() as session:
        assert await image_keys(session, [None]) == {}
