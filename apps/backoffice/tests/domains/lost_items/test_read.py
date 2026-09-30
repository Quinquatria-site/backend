"""`GET /api/v1/lost-items`와 단건 조회 (명세 §2.5, §5.1)."""

from datetime import UTC, datetime, timedelta

import pytest

from backoffice.crud.resources import POSTGRESQL_INTEGER_MAX

from ._support import URL, body, ko, seed_image, seed_lost_item

T0 = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


async def _ids(api, **params) -> list[int]:
    response = await api.get(URL, params=params)
    assert response.status_code == 200
    return [item["id"] for item in response.json()["items"]]


async def test_list_sorts_newest_first_with_id_tie_break(database, api) -> None:
    older = await seed_lost_item(database, created_at=T0)
    tied_low = await seed_lost_item(database, created_at=T0 + timedelta(hours=1))
    tied_high = await seed_lost_item(database, created_at=T0 + timedelta(hours=1))
    newest = await seed_lost_item(database, created_at=T0 + timedelta(hours=2))

    assert await _ids(api) == [newest, tied_high, tied_low, older]


@pytest.mark.parametrize("value", ["true", "false"])
async def test_list_filters_by_is_returned(database, api, value) -> None:
    returned = await seed_lost_item(database, created_at=T0, is_returned=True)
    kept = await seed_lost_item(database, created_at=T0, is_returned=False)

    response = await api.get(URL, params={"is_returned": value})

    expected = [returned] if value == "true" else [kept]
    assert [item["id"] for item in response.json()["items"]] == expected
    assert response.json()["total"] == 1


async def test_list_paginates_after_filter(database, api) -> None:
    ids = [
        await seed_lost_item(database, created_at=T0 + timedelta(minutes=n))
        for n in range(5)
    ]
    await seed_lost_item(database, created_at=T0, is_returned=True)

    response = await api.get(URL, params={"is_returned": "false", "page": 2, "size": 2})

    page = response.json()
    assert [item["id"] for item in page["items"]] == [ids[2], ids[1]]
    assert (page["page"], page["size"], page["total"]) == (2, 2, 5)


async def test_list_past_last_page_is_empty(database, api) -> None:
    await seed_lost_item(database, created_at=T0)

    page = (await api.get(URL, params={"page": 3})).json()

    assert page == {"items": [], "page": 3, "size": 20, "total": 1}


async def test_list_returns_all_translations_and_image(
    api, database, object_store
) -> None:
    key = await seed_image(database, object_store, "listed")
    created = (
        await api.post(
            URL,
            json=body(
                image_url=key,
                translations=[
                    {"language_code": "EN", "title": "Wallet"},
                    ko(),
                    {"language_code": "CHN", "title": "钱包"},
                ],
            ),
        )
    ).json()

    listed = (await api.get(URL)).json()["items"]

    assert listed == [created]
    assert [t["language_code"] for t in created["translations"]] == [
        "CHN",
        "EN",
        "KO",
    ]
    assert created["image_url"] == key


@pytest.mark.parametrize(
    "params",
    [
        {"is_returned": "maybe"},
        {"language_code": "KO"},
        {"size": 101},
        {"page": 0},
    ],
    ids=["bad-bool", "unknown-param", "size-too-large", "page-zero"],
)
async def test_list_rejects_invalid_query(api, params) -> None:
    response = await api.get(URL, params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_get_rejects_query_parameters(api) -> None:
    created = (await api.post(URL, json=body())).json()

    response = await api.get(f"{URL}/{created['id']}", params={"language_code": "KO"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("lost_item_id", [999, POSTGRESQL_INTEGER_MAX + 1])
async def test_get_missing_is_not_found(api, lost_item_id) -> None:
    response = await api.get(f"{URL}/{lost_item_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


async def test_get_non_positive_id_is_validation_error(api) -> None:
    response = await api.get(f"{URL}/0")

    assert response.status_code == 422


async def test_requires_token(api) -> None:
    response = await api.get(URL, headers={"Authorization": ""})

    assert response.status_code == 401
