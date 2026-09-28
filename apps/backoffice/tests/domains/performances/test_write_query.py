"""쓰기 라우트도 명세에 없는 query를 거부한다 (`common/query.py`).

거부는 변경보다 먼저 일어나야 하므로 응답 뒤 상태가 그대로인지도 본다.
"""

import pytest

from ._support import DAY_ONE, body, create, order_of

UNKNOWN = {"page": "1"}


async def test_create_rejects_unknown_query(api) -> None:
    response = await api.post(
        "/api/v1/performances", json=body(), params={"language_code": "EN"}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert (await api.get("/api/v1/performances")).json()["total"] == 0


@pytest.mark.parametrize(
    ("method", "suffix", "payload"),
    [
        ("PATCH", "", {"type": "STUDENT"}),
        ("PUT", "/live", {"is_live": True}),
        ("DELETE", "", None),
        ("DELETE", "/translations/EN", None),
    ],
    ids=["patch", "live", "delete", "delete-translation"],
)
async def test_id_routes_reject_unknown_query(api, method, suffix, payload) -> None:
    created = await create(
        api,
        translations=[
            {"language_code": "KO", "title": "공연"},
            {"language_code": "EN", "title": "Show"},
        ],
    )

    response = await api.request(
        method,
        f"/api/v1/performances/{created['id']}{suffix}",
        json=payload,
        params=UNKNOWN,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    fetched = await api.get(f"/api/v1/performances/{created['id']}")
    assert fetched.json() == created


async def test_reorder_rejects_unknown_query(api, database) -> None:
    a = await create(api, "a")
    b = await create(api, "b")

    response = await api.put(
        "/api/v1/performances/reorder",
        json={"date": DAY_ONE, "order": [b["id"], a["id"]]},
        params=UNKNOWN,
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert await order_of(database, DAY_ONE) == [(a["id"], 1), (b["id"], 2)]
