"""같은 이미지를 동시에 연결하려는 두 요청의 계약.

이미지 하나는 기본 리소스 하나에만 붙는다(명세 §4.6). 두 transaction이
같은 `UPLOADING` key를 읽고 각자 다른 리소스에 연결하면, DB의 unique
제약이 둘 중 하나를 막는다. 그 실패는 client 입력에 대한 판정이므로
`IntegrityError`가 아니라 409 `IMAGE_ALREADY_ATTACHED`로 나가야 한다.

상태 확인과 전이가 직렬화되면 뒤에 온 요청은 `ATTACHED`를 보고 스스로
409를 낸다. 제약에 걸려 죽는 것과 규칙에 따라 거절하는 것은 다르다.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from backoffice.images.service import attach, attach_many
from common.errors import ApiError, ErrorCode
from quinquatria_persistence.enums import (
    CategoryCode,
    ImageContentType,
    ImageResourceType,
    ImageStatus,
)
from quinquatria_persistence.models import Category, Image

from ._images import FakeObjectStore, put_object

WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 64
KEY = "images/category/icon.webp"
MAX_BYTES = 10 * 1024 * 1024
BLOCKED_FOR = 0.5
"""뒤의 요청이 잠금에 막혀 있음을 확인하는 시간."""


@pytest.fixture
def store() -> FakeObjectStore:
    fake = FakeObjectStore()
    put_object(
        fake, KEY, body=WEBP, content_type="image/webp", last_modified=datetime.now(UTC)
    )
    return fake


async def _seed(database) -> None:
    async with database.transaction() as session:
        session.add(
            Image(
                s3_key=KEY,
                resource_type=ImageResourceType.CATEGORY_ICON,
                content_type=ImageContentType.WEBP,
                declared_size=len(WEBP),
                status=ImageStatus.UPLOADING,
            )
        )


async def _attach_to_category(database, store, code: CategoryCode) -> None:
    """하나의 독립 session이 이미지를 검증하고 카테고리에 연결한다."""
    async with database.transaction() as session:
        image = await attach(
            session,
            store,
            object_key=KEY,
            resource_type=ImageResourceType.CATEGORY_ICON,
            current_image_id=None,
            max_bytes=MAX_BYTES,
        )
        await session.flush()
        session.add(Category(code=code, image_id=image.id))


async def test_second_attach_waits_and_is_rejected_as_conflict(database, store) -> None:
    """먼저 연결한 쪽이 commit하기 전까지 뒤의 요청은 판정을 미룬다."""
    await _seed(database)

    async with database.transaction() as first:
        image = await attach(
            first,
            store,
            object_key=KEY,
            resource_type=ImageResourceType.CATEGORY_ICON,
            current_image_id=None,
            max_bytes=MAX_BYTES,
        )
        await first.flush()
        first.add(Category(code=CategoryCode.PUB, image_id=image.id))

        # 앞의 transaction이 아직 열려 있는 동안 두 번째 요청이 들어온다.
        second = asyncio.create_task(
            _attach_to_category(database, store, CategoryCode.BOOTH)
        )
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(second), timeout=BLOCKED_FOR)

    # 앞의 transaction이 commit된 뒤에야 두 번째가 상태를 읽는다.
    with pytest.raises(ApiError) as error:
        await second

    assert error.value.code is ErrorCode.IMAGE_ALREADY_ATTACHED


async def test_losing_attach_leaves_the_winner_untouched(database, store) -> None:
    """경쟁에서 진 요청은 이긴 쪽의 연결을 건드리지 않는다."""
    await _seed(database)

    async with database.transaction() as first:
        image = await attach(
            first,
            store,
            object_key=KEY,
            resource_type=ImageResourceType.CATEGORY_ICON,
            current_image_id=None,
            max_bytes=MAX_BYTES,
        )
        await first.flush()
        first.add(Category(code=CategoryCode.PUB, image_id=image.id))
        second = asyncio.create_task(
            _attach_to_category(database, store, CategoryCode.BOOTH)
        )
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(second), timeout=BLOCKED_FOR)

    with pytest.raises(ApiError):
        await second

    async with database.session() as session:
        categories = (await session.execute(select(Category))).scalars().all()
        stored = (await session.execute(select(Image))).scalar_one()

    assert [category.code for category in categories] == [CategoryCode.PUB]
    assert categories[0].image_id == stored.id
    assert stored.status is ImageStatus.ATTACHED


PLACE_KEYS = ("images/place/a.webp", "images/place/b.webp")
MEET_WITHIN = 0.5
"""두 요청이 첫 검증에서 서로를 기다리는 한도. 잠금에 막힌 쪽은 오지 못한다."""


class MeetingStore(FakeObjectStore):
    """처음 두 `head`가 서로를 기다렸다가 함께 진행하게 한다.

    두 요청이 각자 첫 이미지를 잠근 채 다음 이미지로 넘어가는 순간을
    재현한다. 한쪽이 잠금에 막혀 오지 못하면 한도 후 혼자 진행한다.
    """

    def __init__(self) -> None:
        super().__init__()
        self.arrivals = 0
        self.met = asyncio.Event()

    async def head(self, key: str):
        self.arrivals += 1
        if self.arrivals <= 2:
            if self.arrivals == 2:
                self.met.set()
            try:
                await asyncio.wait_for(self.met.wait(), timeout=MEET_WITHIN)
            except TimeoutError:
                pass
        return await super().head(key)


async def _attach_places(database, store, keys) -> list[int]:
    async with database.transaction() as session:
        images = await attach_many(
            session,
            store,
            object_keys=keys,
            resource_type=ImageResourceType.PLACE_IMAGE,
            current_image_ids=(),
            max_bytes=MAX_BYTES,
        )
        return [image.id for image in images]


async def test_reversed_arrays_conflict_instead_of_deadlocking(database) -> None:
    """같은 두 이미지를 반대 순서로 연결해도 교착 없이 한쪽만 409다."""
    store = MeetingStore()
    async with database.transaction() as session:
        for key in PLACE_KEYS:
            put_object(store, key, body=WEBP, content_type="image/webp")
            session.add(
                Image(
                    s3_key=key,
                    resource_type=ImageResourceType.PLACE_IMAGE,
                    content_type=ImageContentType.WEBP,
                    declared_size=len(WEBP),
                    status=ImageStatus.UPLOADING,
                )
            )

    forward, backward = await asyncio.gather(
        _attach_places(database, store, list(PLACE_KEYS)),
        _attach_places(database, store, list(reversed(PLACE_KEYS))),
        return_exceptions=True,
    )

    outcomes = [forward, backward]
    errors = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
    assert len(errors) == 1
    assert isinstance(errors[0], ApiError)
    assert errors[0].code is ErrorCode.IMAGE_ALREADY_ATTACHED


async def test_attach_many_returns_images_in_request_order(database) -> None:
    """잠금 순서와 무관하게 반환 순서는 요청 배열을 따른다."""
    store = FakeObjectStore()
    keys = list(reversed(PLACE_KEYS))
    async with database.transaction() as session:
        for key in PLACE_KEYS:
            put_object(store, key, body=WEBP, content_type="image/webp")
            session.add(
                Image(
                    s3_key=key,
                    resource_type=ImageResourceType.PLACE_IMAGE,
                    content_type=ImageContentType.WEBP,
                    declared_size=len(WEBP),
                    status=ImageStatus.UPLOADING,
                )
            )

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
