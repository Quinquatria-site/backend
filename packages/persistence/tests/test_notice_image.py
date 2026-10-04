"""`notice_image`는 공지 이미지의 순서와 중복 금지를 DB로 보장한다.

`place_image`와 같은 구조다. 최소 1개 제약은 서비스 계층이 맡는다.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ._data import VALID_IMAGE, VALID_ROWS, insert_row


async def _notice_with_images(connection, count: int) -> list[int]:
    await insert_row(connection, "notice", VALID_ROWS["notice"])
    return [
        await insert_row(
            connection,
            "image",
            VALID_IMAGE
            | {
                "s3_key": f"images/notice/{index}.webp",
                "resource_type": "NOTICE_IMAGE",
            },
        )
        for index in range(count)
    ]


async def _link(connection, image_id: int, seq: int) -> None:
    await insert_row(
        connection, "notice_image", {"notice_id": 1, "image_id": image_id, "seq": seq}
    )


async def test_images_keep_their_declared_order(database) -> None:
    async with database.engine.begin() as connection:
        first, second = await _notice_with_images(connection, 2)
        await _link(connection, second, 1)
        await _link(connection, first, 2)

        keys = (
            (
                await connection.execute(
                    text(
                        "SELECT i.s3_key FROM notice_image n "
                        "JOIN image i ON i.id = n.image_id "
                        "WHERE n.notice_id = 1 ORDER BY n.seq"
                    )
                )
            )
            .scalars()
            .all()
        )

    assert keys == ["images/notice/1.webp", "images/notice/0.webp"]


async def test_one_image_cannot_be_used_twice(database) -> None:
    async with database.engine.begin() as connection:
        first, _ = await _notice_with_images(connection, 2)
        await _link(connection, first, 1)

    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await _link(connection, first, 2)


async def test_a_notice_cannot_repeat_a_sequence(database) -> None:
    async with database.engine.begin() as connection:
        first, second = await _notice_with_images(connection, 2)
        await _link(connection, first, 1)

    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await _link(connection, second, 1)


async def test_sequences_may_be_rewritten_within_one_transaction(database) -> None:
    """deferrable 제약이라 순서 재배치의 중간 상태가 허용된다."""
    async with database.engine.begin() as connection:
        first, second = await _notice_with_images(connection, 2)
        await _link(connection, first, 1)
        await _link(connection, second, 2)

    async with database.engine.begin() as connection:
        await connection.execute(
            text("UPDATE notice_image SET seq = 3 - seq WHERE notice_id = 1")
        )
        order = (
            (
                await connection.execute(
                    text(
                        "SELECT image_id FROM notice_image "
                        "WHERE notice_id = 1 ORDER BY seq"
                    )
                )
            )
            .scalars()
            .all()
        )

    assert order == [second, first]


async def test_deleting_a_notice_removes_its_links(database) -> None:
    async with database.engine.begin() as connection:
        first, _ = await _notice_with_images(connection, 2)
        await _link(connection, first, 1)

    async with database.engine.begin() as connection:
        await connection.execute(text("DELETE FROM notice WHERE id = 1"))
        remaining = await connection.scalar(text("SELECT count(*) FROM notice_image"))
        images = await connection.scalar(text("SELECT count(*) FROM image"))

    assert remaining == 0
    # 링크만 사라지고 image 행은 남는다. DETACHED 전이는 서비스 계층이 한다.
    assert images == 2
