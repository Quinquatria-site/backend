"""명세 §4.6의 연결 검증.

발급 요청의 선언값을 믿지 않고 S3에 직접 묻는다. 여기서는 크기 초과도
422 INVALID_IMAGE다. 413은 발급 요청의 선언 크기에만 쓴다.
"""

from datetime import UTC, datetime

import pytest

from backoffice.images.service import attach, attach_many, detach
from common.errors import ApiError, ErrorCode
from quinquatria_persistence.enums import (
    ImageContentType,
    ImageResourceType,
    ImageStatus,
)
from quinquatria_persistence.models import Image

from ._images import FakeObjectStore, put_object

WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 64
KEY = "images/place/a.webp"
MAX_BYTES = 10 * 1024 * 1024


def _image(**overrides) -> Image:
    """기본값을 override가 덮어쓰게 한다.

    기본값을 인자로 직접 넘기면 `status`처럼 덮어쓸 필드가 중복 전달된다.
    """
    return Image(
        **{
            "s3_key": KEY,
            "resource_type": ImageResourceType.PLACE_IMAGE,
            "content_type": ImageContentType.WEBP,
            "declared_size": len(WEBP),
            "status": ImageStatus.UPLOADING,
        }
        | overrides
    )


@pytest.fixture
def store() -> FakeObjectStore:
    fake = FakeObjectStore()
    put_object(fake, KEY, body=WEBP, content_type="image/webp")
    return fake


async def _seed(database, image: Image) -> int:
    async with database.transaction() as session:
        session.add(image)
        await session.flush()
        return image.id


async def test_valid_key_becomes_attached(database, store) -> None:
    await _seed(database, _image())

    async with database.transaction() as session:
        attached = await attach(
            session,
            store,
            object_key=KEY,
            resource_type=ImageResourceType.PLACE_IMAGE,
            current_image_id=None,
            max_bytes=MAX_BYTES,
        )

    assert attached.status is ImageStatus.ATTACHED
    assert attached.byte_size == len(WEBP)


async def test_unknown_key_is_invalid_image(database, store) -> None:
    async with database.transaction() as session:
        with pytest.raises(ApiError) as error:
            await attach(
                session,
                store,
                object_key="images/place/never-issued.webp",
                resource_type=ImageResourceType.PLACE_IMAGE,
                current_image_id=None,
                max_bytes=MAX_BYTES,
            )

    assert error.value.code is ErrorCode.INVALID_IMAGE


async def test_prefix_mismatch_is_invalid_image(database, store) -> None:
    await _seed(database, _image())

    async with database.transaction() as session:
        with pytest.raises(ApiError) as error:
            await attach(
                session,
                store,
                object_key=KEY,
                resource_type=ImageResourceType.MENU_IMAGE,
                current_image_id=None,
                max_bytes=MAX_BYTES,
            )

    assert error.value.code is ErrorCode.INVALID_IMAGE


async def test_missing_s3_object_is_invalid_image(database) -> None:
    await _seed(database, _image())
    empty = FakeObjectStore()

    async with database.transaction() as session:
        with pytest.raises(ApiError) as error:
            await attach(
                session,
                empty,
                object_key=KEY,
                resource_type=ImageResourceType.PLACE_IMAGE,
                current_image_id=None,
                max_bytes=MAX_BYTES,
            )

    assert error.value.code is ErrorCode.INVALID_IMAGE


async def test_actual_size_over_the_limit_is_invalid_image(database) -> None:
    """발급 때 작게 선언하고 크게 올린 경우. 413이 아니라 422다."""
    await _seed(database, _image())
    store = FakeObjectStore()
    put_object(
        store,
        KEY,
        body=b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * MAX_BYTES,
        content_type="image/webp",
    )

    async with database.transaction() as session:
        with pytest.raises(ApiError) as error:
            await attach(
                session,
                store,
                object_key=KEY,
                resource_type=ImageResourceType.PLACE_IMAGE,
                current_image_id=None,
                max_bytes=MAX_BYTES,
            )

    assert error.value.code is ErrorCode.INVALID_IMAGE


async def test_content_type_mismatch_is_invalid_image(database) -> None:
    await _seed(database, _image())
    store = FakeObjectStore()
    put_object(store, KEY, body=WEBP, content_type="image/png")

    async with database.transaction() as session:
        with pytest.raises(ApiError) as error:
            await attach(
                session,
                store,
                object_key=KEY,
                resource_type=ImageResourceType.PLACE_IMAGE,
                current_image_id=None,
                max_bytes=MAX_BYTES,
            )

    assert error.value.code is ErrorCode.INVALID_IMAGE


async def test_payload_that_is_not_an_image_is_rejected(database) -> None:
    """헤더만 맞춘 비이미지 업로드. presigned로는 막을 수 없는 경로다."""
    await _seed(database, _image())
    store = FakeObjectStore()
    put_object(store, KEY, body=b"#!/bin/sh\nrm -rf /", content_type="image/webp")

    async with database.transaction() as session:
        with pytest.raises(ApiError) as error:
            await attach(
                session,
                store,
                object_key=KEY,
                resource_type=ImageResourceType.PLACE_IMAGE,
                current_image_id=None,
                max_bytes=MAX_BYTES,
            )

    assert error.value.code is ErrorCode.INVALID_IMAGE


async def test_key_used_by_another_resource_is_a_conflict(database, store) -> None:
    image_id = await _seed(database, _image(status=ImageStatus.ATTACHED))

    async with database.transaction() as session:
        with pytest.raises(ApiError) as error:
            await attach(
                session,
                store,
                object_key=KEY,
                resource_type=ImageResourceType.PLACE_IMAGE,
                current_image_id=image_id + 1,
                max_bytes=MAX_BYTES,
            )

    assert error.value.code is ErrorCode.IMAGE_ALREADY_ATTACHED
    assert error.value.status_code == 409


async def test_resending_the_same_key_is_allowed(database, store) -> None:
    """명세 §4.6: 현재 리소스가 이미 쓰는 key의 무변경 재전송은 허용한다."""
    image_id = await _seed(database, _image(status=ImageStatus.ATTACHED))

    async with database.transaction() as session:
        attached = await attach(
            session,
            store,
            object_key=KEY,
            resource_type=ImageResourceType.PLACE_IMAGE,
            current_image_id=image_id,
            max_bytes=MAX_BYTES,
        )

    assert attached.id == image_id
    assert attached.status is ImageStatus.ATTACHED


async def test_detached_key_cannot_be_reattached(database, store) -> None:
    """이미 cleanup 대기열에 오른 key다. 삭제된 객체를 가리키게 된다."""
    await _seed(
        database,
        _image(status=ImageStatus.DETACHED, detached_at=datetime.now(UTC)),
    )

    async with database.transaction() as session:
        with pytest.raises(ApiError) as error:
            await attach(
                session,
                store,
                object_key=KEY,
                resource_type=ImageResourceType.PLACE_IMAGE,
                current_image_id=None,
                max_bytes=MAX_BYTES,
            )

    assert error.value.code is ErrorCode.INVALID_IMAGE


async def test_duplicate_keys_in_one_array_are_rejected(database, store) -> None:
    await _seed(database, _image())

    async with database.transaction() as session:
        with pytest.raises(ApiError) as error:
            await attach_many(
                session,
                store,
                object_keys=[KEY, KEY],
                resource_type=ImageResourceType.PLACE_IMAGE,
                current_image_ids=(),
                max_bytes=MAX_BYTES,
            )

    assert error.value.code is ErrorCode.INVALID_IMAGE


async def test_empty_array_is_a_validation_error(database, store) -> None:
    """명세 §4.6: 이미지가 없는 장소는 빈 배열이 아니라 null이다."""
    async with database.transaction() as session:
        with pytest.raises(ApiError) as error:
            await attach_many(
                session,
                store,
                object_keys=[],
                resource_type=ImageResourceType.PLACE_IMAGE,
                current_image_ids=(),
                max_bytes=MAX_BYTES,
            )

    assert error.value.code is ErrorCode.VALIDATION_ERROR


async def test_attach_many_preserves_order(database) -> None:
    store = FakeObjectStore()
    keys = ["images/place/second.webp", "images/place/first.webp"]
    async with database.transaction() as session:
        for key in keys:
            put_object(store, key, body=WEBP, content_type="image/webp")
            session.add(_image(s3_key=key))

    async with database.transaction() as session:
        attached = await attach_many(
            session,
            store,
            object_keys=keys,
            resource_type=ImageResourceType.PLACE_IMAGE,
            current_image_ids=(),
            max_bytes=MAX_BYTES,
        )

    assert [image.s3_key for image in attached] == keys


async def test_detach_records_the_moment(database, store) -> None:
    image_id = await _seed(database, _image(status=ImageStatus.ATTACHED))
    moment = datetime.now(UTC)

    async with database.transaction() as session:
        await detach(session, image_ids=[image_id], now=moment)

    async with database.session() as session:
        stored = await session.get(Image, image_id)

    assert stored.status is ImageStatus.DETACHED
    assert stored.detached_at == moment


async def test_detach_does_not_touch_s3(database, store) -> None:
    """S3 삭제 실패가 DB transaction을 rollback하지 않게 하는 구조다."""
    image_id = await _seed(database, _image(status=ImageStatus.ATTACHED))

    async with database.transaction() as session:
        await detach(session, image_ids=[image_id], now=datetime.now(UTC))

    assert store.deleted == []
    assert KEY in store.objects
