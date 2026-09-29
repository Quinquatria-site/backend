"""공연 삭제와 남은 공연의 재번호 (명세 §6)."""

from ._support import DAY_ONE, DAY_TWO, create, order_of


async def test_delete_renumbers_the_remaining_performances_of_that_date(
    api, database
) -> None:
    a = await create(api, "a")
    b = await create(api, "b")
    c = await create(api, "c")
    x = await create(api, "x", date=DAY_TWO)

    response = await api.delete(f"/api/v1/performances/{a['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers
    assert await order_of(database, DAY_ONE) == [(b["id"], 1), (c["id"], 2)]
    assert await order_of(database, DAY_TWO) == [(x["id"], 1)]
    missing = await api.get(f"/api/v1/performances/{a['id']}")
    assert missing.status_code == 404


async def test_delete_cascades_translations(api) -> None:
    created = await create(
        api,
        translations=[
            {"language_code": "KO", "title": "공연"},
            {"language_code": "EN", "title": "Show"},
        ],
    )

    await api.delete(f"/api/v1/performances/{created['id']}")

    page = (await api.get("/api/v1/performances")).json()
    assert page["total"] == 0


async def test_delete_unknown_id_is_not_found(api) -> None:
    response = await api.delete("/api/v1/performances/999")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
