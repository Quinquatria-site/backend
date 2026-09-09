"""API 명세 §2의 공통 규칙을 HTTP 수준에서 검증한다."""

from typing import Annotated

import pytest
from fastapi import APIRouter, Query, Response, status
from fastapi.testclient import TestClient

from common.app import API_V1_PREFIX, create_api_app
from common.enums import LanguageCode
from common.errors import ApiError, ErrorCode, ErrorDetail
from common.pagination import Page
from common.query import LanguageQuery, ListQuery, NoQuery

router = APIRouter()

NOTICES = [{"id": index, "title": f"공지 {index}"} for index in range(1, 4)]


@router.get("/notices")
async def list_notices(query: Annotated[ListQuery, Query()]) -> Page[dict]:
    start = (query.page - 1) * query.size
    return Page[dict](
        items=NOTICES[start : start + query.size],
        page=query.page,
        size=query.size,
        total=len(NOTICES),
    )


@router.get("/notices/{notice_id}")
async def get_notice(notice_id: int, query: Annotated[LanguageQuery, Query()]) -> dict:
    if notice_id != 1:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND)
    return {"id": notice_id, "language_code": query.language_code}


@router.delete("/notices/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notice(notice_id: int, query: Annotated[NoQuery, Query()]) -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/categories/{category_id}")
async def delete_category(category_id: int) -> Response:
    raise ApiError(
        ErrorCode.DELETE_CONFLICT,
        message="장소가 연결된 카테고리는 삭제할 수 없습니다.",
        details=[
            ErrorDetail(
                field="category_id", reason="연결된 장소를 먼저 삭제해야 합니다."
            )
        ],
    )


@router.get("/boom")
async def boom() -> dict:
    raise RuntimeError("password=hunter2 SELECT * FROM notice")


app = create_api_app(title="Contract Test API", router=router)
client = TestClient(app, raise_server_exceptions=False)


def test_routes_are_registered_under_the_v1_prefix() -> None:
    assert API_V1_PREFIX == "/api/v1"
    assert client.get("/api/v1/notices").status_code == 200
    assert client.get("/notices").status_code == 404


def test_list_response_uses_the_spec_envelope() -> None:
    body = client.get("/api/v1/notices").json()

    assert list(body) == ["items", "page", "size", "total"]
    assert body["page"] == 1
    assert body["size"] == 20
    assert body["total"] == 3


def test_page_beyond_the_last_returns_an_empty_list() -> None:
    response = client.get("/api/v1/notices", params={"page": 99})

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total"] == 3


def test_unknown_query_parameter_is_rejected() -> None:
    response = client.get("/api/v1/notices", params={"unknown": "1"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == ErrorCode.VALIDATION_ERROR
    assert [detail["field"] for detail in body["details"]] == ["unknown"]


def test_detail_endpoint_rejects_list_only_query() -> None:
    response = client.get("/api/v1/notices/1", params={"page": 2})

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.VALIDATION_ERROR


def test_endpoint_without_query_rejects_any_parameter() -> None:
    response = client.delete("/api/v1/notices/1", params={"language_code": "KO"})

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.VALIDATION_ERROR


@pytest.mark.parametrize("params", [{"page": 0}, {"size": 0}, {"size": 101}])
def test_page_and_size_bounds_are_enforced(params: dict[str, int]) -> None:
    response = client.get("/api/v1/notices", params=params)

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.VALIDATION_ERROR


def test_invalid_enum_value_is_rejected() -> None:
    response = client.get("/api/v1/notices", params={"language_code": "ko"})

    assert response.status_code == 422
    assert response.json()["details"][0]["field"] == "language_code"


def test_language_code_defaults_to_korean() -> None:
    assert client.get("/api/v1/notices/1").json()["language_code"] == LanguageCode.KO


def test_validation_error_body_has_the_spec_keys() -> None:
    body = client.get("/api/v1/notices", params={"size": 0}).json()

    assert list(body) == ["code", "message", "details"]
    assert body["message"]
    assert list(body["details"][0]) == ["field", "reason"]


def test_api_error_uses_its_own_status_and_message() -> None:
    response = client.delete("/api/v1/categories/1")

    assert response.status_code == 409
    assert response.json() == {
        "code": "DELETE_CONFLICT",
        "message": "장소가 연결된 카테고리는 삭제할 수 없습니다.",
        "details": [
            {
                "field": "category_id",
                "reason": "연결된 장소를 먼저 삭제해야 합니다.",
            }
        ],
    }


def test_api_error_without_details_returns_an_empty_array() -> None:
    response = client.get("/api/v1/notices/99")

    assert response.status_code == 404
    assert response.json() == {
        "code": "RESOURCE_NOT_FOUND",
        "message": "요청한 리소스를 찾을 수 없습니다.",
        "details": [],
    }


def test_unknown_path_returns_the_spec_error_body() -> None:
    response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == ErrorCode.RESOURCE_NOT_FOUND


def test_no_content_response_has_no_body_or_content_type() -> None:
    response = client.delete("/api/v1/notices/1")

    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers


def test_unhandled_exception_returns_a_generic_five_hundred() -> None:
    response = client.get("/api/v1/boom")

    assert response.status_code == 500
    assert response.json() == {
        "code": "INTERNAL_SERVER_ERROR",
        "message": "서버 내부 오류가 발생했습니다.",
        "details": [],
    }


def test_unhandled_exception_never_leaks_internals() -> None:
    body = client.get("/api/v1/boom").text

    assert "hunter2" not in body
    assert "SELECT" not in body
    assert "RuntimeError" not in body
    assert "Traceback" not in body
