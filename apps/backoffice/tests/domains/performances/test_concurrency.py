"""동시 요청이 `seq` 연속성과 live 1건 규칙을 깨지 않는다.

요청마다 별도 transaction이 열리므로 `asyncio.gather`로 실제 경합을 만든다.
"""

import asyncio

from sqlalchemy import func, select

from quinquatria_persistence.models import Performance

from ._support import DAY_ONE, body, create, order_of


async def test_concurrent_creates_on_one_date_get_consecutive_seq(
    api, database
) -> None:
    responses = await asyncio.gather(
        *(
            api.post("/api/v1/performances", json=body(f"공연 {index}"))
            for index in range(6)
        )
    )

    assert [response.status_code for response in responses] == [201] * 6
    assert [seq for _, seq in await order_of(database, DAY_ONE)] == [1, 2, 3, 4, 5, 6]


async def test_concurrent_live_requests_leave_at_most_one_live(api, database) -> None:
    ids = [(await create(api, f"공연 {index}"))["id"] for index in range(6)]

    responses = await asyncio.gather(
        *(
            api.put(f"/api/v1/performances/{pid}/live", json={"is_live": True})
            for pid in ids
        )
    )

    assert [response.status_code for response in responses] == [200] * 6
    async with database.session() as session:
        live = await session.scalar(
            select(func.count()).select_from(Performance).where(Performance.is_live)
        )
    assert live == 1
