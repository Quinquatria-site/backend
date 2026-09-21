"""`image` 테이블은 object key의 수명 주기를 소유한다.

`s3_key` unique가 "한 key는 한 기본 리소스에만"을 DB 수준에서 강제하고,
`detached_at` 제약이 sweep의 유예 계산이 기대는 불변식을 지킨다.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ._data import VALID_IMAGE, insert_row


async def test_image_row_round_trips(database) -> None:
    async with database.engine.begin() as connection:
        image_id = await insert_row(connection, "image", VALID_IMAGE)
        row = (
            (
                await connection.execute(
                    text("SELECT * FROM image WHERE id = :id"), {"id": image_id}
                )
            )
            .mappings()
            .one()
        )

    assert row["s3_key"] == VALID_IMAGE["s3_key"]
    assert row["status"] == "UPLOADING"
    assert row["content_type"] == "image/webp"
    assert row["byte_size"] is None
    assert row["detached_at"] is None
    assert row["created_at"] is not None


async def test_duplicate_s3_key_is_rejected(database) -> None:
    async with database.engine.begin() as connection:
        await insert_row(connection, "image", VALID_IMAGE)

    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await insert_row(connection, "image", VALID_IMAGE)


@pytest.mark.parametrize("size", [0, -1, 10485761])
async def test_declared_size_outside_the_allowed_range_is_rejected(
    database, size: int
) -> None:
    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await insert_row(connection, "image", VALID_IMAGE | {"declared_size": size})


async def test_detached_status_requires_a_detached_at(database) -> None:
    """sweep의 유예 계산이 이 불변식에 기댄다."""
    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await insert_row(connection, "image", VALID_IMAGE | {"status": "DETACHED"})


async def test_non_detached_status_forbids_a_detached_at(database) -> None:
    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await insert_row(
                connection,
                "image",
                VALID_IMAGE | {"detached_at": datetime(2026, 10, 6, tzinfo=UTC)},
            )
