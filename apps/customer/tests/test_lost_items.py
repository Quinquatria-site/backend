"""DB 경계 mock으로 API 명세 §3.6의 분실물 조회 계약을 검증한다."""

from datetime import datetime, timedelta, timezone

import pytest

KST = timezone(timedelta(hours=9))
BASE_TIME = datetime(2026, 10, 6, 10, tzinfo=KST)


def _lost_item_row(
    resource_id: int,
    language: str | None,
    *,
    hours: int = 0,
    is_returned: bool = False,
    image_url: str | None = None,
    empty_text: bool = False,
):
    return {
        "id": resource_id,
        "image_url": image_url,
        "is_returned": is_returned,
        "created_at": BASE_TIME + timedelta(hours=hours),
        "language_code": language,
        "title": None if language is None else f"lost-item-{resource_id}-{language}",
        "description": ""
        if empty_text
        else None
        if language is None
        else f"description-{resource_id}-{language}",
        "found_location": ""
        if empty_text
        else None
        if language is None
        else f"location-{resource_id}-{language}",
    }


def _set_page(mock_session, execute_result, total, *rows):
    mock_session.scalar.return_value = total
    mock_session.execute.return_value = execute_result(*rows)


def _assert_unpaginated_count(sql: str):
    assert "ORDER BY" not in sql
    assert "LIMIT" not in sql
    assert "OFFSET" not in sql


def test_list_defaults_to_korean_and_serializes_nullable_and_empty_fields(
    customer_client, mock_session, execute_result, compiled_sql
):
    rows = (
        _lost_item_row(
            50,
            "KO",
            hours=2,
            is_returned=True,
            image_url="images/lost-item/wallet.webp",
        ),
        _lost_item_row(40, "KO", hours=2, empty_text=True),
        _lost_item_row(30, "KO", hours=1, is_returned=True),
    )
    _set_page(mock_session, execute_result, 3, *rows)

    response = customer_client.get("/api/v1/lost-items")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert (body["page"], body["size"], body["total"]) == (1, 20, 3)
    assert [item["id"] for item in body["items"]] == [50, 40, 30]
    assert body["items"][0] == {
        "id": 50,
        "image_url": "images/lost-item/wallet.webp",
        "is_returned": True,
        "created_at": body["items"][0]["created_at"],
        "language_code": "KO",
        "title": "lost-item-50-KO",
        "description": "description-50-KO",
        "found_location": "location-50-KO",
    }
    assert datetime.fromisoformat(
        body["items"][0]["created_at"]
    ) == BASE_TIME + timedelta(hours=2)
    assert body["items"][1]["image_url"] is None
    assert body["items"][1]["description"] == ""
    assert body["items"][1]["found_location"] == ""

    count_sql = compiled_sql(mock_session.scalar.await_args.args[0])
    page_sql = compiled_sql(mock_session.execute.await_args.args[0])
    for sql in (count_sql, page_sql):
        assert (
            "JOIN lost_item_translation ON "
            "lost_item_translation.lost_item_id = lost_item.id" in sql
        )
        assert "lost_item_translation.language_code = 'KO'" in sql
        assert "lost_item.is_returned =" not in sql
    _assert_unpaginated_count(count_sql)
    assert "ORDER BY lost_item.created_at DESC, lost_item.id DESC" in page_sql
    assert "LIMIT 20 OFFSET 0" in page_sql


@pytest.mark.parametrize(
    ("language", "row"),
    [
        ("KO", _lost_item_row(30, "KO", hours=1, is_returned=True)),
        ("EN", _lost_item_row(60, "EN", hours=3)),
        ("CHN", _lost_item_row(50, "CHN", hours=2, is_returned=True)),
    ],
)
def test_list_uses_each_requested_language_without_fallback(
    customer_client,
    mock_session,
    execute_result,
    compiled_sql,
    language,
    row,
):
    _set_page(mock_session, execute_result, 1, row)

    response = customer_client.get(
        "/api/v1/lost-items", params={"language_code": language}
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["language_code"] == language
    count_sql = compiled_sql(mock_session.scalar.await_args.args[0])
    assert "JOIN lost_item_translation" in count_sql
    assert f"lost_item_translation.language_code = '{language}'" in count_sql
    _assert_unpaginated_count(count_sql)


@pytest.mark.parametrize("is_returned", [True, False])
def test_list_applies_each_returned_filter_in_count_and_page_queries(
    customer_client,
    mock_session,
    execute_result,
    compiled_sql,
    is_returned,
):
    row = _lost_item_row(50, "KO", hours=2, is_returned=is_returned)
    _set_page(mock_session, execute_result, 1, row)

    response = customer_client.get(
        "/api/v1/lost-items", params={"is_returned": is_returned}
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["is_returned"] is is_returned
    expected = f"lost_item.is_returned = {str(is_returned).lower()}"
    count_sql = compiled_sql(mock_session.scalar.await_args.args[0])
    page_sql = compiled_sql(mock_session.execute.await_args.args[0])
    assert expected in count_sql
    assert expected in page_sql
    _assert_unpaginated_count(count_sql)


def test_list_counts_language_and_returned_filter_before_pagination(
    customer_client, mock_session, execute_result, compiled_sql
):
    _set_page(
        mock_session,
        execute_result,
        3,
        _lost_item_row(40, "EN", hours=2),
    )

    response = customer_client.get(
        "/api/v1/lost-items",
        params={
            "language_code": "EN",
            "is_returned": False,
            "page": 2,
            "size": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["id"] == 40
    assert (body["page"], body["size"], body["total"]) == (2, 1, 3)

    count_sql = compiled_sql(mock_session.scalar.await_args.args[0])
    page_sql = compiled_sql(mock_session.execute.await_args.args[0])
    for sql in (count_sql, page_sql):
        assert "lost_item_translation.language_code = 'EN'" in sql
        assert "lost_item.is_returned = false" in sql
    _assert_unpaginated_count(count_sql)
    assert "ORDER BY lost_item.created_at DESC, lost_item.id DESC" in page_sql
    assert "LIMIT 1 OFFSET 1" in page_sql


@pytest.mark.parametrize("page", [2, 10**50])
def test_page_beyond_end_preserves_total_without_fetching_rows(
    customer_client, mock_session, page
):
    mock_session.scalar.return_value = 3

    response = customer_client.get(
        "/api/v1/lost-items", params={"page": page, "size": 100}
    )

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": page, "size": 100, "total": 3}
    mock_session.execute.assert_not_awaited()


def test_empty_result_returns_empty_page(customer_client, mock_session):
    mock_session.scalar.return_value = 0

    response = customer_client.get("/api/v1/lost-items")

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "size": 20, "total": 0}
    mock_session.execute.assert_not_awaited()


def test_detail_returns_requested_translation_and_exact_fields(
    customer_client, mock_session, execute_result, compiled_sql
):
    mock_session.execute.return_value = execute_result(
        _lost_item_row(
            50,
            "EN",
            hours=2,
            is_returned=True,
            image_url="images/lost-item/wallet.webp",
        )
    )

    response = customer_client.get(
        "/api/v1/lost-items/50", params={"language_code": "EN"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "id": 50,
        "image_url": "images/lost-item/wallet.webp",
        "is_returned": True,
        "created_at": body["created_at"],
        "language_code": "EN",
        "title": "lost-item-50-EN",
        "description": "description-50-EN",
        "found_location": "location-50-EN",
    }
    assert datetime.fromisoformat(body["created_at"]) == BASE_TIME + timedelta(hours=2)

    sql = compiled_sql(mock_session.execute.await_args.args[0])
    join_sql, where_sql = sql.split(" WHERE ", maxsplit=1)
    assert "LEFT OUTER JOIN lost_item_translation" in sql
    assert "lost_item_translation.lost_item_id = lost_item.id" in sql
    assert "lost_item_translation.language_code = 'EN'" in join_sql
    assert "lost_item_translation.language_code" not in where_sql
    assert where_sql == "lost_item.id = 50"


@pytest.mark.parametrize(
    ("row", "code"),
    [
        (None, "RESOURCE_NOT_FOUND"),
        (_lost_item_row(70, None, hours=4), "TRANSLATION_NOT_FOUND"),
    ],
)
def test_detail_distinguishes_resource_and_translation_absence(
    customer_client, mock_session, execute_result, row, code
):
    mock_session.execute.return_value = execute_result(*(() if row is None else (row,)))

    response = customer_client.get("/api/v1/lost-items/70")

    assert response.status_code == 404
    assert response.json() == {
        "code": code,
        "message": "요청한 리소스를 찾을 수 없습니다."
        if code == "RESOURCE_NOT_FOUND"
        else "요청한 언어의 번역이 없습니다.",
        "details": [],
    }


@pytest.mark.parametrize("lost_item_id", [2_147_483_648, 10**50])
def test_unstorable_detail_id_is_not_sent_to_postgresql(
    customer_client, mock_session, lost_item_id
):
    response = customer_client.get(f"/api/v1/lost-items/{lost_item_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    mock_session.execute.assert_not_awaited()


@pytest.mark.parametrize("path", ["lost-items", "lost-items/50"])
@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"language_code": "ko"}, "language_code"),
        ({"language_code": "JP"}, "language_code"),
        ({"unknown": "1"}, "unknown"),
    ],
)
def test_invalid_language_and_unknown_query(
    customer_client, mock_session, path, params, field
):
    response = customer_client.get(f"/api/v1/{path}", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["details"][0]["field"] == field
    mock_session.scalar.assert_not_awaited()
    mock_session.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("path", "params", "field"),
    [
        ("lost-items", {"page": 0}, "page"),
        ("lost-items", {"page": "x"}, "page"),
        ("lost-items", {"size": 0}, "size"),
        ("lost-items", {"size": 101}, "size"),
        ("lost-items", {"is_returned": "maybe"}, "is_returned"),
        ("lost-items", {"type": "GENERAL"}, "type"),
        ("lost-items/50", {"page": 1}, "page"),
        ("lost-items/50", {"size": 20}, "size"),
        ("lost-items/50", {"is_returned": False}, "is_returned"),
        ("lost-items/0", {}, "lost_item_id"),
        ("lost-items/-1", {}, "lost_item_id"),
        ("lost-items/1.5", {}, "lost_item_id"),
        ("lost-items/abc", {}, "lost_item_id"),
    ],
)
def test_endpoint_specific_validation(
    customer_client, mock_session, path, params, field
):
    response = customer_client.get(f"/api/v1/{path}", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["details"][0]["field"] == field
    mock_session.scalar.assert_not_awaited()
    mock_session.execute.assert_not_awaited()


def test_openapi_describes_lost_item_contracts(customer_client):
    paths = customer_client.get("/openapi.json").json()["paths"]
    expected_queries = {
        "/api/v1/lost-items": {"language_code", "is_returned", "page", "size"},
        "/api/v1/lost-items/{lost_item_id}": {"language_code"},
    }
    for path, expected in expected_queries.items():
        operation = paths[path]["get"]
        assert {
            param["name"] for param in operation["parameters"] if param["in"] == "query"
        } == expected
        assert operation["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/ErrorResponse")

    list_operation = paths["/api/v1/lost-items"]["get"]
    assert list_operation["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/Page_LostItemResponse_")
    detail = paths["/api/v1/lost-items/{lost_item_id}"]["get"]
    assert detail["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/LostItemResponse")
    assert detail["responses"]["404"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorResponse")
    assert {"/api/v1/", *expected_queries}.issubset(paths)
