"""Mock 세션으로 API 명세 §3.4의 공연 조회 계약과 SQL 구성을 검증한다."""

from datetime import date

import pytest
from sqlalchemy import Table
from sqlalchemy.sql.selectable import TableClause

from customer.api.routes.performances import _PERFORMANCE, _PERFORMANCE_TRANSLATION
from quinquatria_persistence import (
    Base,
    LanguageCode,
    Performance,
    PerformanceType,
)

DAY_ONE = date(2026, 10, 6)
DAY_TWO = date(2026, 10, 7)


def _performance_row(
    resource_id: int,
    performance_type: PerformanceType,
    performance_date: date,
    sequence: int,
    language_code: LanguageCode,
    *,
    image_uri: str | None = None,
    is_live: bool = False,
    description: str | None = None,
) -> dict[str, object]:
    return {
        "id": resource_id,
        "type": performance_type,
        "image_uri": image_uri,
        "date": performance_date,
        "seq": sequence,
        "is_live": is_live,
        "language_code": language_code,
        "title": f"performance-{resource_id}-{language_code.value}",
        "description": (
            description
            if description is not None
            else f"description-{resource_id}-{language_code.value}"
        ),
    }


def test_customer_projection_does_not_mutate_shared_metadata():
    assert isinstance(_PERFORMANCE, TableClause)
    assert isinstance(_PERFORMANCE_TRANSLATION, TableClause)
    assert not isinstance(_PERFORMANCE, Table)
    assert not isinstance(_PERFORMANCE_TRANSLATION, Table)
    assert Base.metadata.tables["performance"] is Performance.__table__
    assert _PERFORMANCE is not Performance.__table__
    assert all(_PERFORMANCE is not mapped for mapped in Base.metadata.tables.values())
    assert all(
        _PERFORMANCE_TRANSLATION is not mapped
        for mapped in Base.metadata.tables.values()
    )
    assert set(_PERFORMANCE.c.keys()) == {
        "id",
        "type",
        "image_id",
        "date",
        "seq",
        "is_live",
    }


def test_performances_default_language_and_complete_response(
    customer_client, mock_session, execute_result
):
    mock_session.scalar.return_value = 3
    mock_session.execute.return_value = execute_result(
        _performance_row(
            40,
            PerformanceType.STUDENT,
            DAY_ONE,
            1,
            LanguageCode.KO,
            description="",
        ),
        _performance_row(
            30,
            PerformanceType.ARTIST,
            DAY_ONE,
            2,
            LanguageCode.KO,
            image_uri="images/performance/artist.webp",
            is_live=True,
        ),
        _performance_row(10, PerformanceType.STUDENT, DAY_TWO, 1, LanguageCode.KO),
    )

    response = customer_client.get("/api/v1/performances")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "items": [
            {
                "id": 40,
                "type": "STUDENT",
                "image_uri": None,
                "date": "2026-10-06",
                "seq": 1,
                "is_live": False,
                "language_code": "KO",
                "title": "performance-40-KO",
                "description": "",
            },
            {
                "id": 30,
                "type": "ARTIST",
                "image_uri": "images/performance/artist.webp",
                "date": "2026-10-06",
                "seq": 2,
                "is_live": True,
                "language_code": "KO",
                "title": "performance-30-KO",
                "description": "description-30-KO",
            },
            {
                "id": 10,
                "type": "STUDENT",
                "image_uri": None,
                "date": "2026-10-07",
                "seq": 1,
                "is_live": False,
                "language_code": "KO",
                "title": "performance-10-KO",
                "description": "description-10-KO",
            },
        ],
        "page": 1,
        "size": 20,
        "total": 3,
    }


@pytest.mark.parametrize(("language", "resource_id"), [("EN", 30), ("CHN", 31)])
def test_performance_list_builds_translation_filter_and_stable_order(
    customer_client,
    mock_session,
    execute_result,
    compiled_sql,
    language,
    resource_id,
):
    mock_session.scalar.return_value = 1
    mock_session.execute.return_value = execute_result(
        _performance_row(
            resource_id,
            PerformanceType.ARTIST,
            DAY_ONE,
            2,
            LanguageCode(language),
        )
    )

    response = customer_client.get(
        "/api/v1/performances",
        params={
            "language_code": language,
            "type": "ARTIST",
            "date": "2026-10-06",
        },
    )

    assert response.status_code == 200
    sql = compiled_sql(mock_session.execute.await_args.args[0])
    assert (
        "FROM performance LEFT OUTER JOIN image ON image.id = performance.image_id "
        "JOIN performance_translation ON "
        "performance_translation.performance_id = performance.id" in sql
    )
    assert f"performance_translation.language_code = '{language}'" in sql
    assert "performance.type = 'ARTIST'" in sql
    assert "performance.date = '2026-10-06'" in sql
    assert "ORDER BY performance.date, performance.seq, performance.id" in sql
    assert "LIMIT 20 OFFSET 0" in sql
    assert "start_at" not in sql and "end_at" not in sql
    assert response.json()["items"][0]["language_code"] == language

    count_sql = compiled_sql(mock_session.scalar.await_args.args[0])
    assert (
        "FROM performance LEFT OUTER JOIN image ON image.id = performance.image_id "
        "JOIN performance_translation ON "
        "performance_translation.performance_id = performance.id" in count_sql
    )
    assert f"performance_translation.language_code = '{language}'" in count_sql
    assert "performance.type = 'ARTIST'" in count_sql
    assert "performance.date = '2026-10-06'" in count_sql
    assert "ORDER BY" not in count_sql
    assert "LIMIT" not in count_sql and "OFFSET" not in count_sql


def test_performances_apply_pagination_after_filters(
    customer_client, mock_session, execute_result, compiled_sql
):
    mock_session.scalar.return_value = 3
    mock_session.execute.return_value = execute_result(
        _performance_row(20, PerformanceType.SPECIAL, DAY_ONE, 3, LanguageCode.EN)
    )

    response = customer_client.get(
        "/api/v1/performances",
        params={"language_code": "EN", "page": 2, "size": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [20]
    assert (body["page"], body["size"], body["total"]) == (2, 2, 3)
    assert "LIMIT 2 OFFSET 2" in compiled_sql(mock_session.execute.await_args.args[0])


@pytest.mark.parametrize("page", [2, 10**50])
def test_performances_page_beyond_end_preserves_total(
    customer_client, mock_session, page
):
    mock_session.scalar.return_value = 3

    response = customer_client.get(
        "/api/v1/performances", params={"page": page, "size": 20}
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "page": page,
        "size": 20,
        "total": 3,
    }
    mock_session.execute.assert_not_awaited()


def test_performances_empty_result_returns_empty_page(customer_client, mock_session):
    mock_session.scalar.return_value = 0

    response = customer_client.get("/api/v1/performances")

    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 1, "size": 20, "total": 0}
    mock_session.execute.assert_not_awaited()


@pytest.mark.parametrize(("language", "resource_id"), [("EN", 20), ("CHN", 21)])
def test_performance_detail_uses_requested_translation_and_outer_join(
    customer_client,
    mock_session,
    execute_result,
    compiled_sql,
    language,
    resource_id,
):
    mock_session.execute.return_value = execute_result(
        _performance_row(
            resource_id,
            PerformanceType.SPECIAL,
            DAY_ONE,
            3,
            LanguageCode(language),
        )
    )

    response = customer_client.get(
        f"/api/v1/performances/{resource_id}",
        params={"language_code": language},
    )

    assert response.status_code == 200
    assert response.json()["language_code"] == language
    assert response.json()["title"] == f"performance-{resource_id}-{language}"
    sql = compiled_sql(mock_session.execute.await_args.args[0])
    assert "LEFT OUTER JOIN performance_translation ON" in sql
    assert "performance_translation.performance_id = performance.id" in sql
    on_clause, where_clause = sql.split(" WHERE ", maxsplit=1)
    assert f"performance_translation.language_code = '{language}'" in on_clause
    assert "performance_translation.language_code" not in where_clause
    assert where_clause == f"performance.id = {resource_id}"


def test_missing_performance_returns_resource_not_found(
    customer_client, mock_session, execute_result
):
    mock_session.execute.return_value = execute_result()

    response = customer_client.get("/api/v1/performances/999")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.parametrize("performance_id", [2_147_483_648, 10**50])
def test_unstorable_performance_id_returns_resource_not_found_without_query(
    customer_client, mock_session, performance_id
):
    response = customer_client.get(f"/api/v1/performances/{performance_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    mock_session.execute.assert_not_awaited()


def test_missing_requested_translation_returns_translation_not_found(
    customer_client, mock_session, execute_result
):
    row = _performance_row(20, PerformanceType.SPECIAL, DAY_ONE, 3, LanguageCode.EN)
    row.update(language_code=None, title=None, description=None)
    mock_session.execute.return_value = execute_result(row)

    response = customer_client.get("/api/v1/performances/20")

    assert response.status_code == 404
    assert response.json()["code"] == "TRANSLATION_NOT_FOUND"


@pytest.mark.parametrize(
    "params",
    [
        {"language_code": "ko"},
        {"language_code": "JP"},
        {"type": "artist"},
        {"type": "UNKNOWN"},
        {"page": 0},
        {"size": 0},
        {"size": 101},
        {"unknown": "1"},
    ],
)
def test_performance_list_rejects_invalid_or_unknown_query(
    customer_client, mock_session, params
):
    response = customer_client.get("/api/v1/performances", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    mock_session.scalar.assert_not_awaited()
    mock_session.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "invalid_date",
    [
        "2026-02-30",
        "2026-1-06",
        "2026-10-6",
        "2026-10-06T00:00:00",
        "2026-10-06T00:00:00+09:00",
        "1791244800",
    ],
)
def test_performance_list_requires_exact_calendar_date(
    customer_client, mock_session, invalid_date
):
    response = customer_client.get(
        "/api/v1/performances", params={"date": invalid_date}
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert any(detail["field"] == "date" for detail in body["details"])
    mock_session.scalar.assert_not_awaited()
    mock_session.execute.assert_not_awaited()


@pytest.mark.parametrize("performance_id", ["zero", 0, -1])
def test_performance_detail_rejects_invalid_id(
    customer_client, mock_session, performance_id
):
    response = customer_client.get(f"/api/v1/performances/{performance_id}")

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    mock_session.execute.assert_not_awaited()


@pytest.mark.parametrize("extra", ["page", "size", "type", "date", "unknown"])
def test_performance_detail_rejects_list_or_unknown_query(
    customer_client, mock_session, extra
):
    response = customer_client.get("/api/v1/performances/30", params={extra: "1"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    mock_session.execute.assert_not_awaited()


def test_performance_openapi_documents_exact_contract(customer_client):
    paths = customer_client.get("/openapi.json").json()["paths"]
    listing = paths["/api/v1/performances"]["get"]
    detail = paths["/api/v1/performances/{performance_id}"]["get"]

    assert {
        parameter["name"]
        for parameter in listing["parameters"]
        if parameter["in"] == "query"
    } == {"language_code", "type", "date", "page", "size"}
    assert {
        parameter["name"]
        for parameter in detail["parameters"]
        if parameter["in"] == "query"
    } == {"language_code"}
    assert listing["responses"]["422"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorResponse")
    assert detail["responses"]["404"]["content"]["application/json"]["schema"][
        "$ref"
    ].endswith("/ErrorResponse")
