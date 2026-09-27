"""번역 텍스트 필드 규칙 (명세 §2.2). FastAPI를 거쳐 422 변환까지 확인한다."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backoffice.crud.schemas import (
    OptionalLine,
    OptionalText,
    RequestModel,
    RequiredLine,
    RequiredText,
)
from common.handlers import register_exception_handlers


class _Body(RequestModel):
    title: RequiredLine = "제목"
    content: RequiredText = "본문"
    found_location: OptionalLine = ""
    description: OptionalText = ""


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/items")
    def create(body: _Body) -> dict:
        return body.model_dump()

    return TestClient(app)


def _post(client: TestClient, **fields: str):
    # httpx의 json=은 짝 없는 서로게이트를 인코딩하지 못하므로 직접 직렬화한다.
    raw = json.dumps(fields, ensure_ascii=True).encode()
    return client.post(
        "/items", content=raw, headers={"Content-Type": "application/json"}
    )


@pytest.mark.parametrize("field", ["title", "content", "found_location", "description"])
def test_strips_surrounding_whitespace(client, field) -> None:
    response = _post(client, **{field: " \t 축제\u3000 \n"})

    assert response.status_code == 200
    assert response.json()[field] == "축제"


@pytest.mark.parametrize("field", ["title", "content"])
@pytest.mark.parametrize("value", ["", " ", "\u3000", " \n\t "])
def test_required_rejects_blank(client, field, value) -> None:
    response = _post(client, **{field: value})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("field", ["found_location", "description"])
def test_optional_blank_becomes_empty(client, field) -> None:
    response = _post(client, **{field: "   "})

    assert response.status_code == 200
    assert response.json()[field] == ""


@pytest.mark.parametrize("field", ["content", "description"])
def test_body_text_keeps_inner_line_breaks_and_tabs(client, field) -> None:
    value = "첫 줄\n둘째 줄\r\n\t들여쓰기"

    response = _post(client, **{field: value})

    assert response.status_code == 200
    assert response.json()[field] == value


@pytest.mark.parametrize("field", ["title", "found_location"])
@pytest.mark.parametrize("char", ["\n", "\r", "\t"])
def test_line_rejects_inner_line_breaks_and_tabs(client, field, char) -> None:
    response = _post(client, **{field: f"앞{char}뒤"})

    assert response.status_code == 422


@pytest.mark.parametrize("field", ["title", "content", "found_location", "description"])
@pytest.mark.parametrize(
    "char",
    ["\x00", "\x07", "\x1b", "\x7f", "\x9b", "\ud83d", "\udc00"],
    ids=[
        "nul",
        "bell",
        "escape",
        "delete",
        "c1-csi",
        "high-surrogate",
        "low-surrogate",
    ],
)
def test_rejects_control_and_lone_surrogate(client, field, char) -> None:
    response = _post(client, **{field: f"앞{char}뒤"})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("field", ["title", "content", "found_location", "description"])
@pytest.mark.parametrize(
    "value",
    [
        "🎉 축제 개막",
        "👨\u200d👩\u200d👧 가족 부스",
        "❤\ufe0f 사랑",
        "🇰🇷 한국",
        "👍🏽 좋아요",
    ],
    ids=["basic", "zwj", "variation-selector", "flag", "skin-tone"],
)
def test_accepts_emoji(client, field, value) -> None:
    response = _post(client, **{field: value})

    assert response.status_code == 200
    assert response.json()[field] == value


@pytest.mark.parametrize("value", [123, None, ["제목"]], ids=["int", "null", "list"])
def test_rejects_non_string(client, value) -> None:
    response = client.post("/items", json={"title": value})

    assert response.status_code == 422
