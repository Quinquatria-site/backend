"""DB 세션을 mock해 API 명세 §3.2, §3.3의 HTTP·SQL 계약을 검증한다."""

from datetime import UTC, datetime, timedelta

import pytest

from quinquatria_persistence import CategoryCode, LanguageCode

START = datetime(2026, 10, 6, 1, tzinfo=UTC)


def _category_row(resource_id, code="PUB", language="KO", icon=None):
    return {
        "id": resource_id,
        "code": CategoryCode(code),
        "category_icon_uri": icon,
        "language_code": LanguageCode(language),
        "name": f"category-{resource_id}-{language}",
    }


def _place_row(
    resource_id,
    *,
    language="KO",
    category_id=10,
    sequence=1,
    images=None,
):
    return {
        "id": resource_id,
        "category_id": category_id,
        "category_sequence": sequence,
        "x": 127.42,
        "y": 36.18,
        "start_hour": START,
        "end_hour": START + timedelta(hours=12),
        "place_image_uri": images,
        "language_code": LanguageCode(language),
        "name": f"place-{resource_id}-{language}",
        "host_college": f"college-{language}",
        "description": "",
    }


def _menu_row(resource_id, *, language="KO", image=None):
    return {
        "id": resource_id,
        "place_id": 40,
        "image_url": image,
        "price": 0 if resource_id == 100 else 5000,
        "language_code": LanguageCode(language),
        "name": f"menu-{resource_id}-{language}",
        "description": "",
    }


def test_categories_default_language_and_complete_response(
    customer_client, mock_session, execute_result
):
    rows = [
        _category_row(10),
        _category_row(20, code="BOOTH", icon="images/category/icon.webp"),
        _category_row(30, code="FOODTRUCK"),
    ]
    mock_session.scalar.return_value = len(rows)
    mock_session.execute.return_value = execute_result(*rows)

    response = customer_client.get("/api/v1/categories")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "items": [
            {
                "id": 10,
                "code": "PUB",
                "category_icon_uri": None,
                "language_code": "KO",
                "name": "category-10-KO",
            },
            {
                "id": 20,
                "code": "BOOTH",
                "category_icon_uri": "images/category/icon.webp",
                "language_code": "KO",
                "name": "category-20-KO",
            },
            {
                "id": 30,
                "code": "FOODTRUCK",
                "category_icon_uri": None,
                "language_code": "KO",
                "name": "category-30-KO",
            },
        ],
        "page": 1,
        "size": 20,
        "total": 3,
    }


@pytest.mark.parametrize("language,ids", [("EN", [10, 20, 40]), ("CHN", [20])])
def test_categories_return_mocked_requested_translation(
    customer_client, mock_session, execute_result, language, ids
):
    rows = [_category_row(resource_id, language=language) for resource_id in ids]
    mock_session.scalar.return_value = len(rows)
    mock_session.execute.return_value = execute_result(*rows)

    response = customer_client.get(
        "/api/v1/categories", params={"language_code": language}
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ids
    assert response.json()["total"] == len(ids)
    assert all(item["language_code"] == language for item in response.json()["items"])


@pytest.mark.parametrize(
    "params,rows",
    [
        ({}, [_place_row(30), _place_row(40), _place_row(50), _place_row(60)]),
        (
            {"language_code": "EN"},
            [
                _place_row(40, language="EN"),
                _place_row(50, language="EN"),
                _place_row(60, language="EN"),
                _place_row(20, language="EN", category_id=30),
            ],
        ),
        ({"language_code": "CHN"}, [_place_row(40, language="CHN")]),
    ],
)
def test_places_serialize_rows_in_query_order(
    customer_client, mock_session, execute_result, params, rows
):
    mock_session.scalar.return_value = len(rows)
    mock_session.execute.return_value = execute_result(*rows)

    response = customer_client.get("/api/v1/places", params=params)

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [row["id"] for row in rows]
    assert body["total"] == len(rows)
    assert all(
        item["language_code"] == params.get("language_code", "KO")
        for item in body["items"]
    )
    assert all(
        "menus" not in item and "translations" not in item for item in body["items"]
    )


def test_categories_query_filters_translation_before_count_and_pagination(
    customer_client, mock_session, execute_result, compiled_sql
):
    mock_session.scalar.return_value = 3
    mock_session.execute.return_value = execute_result(_category_row(40, language="EN"))

    response = customer_client.get(
        "/api/v1/categories", params={"language_code": "EN", "page": 2, "size": 2}
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == 40
    count_sql = compiled_sql(mock_session.scalar.await_args.args[0])
    page_sql = compiled_sql(mock_session.execute.await_args.args[0])
    for sql in (count_sql, page_sql):
        assert (
            "JOIN category_translation ON "
            "category_translation.category_id = category.id"
        ) in sql
        assert "category_translation.language_code = 'EN'" in sql
    assert "ORDER BY" not in count_sql
    assert "LIMIT" not in count_sql
    assert "OFFSET" not in count_sql
    assert "ORDER BY category.id" in page_sql
    assert "LIMIT 2 OFFSET 2" in page_sql


def test_places_query_applies_filters_before_count_and_page(
    customer_client, mock_session, execute_result, compiled_sql
):
    mock_session.scalar.return_value = 2
    mock_session.execute.return_value = execute_result(
        _place_row(50, language="EN", sequence=2)
    )

    response = customer_client.get(
        "/api/v1/places",
        params={"category_id": 10, "language_code": "EN", "page": 2, "size": 1},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == 50
    count_sql = compiled_sql(mock_session.scalar.await_args.args[0])
    page_sql = compiled_sql(mock_session.execute.await_args.args[0])
    for sql in (count_sql, page_sql):
        assert "JOIN place_translation ON place_translation.place_id = place.id" in sql
        assert "place_translation.language_code = 'EN'" in sql
        assert "place.category_id = 10" in sql
    assert "ORDER BY" not in count_sql
    assert "LIMIT" not in count_sql
    assert "OFFSET" not in count_sql
    assert "ORDER BY place.category_id, place.category_sequence, place.id" in page_sql
    assert "LIMIT 1 OFFSET 1" in page_sql


@pytest.mark.parametrize("category_id", [40, 999, 2_147_483_648, 10**50])
def test_empty_or_unstorable_category_filter_returns_empty_page(
    customer_client, mock_session, category_id
):
    if category_id <= 2_147_483_647:
        mock_session.scalar.return_value = 0

    response = customer_client.get(
        "/api/v1/places", params={"category_id": category_id}
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "size": 20, "total": 0}
    mock_session.execute.assert_not_awaited()
    if category_id > 2_147_483_647:
        mock_session.scalar.assert_not_awaited()


@pytest.mark.parametrize("path,total", [("categories", 3), ("places", 4)])
@pytest.mark.parametrize("page", [2, 10**50])
def test_page_beyond_end_preserves_total_without_data_query(
    customer_client, mock_session, path, total, page
):
    mock_session.scalar.return_value = total

    response = customer_client.get(f"/api/v1/{path}", params={"page": page})

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": page, "size": 20, "total": total}
    mock_session.execute.assert_not_awaited()


@pytest.mark.parametrize("path", ["categories", "places"])
def test_empty_result_returns_empty_page(customer_client, mock_session, path):
    mock_session.scalar.return_value = 0

    response = customer_client.get(f"/api/v1/{path}")

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "size": 20, "total": 0}
    mock_session.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "language,ids", [(None, [100, 200, 300]), ("EN", [100, 300, 400]), ("CHN", [])]
)
def test_detail_serializes_mocked_menus_in_query_order(
    customer_client, mock_session, execute_result, language, ids
):
    selected_language = language or "KO"
    mock_session.execute.side_effect = [
        execute_result(_place_row(40, language=selected_language)),
        execute_result(
            *[_menu_row(resource_id, language=selected_language) for resource_id in ids]
        ),
    ]
    params = {} if language is None else {"language_code": language}

    response = customer_client.get("/api/v1/places/40", params=params)

    assert response.status_code == 200
    body = response.json()
    assert body["language_code"] == selected_language
    assert body["name"] == f"place-40-{selected_language}"
    assert [menu["id"] for menu in body["menus"]] == ids
    assert all(menu["language_code"] == selected_language for menu in body["menus"])


def test_detail_returns_exact_place_and_menu_fields(
    customer_client, mock_session, execute_result
):
    mock_session.execute.side_effect = [
        execute_result(_place_row(40, language="EN")),
        execute_result(
            _menu_row(100, language="EN"),
            _menu_row(300, language="EN", image="images/menu/item.webp"),
        ),
    ]

    body = customer_client.get(
        "/api/v1/places/40", params={"language_code": "EN"}
    ).json()

    assert set(body) == {
        "id",
        "category_id",
        "category_sequence",
        "x",
        "y",
        "start_hour",
        "end_hour",
        "place_image_uri",
        "language_code",
        "name",
        "host_college",
        "description",
        "menus",
    }
    assert (body["id"], body["category_id"], body["category_sequence"]) == (40, 10, 1)
    assert (body["x"], body["y"]) == (127.42, 36.18)
    assert (body["name"], body["host_college"], body["description"]) == (
        "place-40-EN",
        "college-EN",
        "",
    )
    assert body["place_image_uri"] is None
    assert datetime.fromisoformat(body["start_hour"]) == START
    assert datetime.fromisoformat(body["end_hour"]) == START + timedelta(hours=12)
    assert body["menus"][0] == {
        "id": 100,
        "place_id": 40,
        "image_url": None,
        "price": 0,
        "language_code": "EN",
        "name": "menu-100-EN",
        "description": "",
    }
    assert body["menus"][1]["image_url"] == "images/menu/item.webp"


def test_place_images_preserve_key_order_and_list_detail_parity(
    customer_client, mock_session, execute_result
):
    place = _place_row(
        50,
        sequence=2,
        images=["images/place/second.webp", "images/place/first.webp"],
    )
    mock_session.execute.side_effect = [execute_result(place), execute_result()]
    detail = customer_client.get("/api/v1/places/50").json()

    mock_session.reset_mock()
    mock_session.scalar.return_value = 1
    mock_session.execute.side_effect = None
    mock_session.execute.return_value = execute_result(place)
    listed = customer_client.get("/api/v1/places").json()["items"][0]

    assert detail.pop("menus") == []
    assert detail == listed
    assert detail["place_image_uri"] == [
        "images/place/second.webp",
        "images/place/first.webp",
    ]


def test_detail_builds_left_join_and_ordered_menu_query(
    customer_client, mock_session, execute_result, compiled_sql
):
    mock_session.execute.side_effect = [
        execute_result(_place_row(40, language="EN")),
        execute_result(_menu_row(100, language="EN")),
    ]

    response = customer_client.get("/api/v1/places/40", params={"language_code": "EN"})

    assert response.status_code == 200
    place_sql = compiled_sql(mock_session.execute.await_args_list[0].args[0])
    menu_sql = compiled_sql(mock_session.execute.await_args_list[1].args[0])
    place_join, place_where = place_sql.split(" WHERE ", maxsplit=1)
    assert (
        "LEFT OUTER JOIN place_translation ON place_translation.place_id = place.id"
    ) in place_join
    assert "place_translation.language_code = 'EN'" in place_join
    assert "place_translation.language_code" not in place_where
    assert place_where == "place.id = 40"
    assert "JOIN menu_translation ON menu_translation.menu_id = menu.id" in menu_sql
    assert "menu_translation.language_code = 'EN'" in menu_sql
    assert "menu.place_id = 40" in menu_sql
    assert "ORDER BY menu.id" in menu_sql


@pytest.mark.parametrize(
    "place_id,language,code",
    [
        (999, "KO", "RESOURCE_NOT_FOUND"),
        (999, "EN", "RESOURCE_NOT_FOUND"),
        (2_147_483_648, "KO", "RESOURCE_NOT_FOUND"),
        (10**50, "KO", "RESOURCE_NOT_FOUND"),
        (30, "EN", "TRANSLATION_NOT_FOUND"),
        (70, "KO", "TRANSLATION_NOT_FOUND"),
    ],
)
def test_detail_distinguishes_absence_from_missing_translation(
    customer_client, mock_session, execute_result, place_id, language, code
):
    if place_id <= 2_147_483_647:
        result = (
            execute_result()
            if code == "RESOURCE_NOT_FOUND"
            else execute_result({"language_code": None})
        )
        mock_session.execute.return_value = result

    response = customer_client.get(
        f"/api/v1/places/{place_id}", params={"language_code": language}
    )

    assert response.status_code == 404
    assert response.json() == {
        "code": code,
        "message": "요청한 리소스를 찾을 수 없습니다."
        if code == "RESOURCE_NOT_FOUND"
        else "요청한 언어의 번역이 없습니다.",
        "details": [],
    }
    if place_id > 2_147_483_647:
        mock_session.execute.assert_not_awaited()


@pytest.mark.parametrize("path", ["categories", "places", "places/40"])
@pytest.mark.parametrize(
    "params,field",
    [
        ({"language_code": "ko"}, "language_code"),
        ({"language_code": "JP"}, "language_code"),
        ({"unknown": "1"}, "unknown"),
    ],
)
def test_invalid_language_and_unknown_query(customer_client, path, params, field):
    response = customer_client.get(f"/api/v1/{path}", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["details"][0]["field"] == field


@pytest.mark.parametrize(
    "path,params,field",
    [
        ("categories", {"category_id": 10}, "category_id"),
        ("categories", {"code": "PUB"}, "code"),
        ("categories", {"page": 0}, "page"),
        ("categories", {"size": 101}, "size"),
        ("places", {"type": "PUB"}, "type"),
        ("places", {"category_id": 0}, "category_id"),
        ("places", {"category_id": -1}, "category_id"),
        ("places", {"category_id": "1.5"}, "category_id"),
        ("places", {"page": "x"}, "page"),
        ("places", {"size": 0}, "size"),
        ("places/40", {"page": 1}, "page"),
        ("places/40", {"size": 20}, "size"),
        ("places/40", {"category_id": 10}, "category_id"),
        ("places/0", {}, "place_id"),
        ("places/-1", {}, "place_id"),
        ("places/1.5", {}, "place_id"),
        ("places/abc", {}, "place_id"),
    ],
)
def test_endpoint_specific_validation(customer_client, path, params, field):
    response = customer_client.get(f"/api/v1/{path}", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["details"][0]["field"] == field


def test_openapi_describes_query_and_response_contracts(customer_client):
    paths = customer_client.get("/openapi.json").json()["paths"]
    expected_queries = {
        "/api/v1/categories": {"language_code", "page", "size"},
        "/api/v1/places": {"language_code", "category_id", "page", "size"},
        "/api/v1/places/{place_id}": {"language_code"},
    }
    for path, expected in expected_queries.items():
        operation = paths[path]["get"]
        assert {
            param["name"] for param in operation["parameters"] if param["in"] == "query"
        } == expected
        assert operation["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/ErrorResponse")
    detail = paths["/api/v1/places/{place_id}"]["get"]
    assert detail["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/PlaceDetailResponse")
    assert detail["responses"]["404"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorResponse")
    assert {"/api/v1/", *expected_queries}.issubset(paths)
