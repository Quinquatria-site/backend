"""요청 하나의 변경은 한꺼번에 반영되거나 한꺼번에 취소된다 (명세 §5.2, §5.6)."""

from ._support import DAY_ONE, DAY_TWO, create, order_of


async def test_failed_patch_rolls_back_the_date_move_and_renumbering(
    api, database
) -> None:
    a = await create(api, "a")
    b = await create(api, "b")

    response = await api.patch(
        f"/api/v1/performances/{a['id']}",
        json={
            "date": DAY_TWO,
            "image_uri": "images/performance/missing.webp",
            "translations": [{"language_code": "EN", "title": "A"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_IMAGE"
    assert await order_of(database, DAY_ONE) == [(a["id"], 1), (b["id"], 2)]
    assert await order_of(database, DAY_TWO) == []
    fetched = (await api.get(f"/api/v1/performances/{a['id']}")).json()
    assert fetched == a


async def test_failed_create_leaves_nothing_behind(api, database) -> None:
    response = await api.post(
        "/api/v1/performances",
        json={
            "type": "ARTIST",
            "date": DAY_ONE,
            "image_uri": "images/performance/missing.webp",
            "translations": [{"language_code": "KO", "title": "공연"}],
        },
    )

    assert response.status_code == 422
    assert (await api.get("/api/v1/performances")).json()["total"] == 0
    assert (await create(api))["seq"] == 1
