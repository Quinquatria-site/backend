"""기본 리소스 단건 조회와 목록 페이지네이션."""

import pytest
from sqlalchemy import select

from backoffice.crud.resources import POSTGRESQL_INTEGER_MAX, get_or_404, paginate
from common.errors import ApiError, ErrorCode
from common.query import PageQuery
from quinquatria_persistence.enums import NoticeType
from quinquatria_persistence.models import Notice


async def _seed(database, count: int) -> list[int]:
    async with database.transaction() as session:
        notices = [Notice(type=NoticeType.GENERAL) for _ in range(count)]
        session.add_all(notices)
        await session.flush()
        return [notice.id for notice in notices]


async def _ids(rows) -> list[int]:
    return [row.id for row in rows]


async def test_paginate_counts_filtered_rows_and_slices(database) -> None:
    ids = await _seed(database, 5)

    async with database.session() as session:
        page = await paginate(
            session,
            select(Notice).order_by(Notice.id),
            PageQuery(page=2, size=2),
            _ids,
        )

    assert page.items == ids[2:4]
    assert (page.page, page.size, page.total) == (2, 2, 5)


async def test_paginate_past_last_page_keeps_total(database) -> None:
    await _seed(database, 3)

    async with database.session() as session:
        page = await paginate(
            session, select(Notice).order_by(Notice.id), PageQuery(page=9, size=2), _ids
        )

    assert page.items == []
    assert page.total == 3


@pytest.mark.parametrize(
    "resource_id", [999, POSTGRESQL_INTEGER_MAX + 1], ids=["missing", "out-of-range"]
)
async def test_get_or_404(database, resource_id) -> None:
    async with database.session() as session:
        with pytest.raises(ApiError) as caught:
            await get_or_404(session, Notice, resource_id)

    assert caught.value.code is ErrorCode.RESOURCE_NOT_FOUND
