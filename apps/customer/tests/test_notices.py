"""DB 경계 mock으로 API 명세 §3.5의 공지 조회 계약을 검증한다."""

from datetime import datetime, timedelta, timezone

import pytest

KST = timezone(timedelta(hours=9))
FIRST = datetime(2026, 10, 5, 9, tzinfo=KST)


def _notice_row(
    resource_id: int,
    notice_type: str,
    language: str | None,
    *,
    hours: int = 0,
):
    return {
        "id": resource_id,
        "type": notice_type,
        "created_at": FIRST + timedelta(hours=hours),
        "language_code": language,
        "title": None if language is None else f"notice-{resource_id}-{language}",
        "content": None if language is None else f"content-{resource_id}-{language}",
    }


def _set_page(mock_session, execute_result, total, *rows):
    mock_session.scalar.return_value = total
    mock_session.execute.return_value = execute_result(*rows)


def _assert_unpaginated_count(sql: str):
    assert "ORDER BY" not in sql
    assert "LIMIT" not in sql
    assert "OFFSET" not in sql


def test_general_notices_default_to_korean_and_serialize_rows(
    customer_client, mock_session, execute_result, compiled_sql
):
    rows = (
        _notice_row(30, "GENERAL", "KO", hours=2),
        _notice_row(20, "GENERAL", "KO", hours=1),
        _notice_row(10, "GENERAL", "KO"),
    )
    _set_page(mock_session, execute_result, 3, *rows)

    response = customer_client.get("/api/v1/notices")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert [item["id"] for item in body["items"]] == [30, 20, 10]
    assert (body["page"], body["size"], body["total"]) == (1, 20, 3)
    assert all(item["type"] == "GENERAL" for item in body["items"])
    assert all(item["language_code"] == "KO" for item in body["items"])
    assert datetime.fromisoformat(body["items"][0]["created_at"]) == FIRST + timedelta(
        hours=2
    )

    count_sql = compiled_sql(mock_session.scalar.await_args.args[0])
    page_sql = compiled_sql(mock_session.execute.await_args.args[0])
    for sql in (count_sql, page_sql):
        assert (
            "JOIN notice_translation ON notice_translation.notice_id = notice.id" in sql
        )
        assert "notice.type = 'GENERAL'" in sql
        assert "notice_translation.language_code = 'KO'" in sql
    _assert_unpaginated_count(count_sql)
    assert "ORDER BY notice.created_at DESC, notice.id DESC" in page_sql
    assert "LIMIT 20 OFFSET 0" in page_sql


@pytest.mark.parametrize(
    ("language", "rows"),
    [
        ("KO", (_notice_row(50, "PERMANENT", "KO", hours=3),)),
        (
            "EN",
            (
                _notice_row(60, "PERMANENT", "EN", hours=4),
                _notice_row(50, "PERMANENT", "EN", hours=3),
            ),
        ),
        ("CHN", ()),
    ],
)
def test_permanent_notices_use_requested_language_and_static_route(
    customer_client,
    mock_session,
    execute_result,
    compiled_sql,
    language,
    rows,
):
    _set_page(mock_session, execute_result, len(rows), *rows)

    response = customer_client.get(
        "/api/v1/notices/permanent", params={"language_code": language}
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [row["id"] for row in rows]
    assert body["total"] == len(rows)
    assert all(item["type"] == "PERMANENT" for item in body["items"])
    assert all(item["language_code"] == language for item in body["items"])

    count_sql = compiled_sql(mock_session.scalar.await_args.args[0])
    assert "notice.type = 'PERMANENT'" in count_sql
    assert f"notice_translation.language_code = '{language}'" in count_sql
    _assert_unpaginated_count(count_sql)
    if rows:
        page_sql = compiled_sql(mock_session.execute.await_args.args[0])
        assert "ORDER BY notice.created_at DESC, notice.id DESC" in page_sql
    else:
        mock_session.execute.assert_not_awaited()


def test_general_notices_count_filters_before_pagination(
    customer_client, mock_session, execute_result, compiled_sql
):
    _set_page(
        mock_session,
        execute_result,
        2,
        _notice_row(10, "GENERAL", "EN"),
    )

    response = customer_client.get(
        "/api/v1/notices",
        params={"language_code": "EN", "page": 2, "size": 1},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == 10
    assert response.json() | {"items": []} == {
        "items": [],
        "page": 2,
        "size": 1,
        "total": 2,
    }

    count_sql = compiled_sql(mock_session.scalar.await_args.args[0])
    page_sql = compiled_sql(mock_session.execute.await_args.args[0])
    assert "notice_translation.language_code = 'EN'" in count_sql
    assert "notice.type = 'GENERAL'" in count_sql
    _assert_unpaginated_count(count_sql)
    assert "ORDER BY notice.created_at DESC, notice.id DESC" in page_sql
    assert "LIMIT 1 OFFSET 1" in page_sql


@pytest.mark.parametrize(("path", "total"), [("notices", 3), ("notices/permanent", 1)])
@pytest.mark.parametrize("page", [10, 10**50])
def test_page_beyond_end_preserves_total_without_fetching_rows(
    customer_client, mock_session, path, total, page
):
    mock_session.scalar.return_value = total

    response = customer_client.get(f"/api/v1/{path}", params={"page": page})

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": page, "size": 20, "total": total}
    mock_session.execute.assert_not_awaited()


@pytest.mark.parametrize("path", ["notices", "notices/permanent"])
def test_empty_result_returns_empty_page(customer_client, mock_session, path):
    mock_session.scalar.return_value = 0

    response = customer_client.get(f"/api/v1/{path}")

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "size": 20, "total": 0}
    mock_session.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("notice_type", "language"),
    [("GENERAL", "KO"), ("GENERAL", "EN"), ("PERMANENT", "CHN")],
)
def test_detail_returns_both_types_and_requested_languages(
    customer_client,
    mock_session,
    execute_result,
    compiled_sql,
    notice_type,
    language,
):
    row = _notice_row(20, notice_type, language, hours=1)
    mock_session.execute.return_value = execute_result(row)

    response = customer_client.get(
        "/api/v1/notices/20", params={"language_code": language}
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": 20,
        "type": notice_type,
        "created_at": response.json()["created_at"],
        "language_code": language,
        "title": f"notice-20-{language}",
        "content": f"content-20-{language}",
    }
    assert datetime.fromisoformat(response.json()["created_at"]) == FIRST + timedelta(
        hours=1
    )

    sql = compiled_sql(mock_session.execute.await_args.args[0])
    join_sql, where_sql = sql.split(" WHERE ", maxsplit=1)
    assert "LEFT OUTER JOIN notice_translation" in sql
    assert "notice_translation.notice_id = notice.id" in sql
    assert f"notice_translation.language_code = '{language}'" in join_sql
    assert "notice_translation.language_code" not in where_sql
    assert where_sql == "notice.id = 20"


@pytest.mark.parametrize(
    ("row", "code"),
    [
        (None, "RESOURCE_NOT_FOUND"),
        (_notice_row(40, "GENERAL", None, hours=2), "TRANSLATION_NOT_FOUND"),
    ],
)
def test_detail_distinguishes_resource_and_translation_absence(
    customer_client, mock_session, execute_result, row, code
):
    mock_session.execute.return_value = execute_result(*(() if row is None else (row,)))

    response = customer_client.get("/api/v1/notices/40")

    assert response.status_code == 404
    assert response.json() == {
        "code": code,
        "message": "요청한 리소스를 찾을 수 없습니다."
        if code == "RESOURCE_NOT_FOUND"
        else "요청한 언어의 번역이 없습니다.",
        "details": [],
    }


@pytest.mark.parametrize("notice_id", [2_147_483_648, 10**50])
def test_unstorable_detail_id_is_not_sent_to_postgresql(
    customer_client, mock_session, notice_id
):
    response = customer_client.get(f"/api/v1/notices/{notice_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    mock_session.execute.assert_not_awaited()


def test_latest_uses_static_route_and_selects_base_general_before_translation(
    customer_client, mock_session, execute_result, compiled_sql
):
    mock_session.execute.return_value = execute_result(
        _notice_row(40, "GENERAL", "EN", hours=2)
    )

    response = customer_client.get(
        "/api/v1/notices/latest", params={"language_code": "EN"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": 40,
        "type": "GENERAL",
        "created_at": response.json()["created_at"],
        "language_code": "EN",
        "title": "notice-40-EN",
        "content": "content-40-EN",
    }

    sql = compiled_sql(mock_session.execute.await_args.args[0])
    assert "LEFT OUTER JOIN notice_translation" in sql
    assert (
        "notice_translation.notice_id = notice.id AND "
        "notice_translation.language_code = 'EN'" in sql
    )
    assert "WHERE notice.type = 'GENERAL'" in sql
    assert "ORDER BY notice.created_at DESC, notice.id DESC" in sql
    assert "LIMIT 1" in sql
    assert sql.index("notice_translation.language_code = 'EN'") < sql.index("WHERE")


@pytest.mark.parametrize("language", ["KO", "CHN"])
def test_latest_does_not_fall_back_when_translation_is_missing(
    customer_client, mock_session, execute_result, language
):
    mock_session.execute.return_value = execute_result(
        _notice_row(40, "GENERAL", None, hours=2)
    )

    response = customer_client.get(
        "/api/v1/notices/latest", params={"language_code": language}
    )

    assert response.status_code == 404
    assert response.json() == {
        "code": "TRANSLATION_NOT_FOUND",
        "message": "요청한 언어의 번역이 없습니다.",
        "details": [],
    }


def test_latest_without_general_notice_is_bodyless_204(
    customer_client, mock_session, execute_result
):
    mock_session.execute.return_value = execute_result()

    response = customer_client.get("/api/v1/notices/latest")

    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers


@pytest.mark.parametrize(
    "path",
    ["notices", "notices/permanent", "notices/latest", "notices/20"],
)
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
        ("notices", {"type": "GENERAL"}, "type"),
        ("notices", {"page": 0}, "page"),
        ("notices", {"size": 101}, "size"),
        ("notices/permanent", {"type": "PERMANENT"}, "type"),
        ("notices/latest", {"page": 1}, "page"),
        ("notices/latest", {"size": 20}, "size"),
        ("notices/latest", {"type": "GENERAL"}, "type"),
        ("notices/20", {"page": 1}, "page"),
        ("notices/20", {"size": 20}, "size"),
        ("notices/20", {"type": "GENERAL"}, "type"),
        ("notices/0", {}, "notice_id"),
        ("notices/-1", {}, "notice_id"),
        ("notices/1.5", {}, "notice_id"),
        ("notices/abc", {}, "notice_id"),
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


def test_openapi_describes_notice_query_and_response_contracts(customer_client):
    paths = customer_client.get("/openapi.json").json()["paths"]
    expected_queries = {
        "/api/v1/notices": {"language_code", "page", "size"},
        "/api/v1/notices/permanent": {"language_code", "page", "size"},
        "/api/v1/notices/latest": {"language_code"},
        "/api/v1/notices/{notice_id}": {"language_code"},
    }
    for path, expected in expected_queries.items():
        operation = paths[path]["get"]
        assert {
            param["name"] for param in operation["parameters"] if param["in"] == "query"
        } == expected
        assert operation["responses"]["422"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/ErrorResponse")

    for path in ("/api/v1/notices/latest", "/api/v1/notices/{notice_id}"):
        operation = paths[path]["get"]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/NoticeResponse")
        assert operation["responses"]["404"]["content"]["application/json"]["schema"][
            "$ref"
        ].endswith("/ErrorResponse")

    latest = paths["/api/v1/notices/latest"]["get"]
    assert "content" not in latest["responses"]["204"]
    assert set(expected_queries).issubset(paths)
