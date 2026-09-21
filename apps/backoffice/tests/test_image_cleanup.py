"""24시간 유예 cleanup.

DB가 참조하는 key는 후보가 되지 않는다. 유예 시계는 미연결 객체는
`created_at`, 해제된 객체는 `detached_at`이 준다.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from backoffice.images.cleanup import sweep
from quinquatria_persistence.enums import (
    ImageContentType,
    ImageResourceType,
    ImageStatus,
)
from quinquatria_persistence.models import Image

from ._images import FakeObjectStore, put_object

GRACE = 86400
NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)
OLD = NOW - timedelta(hours=25)
RECENT = NOW - timedelta(hours=1)


def _image(key: str, status: ImageStatus, **overrides) -> Image:
    return Image(
        s3_key=key,
        resource_type=ImageResourceType.PLACE_IMAGE,
        content_type=ImageContentType.WEBP,
        declared_size=1024,
        status=status,
        **overrides,
    )


@pytest.fixture
def store() -> FakeObjectStore:
    return FakeObjectStore()


async def _seed(database, images: list[Image], created_at: datetime) -> None:
    async with database.transaction() as session:
        for image in images:
            session.add(image)
        await session.flush()
        for image in images:
            image.created_at = created_at


async def test_stale_uploading_row_is_cleaned(database, store) -> None:
    put_object(store, "images/place/a.webp", body=b"x", content_type="image/webp")
    await _seed(database, [_image("images/place/a.webp", ImageStatus.UPLOADING)], OLD)

    report = await sweep(database, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    assert report.deleted == 1
    assert store.deleted == ["images/place/a.webp"]


async def test_recent_uploading_row_is_kept(database, store) -> None:
    """운영자가 아직 폼을 작성 중인 구간이다."""
    put_object(store, "images/place/a.webp", body=b"x", content_type="image/webp")
    await _seed(
        database, [_image("images/place/a.webp", ImageStatus.UPLOADING)], RECENT
    )

    report = await sweep(database, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    assert report.deleted == 0
    assert store.deleted == []


async def test_attached_row_is_never_a_candidate(database, store) -> None:
    """DB가 참조하는 key는 아무리 오래돼도 지우지 않는다."""
    put_object(store, "images/place/a.webp", body=b"x", content_type="image/webp")
    await _seed(
        database,
        [_image("images/place/a.webp", ImageStatus.ATTACHED)],
        NOW - timedelta(days=90),
    )

    report = await sweep(database, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    assert report.deleted == 0
    assert store.deleted == []


async def test_detached_row_waits_for_its_own_grace(database, store) -> None:
    """3개월 전에 올려 오늘 해제된 객체도 24시간을 기다린다."""
    put_object(store, "images/place/a.webp", body=b"x", content_type="image/webp")
    await _seed(
        database,
        [
            _image(
                "images/place/a.webp",
                ImageStatus.DETACHED,
                detached_at=NOW - timedelta(hours=1),
            )
        ],
        NOW - timedelta(days=90),
    )

    report = await sweep(database, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    assert report.deleted == 0


async def test_detached_row_past_its_grace_is_cleaned(database, store) -> None:
    put_object(store, "images/place/a.webp", body=b"x", content_type="image/webp")
    await _seed(
        database,
        [_image("images/place/a.webp", ImageStatus.DETACHED, detached_at=OLD)],
        NOW - timedelta(days=90),
    )

    report = await sweep(database, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    assert report.deleted == 1


async def test_failed_deletion_still_releases_the_row(database, store) -> None:
    """삭제 권한은 DB에서 먼저 얻으므로 행은 이미 없다.

    남은 객체는 행이 없는 객체가 되어 `_sweep_untracked`의 담당으로
    넘어간다. 행을 남겨 두면 그 행이 가리키는 파일이 정말 있는지 아무도
    보장하지 못한다.
    """
    put_object(
        store,
        "images/place/a.webp",
        body=b"x",
        content_type="image/webp",
        last_modified=OLD,
    )
    store.delete_failures.add("images/place/a.webp")
    await _seed(database, [_image("images/place/a.webp", ImageStatus.UPLOADING)], OLD)

    report = await sweep(database, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    assert report.failed == 1
    assert report.deleted == 0

    async with database.session() as session:
        remaining = (await session.execute(select(Image))).scalars().all()

    assert remaining == []
    assert "images/place/a.webp" in store.objects


async def test_rerunning_after_a_failure_reclaims_the_object(database, store) -> None:
    """첫 실행이 행을 지웠으므로 두 번째 실행은 고아 객체로 회수한다."""
    put_object(
        store,
        "images/place/a.webp",
        body=b"x",
        content_type="image/webp",
        last_modified=OLD,
    )
    store.delete_failures.add("images/place/a.webp")
    await _seed(database, [_image("images/place/a.webp", ImageStatus.UPLOADING)], OLD)

    await sweep(database, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    store.delete_failures.clear()

    report = await sweep(database, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    assert report.orphans == 1
    assert store.deleted == ["images/place/a.webp"]


async def test_object_without_a_row_is_swept_as_an_orphan(database, store) -> None:
    """발급 transaction이 rollback됐는데 S3 PUT은 성공한 경우."""
    put_object(
        store,
        "images/place/ghost.webp",
        body=b"x",
        content_type="image/webp",
        last_modified=OLD,
    )

    report = await sweep(database, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    assert report.orphans == 1
    assert store.deleted == ["images/place/ghost.webp"]


async def test_recent_object_without_a_row_is_kept(database, store) -> None:
    put_object(
        store,
        "images/place/ghost.webp",
        body=b"x",
        content_type="image/webp",
        last_modified=RECENT,
    )

    report = await sweep(database, store, now=NOW, grace_seconds=GRACE, batch_size=100)

    assert report.orphans == 0
    assert store.deleted == []


async def test_batch_size_caps_one_run(database, store) -> None:
    images = []
    for index in range(5):
        key = f"images/place/{index}.webp"
        put_object(store, key, body=b"x", content_type="image/webp")
        images.append(_image(key, ImageStatus.UPLOADING))
    await _seed(database, images, OLD)

    report = await sweep(database, store, now=NOW, grace_seconds=GRACE, batch_size=2)

    assert report.deleted == 2
