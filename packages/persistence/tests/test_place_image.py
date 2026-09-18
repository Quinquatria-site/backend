"""`place_image`는 장소 이미지의 순서와 중복 금지를 DB로 보장한다.

기존 `place_image_uri` 배열이 CHECK로 갖고 있던 성질 중 차원과 NULL 금지는
테이블 구조가 대신한다. 최소 1개 제약만 서비스 계층으로 내려간다.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ._data import VALID_IMAGE, VALID_ROWS, insert_row


async def _place_with_images(connection, count: int) -> list[int]:
    await insert_row(connection, "category", VALID_ROWS["category"])
    await insert_row(connection, "place", VALID_ROWS["place"])
    return [
        await insert_row(
            connection,
            "image",
            VALID_IMAGE | {"s3_key": f"images/place/{index}.webp"},
        )
        for index in range(count)
    ]


async def test_images_keep_their_declared_order(database) -> None:
    async with database.engine.begin() as connection:
        first, second = await _place_with_images(connection, 2)
        await insert_row(
            connection, "place_image", {"place_id": 1, "image_id": second, "seq": 1}
        )
        await insert_row(
            connection, "place_image", {"place_id": 1, "image_id": first, "seq": 2}
        )

        keys = (
            (
                await connection.execute(
                    text(
                        "SELECT i.s3_key FROM place_image p "
                        "JOIN image i ON i.id = p.image_id "
                        "WHERE p.place_id = 1 ORDER BY p.seq"
                    )
                )
            )
            .scalars()
            .all()
        )

    assert keys == ["images/place/1.webp", "images/place/0.webp"]


async def test_one_image_cannot_be_used_twice(database) -> None:
    async with database.engine.begin() as connection:
        first, _ = await _place_with_images(connection, 2)
        await insert_row(
            connection, "place_image", {"place_id": 1, "image_id": first, "seq": 1}
        )

    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await insert_row(
                connection, "place_image", {"place_id": 1, "image_id": first, "seq": 2}
            )


async def test_a_place_cannot_repeat_a_sequence(database) -> None:
    async with database.engine.begin() as connection:
        first, second = await _place_with_images(connection, 2)
        await insert_row(
            connection, "place_image", {"place_id": 1, "image_id": first, "seq": 1}
        )

    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await insert_row(
                connection, "place_image", {"place_id": 1, "image_id": second, "seq": 1}
            )


async def test_sequences_may_be_rewritten_within_one_transaction(database) -> None:
    """deferrable 제약이라 순서 재배치의 중간 상태가 허용된다."""
    async with database.engine.begin() as connection:
        first, second = await _place_with_images(connection, 2)
        await insert_row(
            connection, "place_image", {"place_id": 1, "image_id": first, "seq": 1}
        )
        await insert_row(
            connection, "place_image", {"place_id": 1, "image_id": second, "seq": 2}
        )

    async with database.engine.begin() as connection:
        await connection.execute(
            text("UPDATE place_image SET seq = 3 - seq WHERE place_id = 1")
        )

        order = (
            (
                await connection.execute(
                    text(
                        "SELECT image_id FROM place_image WHERE place_id = 1 ORDER BY seq"
                    )
                )
            )
            .scalars()
            .all()
        )

    assert order == [second, first]


async def test_deleting_a_place_removes_its_links(database) -> None:
    async with database.engine.begin() as connection:
        first, _ = await _place_with_images(connection, 2)
        await insert_row(
            connection, "place_image", {"place_id": 1, "image_id": first, "seq": 1}
        )

    async with database.engine.begin() as connection:
        await connection.execute(text("DELETE FROM place WHERE id = 1"))
        remaining = await connection.scalar(text("SELECT count(*) FROM place_image"))
        images = await connection.scalar(text("SELECT count(*) FROM image"))

    assert remaining == 0
    # 링크만 사라지고 image 행은 남는다. DETACHED 전이는 서비스 계층이 한다.
    assert images == 2
