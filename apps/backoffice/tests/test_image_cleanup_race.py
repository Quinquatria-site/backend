"""attach와 cleanup이 같은 이미지를 두고 만날 때의 계약.

후보 조회와 S3 삭제 사이에 다른 transaction이 같은 이미지를 `ATTACHED`로
바꾸고 리소스 FK까지 commit할 수 있다. 이때 이전에 읽은 상태로 객체를
지우면 DB는 참조를 유지한 채 파일만 사라진다. DB 제약은 이미 삭제한
파일을 복구하지 못하므로, 삭제 권한은 DB에서 원자적으로 얻어야 한다.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backoffice.images.cleanup import sweep
from backoffice.images.service import attach
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
OTHER_KEY = "images/category/other.webp"
MAX_BYTES = 10 * 1024 * 1024
GRACE = 86400
NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)
OLD = NOW - timedelta(hours=25)


def _image(key: str) -> Image:
    return Image(
        s3_key=key,
        resource_type=ImageResourceType.CATEGORY_ICON,
        content_type=ImageContentType.WEBP,
        declared_size=len(WEBP),
        status=ImageStatus.UPLOADING,
    )


async def _seed(database, keys: list[str]) -> None:
    """유예가 지난 UPLOADING 행을 만든다. 모두 회수 후보다."""
    async with database.transaction() as session:
        images = [_image(key) for key in keys]
        for image in images:
            session.add(image)
        await session.flush()
        for image in images:
            image.created_at = OLD


async def _attach_to_new_category(database, store, key: str) -> None:
    """다른 transaction이 이미지를 연결하고 commit한다.

    실제 운영 경로와 같게 `attach`가 S3를 다시 검증하고, 같은
    transaction에서 리소스의 `image_id`에 넣는다.
    """
    async with database.transaction() as session:
        image = await attach(
            session,
            store,
            object_key=key,
            resource_type=ImageResourceType.CATEGORY_ICON,
            current_image_id=None,
            max_bytes=MAX_BYTES,
        )
        await session.flush()
        session.add(Category(code=CategoryCode.PUB, image_id=image.id))


class _AttachRacingDatabase:
    """후보를 읽은 뒤 삭제를 선점하기 직전에 attach가 commit된 상황.

    경합 창은 sweep이 후보 목록을 확정한 다음부터다. 첫 삭제 transaction이
    열리기 직전에 끼어들어 그 창을 재현한다.
    """

    def __init__(self, database, store: FakeObjectStore, key: str) -> None:
        self._database = database
        self._store = store
        self._key = key
        self.raced = False

    def session(self):
        return self._database.session()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        if not self.raced:
            self.raced = True
            await _attach_to_new_category(self._database, self._store, self._key)
        async with self._database.transaction() as session:
            yield session


@pytest.fixture
def store() -> FakeObjectStore:
    fake = FakeObjectStore()
    put_object(fake, KEY, body=WEBP, content_type="image/webp")
    return fake


@pytest.fixture
def racing(database, store) -> _AttachRacingDatabase:
    return _AttachRacingDatabase(database, store, KEY)


async def test_image_attached_during_the_sweep_keeps_its_object(
    database, store, racing
) -> None:
    """연결된 이미지의 객체는 지워지지 않는다."""
    await _seed(database, [KEY])

    report = await sweep(racing, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    assert racing.raced, "경합을 재현하지 못했다"
    assert store.deleted == []
    assert KEY in store.objects
    assert report.deleted == 0


async def test_image_attached_during_the_sweep_keeps_db_and_store_agreed(
    database, store, racing
) -> None:
    """DB가 참조하는 이미지는 실제로 존재해야 한다."""
    await _seed(database, [KEY])

    await sweep(racing, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    async with database.session() as session:
        image = (await session.execute(select(Image))).scalar_one()
        category = (await session.execute(select(Category))).scalar_one()

    assert image.status is ImageStatus.ATTACHED
    assert category.image_id == image.id
    assert image.s3_key in store.objects


async def test_one_raced_image_does_not_spare_the_rest_of_the_batch(
    database, store, racing
) -> None:
    """한 건의 경합이 같은 배치의 다른 회수를 되돌리지 않는다."""
    put_object(store, OTHER_KEY, body=WEBP, content_type="image/webp")
    await _seed(database, [KEY, OTHER_KEY])

    report = await sweep(racing, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    assert racing.raced
    assert store.deleted == [OTHER_KEY]
    assert report.deleted == 1

    async with database.session() as session:
        remaining = (await session.execute(select(Image.s3_key))).scalars().all()

    assert remaining == [KEY]
