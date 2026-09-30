"""동시 요청이 `seq` 연속성과 live 1건 규칙을 깨지 않는다.

요청마다 별도 transaction이 열리므로 `asyncio.gather`로 실제 경합을 만든다.
"""

import asyncio

from sqlalchemy import func, select

from quinquatria_persistence.models import Performance

from ._support import DAY_ONE, DAY_TWO, body, create, order_of


async def _consistent_order(api, database, date: str) -> list[int]:
    """DB와 목록 API가 같은 순서를 보이고 `seq`가 1부터 이어지는지 본다."""
    stored = await order_of(database, date)
    listed = (
        await api.get("/api/v1/performances", params={"date": date, "size": 100})
    ).json()["items"]
    assert [(item["id"], item["seq"]) for item in listed] == stored
    assert [seq for _, seq in stored] == list(range(1, len(stored) + 1))
    return [pid for pid, _ in stored]


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


async def test_concurrent_reorders_apply_one_whole_order(api, database) -> None:
    ids = [(await create(api, f"공연 {index}"))["id"] for index in range(6)]
    orders = [list(reversed(ids)), ids[1::2] + ids[::2]]

    responses = await asyncio.gather(
        *(
            api.put(
                "/api/v1/performances/reorder",
                json={"date": DAY_ONE, "order": order},
            )
            for order in orders
        )
    )

    assert [response.status_code for response in responses] == [204] * 2
    final = await order_of(database, DAY_ONE)
    assert [pid for pid, _ in final] in orders
    assert [seq for _, seq in final] == [1, 2, 3, 4, 5, 6]


async def test_concurrent_create_and_delete_on_one_date(api, database) -> None:
    a, b, c = [(await create(api, name))["id"] for name in "abc"]

    created, deleted = await asyncio.gather(
        api.post("/api/v1/performances", json=body("d")),
        api.delete(f"/api/v1/performances/{b}"),
    )

    assert (created.status_code, deleted.status_code) == (201, 204)
    # 어느 쪽이 먼저든 b가 빠지고 d가 끝에 붙는다.
    d = created.json()["id"]
    assert await _consistent_order(api, database, DAY_ONE) == [a, c, d]


async def test_concurrent_date_moves_with_create_and_delete(api, database) -> None:
    a, b, c = [(await create(api, name))["id"] for name in "abc"]
    x = (await create(api, "x", date=DAY_TWO))["id"]

    moved_a, moved_x, created, deleted = await asyncio.gather(
        api.patch(f"/api/v1/performances/{a}", json={"date": DAY_TWO}),
        api.patch(f"/api/v1/performances/{x}", json={"date": DAY_ONE}),
        api.post("/api/v1/performances", json=body("n", date=DAY_TWO)),
        api.delete(f"/api/v1/performances/{b}"),
    )

    assert [
        response.status_code for response in (moved_a, moved_x, created, deleted)
    ] == [200, 200, 201, 204]
    # 옮겨 온 공연과 새 공연은 처리 순서대로 끝에 붙으므로 그 둘의 순서만 열려 있다.
    n = created.json()["id"]
    assert await _consistent_order(api, database, DAY_ONE) == [c, x]
    assert await _consistent_order(api, database, DAY_TWO) in ([a, n], [n, a])
    for response in (moved_a, moved_x):
        fetched = await api.get(f"/api/v1/performances/{response.json()['id']}")
        assert fetched.json()["date"] == response.json()["date"]


async def test_concurrent_patch_and_delete_of_one_performance(api, database) -> None:
    a, b, c = [(await create(api, name))["id"] for name in "abc"]

    patched, deleted = await asyncio.gather(
        api.patch(
            f"/api/v1/performances/{b}", json={"type": "STUDENT", "date": DAY_TWO}
        ),
        api.delete(f"/api/v1/performances/{b}"),
    )

    # PATCH가 먼저면 200 뒤 삭제되고, DELETE가 먼저면 PATCH가 공연을 찾지 못한다.
    assert deleted.status_code == 204
    assert patched.status_code in (200, 404)
    if patched.status_code == 404:
        assert patched.json()["code"] == "RESOURCE_NOT_FOUND"
    assert (await api.get(f"/api/v1/performances/{b}")).status_code == 404
    assert await _consistent_order(api, database, DAY_ONE) == [a, c]
    assert await _consistent_order(api, database, DAY_TWO) == []
