"""공연 목록의 필터, 정렬, 페이지네이션 (명세 §2.5, §5.1)."""

import pytest

from ._support import DAY_ONE, DAY_TWO, create


async def _seed(api) -> dict[str, int]:
    ids = {}
    ids["day2-a"] = (await create(api, "day2-a", date=DAY_TWO))["id"]
    ids["day1-a"] = (await create(api, "day1-a", type="STUDENT"))["id"]
    ids["day1-b"] = (await create(api, "day1-b"))["id"]
    ids["day2-b"] = (await create(api, "day2-b", date=DAY_TWO, type="STUDENT"))["id"]
    return ids


def _titles(page: dict) -> list[str]:
    return [item["translations"][0]["title"] for item in page["items"]]


async def test_list_sorts_by_date_then_seq(api) -> None:
    await _seed(api)

    response = await api.get("/api/v1/performances")

    assert response.status_code == 200
    page = response.json()
    assert _titles(page) == ["day1-a", "day1-b", "day2-a", "day2-b"]
    assert (page["page"], page["size"], page["total"]) == (1, 20, 4)
    assert [item["seq"] for item in page["items"]] == [1, 2, 1, 2]


async def test_list_returns_every_translation(api) -> None:
    await create(
        api,
        translations=[
            {"language_code": "KO", "title": "공연"},
            {"language_code": "CHN", "title": "演出"},
        ],
    )

    item = (await api.get("/api/v1/performances")).json()["items"][0]

    assert [t["language_code"] for t in item["translations"]] == ["CHN", "KO"]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"type": "STUDENT"}, ["day1-a", "day2-b"]),
        ({"date": DAY_TWO}, ["day2-a", "day2-b"]),
        ({"type": "ARTIST", "date": DAY_ONE}, ["day1-b"]),
        ({"date": "2026-10-08"}, []),
    ],
)
async def test_list_filters(api, params, expected) -> None:
    await _seed(api)

    page = (await api.get("/api/v1/performances", params=params)).json()

    assert _titles(page) == expected
    assert page["total"] == len(expected)


async def test_list_paginates(api) -> None:
    await _seed(api)

    second = (
        await api.get("/api/v1/performances", params={"size": 3, "page": 2})
    ).json()
    beyond = (
        await api.get("/api/v1/performances", params={"size": 3, "page": 3})
    ).json()

    assert _titles(second) == ["day2-b"]
    assert second["total"] == 4
    assert beyond["items"] == [] and beyond["total"] == 4


@pytest.mark.parametrize(
    "params",
    [
        {"type": "artist"},
        {"date": "2026-10-06T00:00:00"},
        {"date": "20261006"},
        {"size": 101},
        {"page": 0},
        {"language_code": "KO"},
    ],
)
async def test_list_rejects_invalid_query(api, params) -> None:
    response = await api.get("/api/v1/performances", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
