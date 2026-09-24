"""명세 §5.2의 요청 본문 규칙. FastAPI를 거쳐 Python mode 검증을 확인한다."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import StrictBool

from backoffice.crud.schemas import (
    CreateTranslations,
    PatchModel,
    PatchTranslations,
    RequestModel,
    TranslationIn,
)
from common.handlers import register_exception_handlers


class _Translation(TranslationIn):
    title: str
    description: str = ""


class _Create(RequestModel):
    is_returned: StrictBool
    at: datetime | None = None
    translations: CreateTranslations[_Translation]


class _Patch(PatchModel):
    NULLABLE = frozenset({"image_url"})

    is_returned: StrictBool | None = None
    image_url: str | None = None
    translations: PatchTranslations[_Translation] | None = None


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/items")
    def create(body: _Create) -> dict:
        return body.model_dump(mode="json")

    @app.patch("/items")
    def patch(body: _Patch) -> dict:
        return {"changes": body.changes(), "translations": body.translations}

    return TestClient(app)


def _ko(**fields) -> dict:
    return {"language_code": "KO", "title": "제목"} | fields


def test_create_accepts_enum_and_datetime_strings(client) -> None:
    response = client.post(
        "/items",
        json={
            "is_returned": False,
            "at": "2026-10-06T10:00:00+09:00",
            "translations": [_ko(), {"language_code": "EN", "title": "t"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["translations"][0]["description"] == ""


@pytest.mark.parametrize(
    "translations",
    [
        [],
        [{"language_code": "EN", "title": "t"}],
        [_ko(), _ko(title="두 번째")],
        [
            _ko(),
            {"language_code": "EN", "title": "a"},
            {"language_code": "EN", "title": "b"},
        ],
    ],
    ids=["empty", "no-ko", "two-ko", "duplicate-en"],
)
def test_create_rejects_invalid_translation_sets(client, translations) -> None:
    response = client.post(
        "/items", json={"is_returned": False, "translations": translations}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "body",
    [
        {"is_returned": "true", "translations": [_ko()]},
        {"is_returned": 1, "translations": [_ko()]},
        {"is_returned": True, "id": 1, "translations": [_ko()]},
        {"is_returned": True, "translations": [_ko(id=3)]},
        {"is_returned": True, "translations": [_ko(language_code="ko")]},
    ],
    ids=["string-bool", "int-bool", "server-id", "translation-id", "lowercase-enum"],
)
def test_create_rejects_coercion_and_server_fields(client, body) -> None:
    assert client.post("/items", json=body).status_code == 422


def test_create_rejects_unsupported_language_with_ko(client) -> None:
    response = client.post(
        "/items",
        json={
            "is_returned": False,
            "translations": [_ko(), {"language_code": "JA", "title": "t"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_patch_rejects_unsupported_language(client) -> None:
    response = client.patch(
        "/items", json={"translations": [{"language_code": "JA", "title": "t"}]}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "body",
    [{}, {"translations": []}, {"is_returned": None}],
    ids=["empty", "empty-translations", "null-required"],
)
def test_patch_rejects_no_change_and_null(client, body) -> None:
    response = client.patch("/items", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_patch_allows_null_on_nullable_field(client) -> None:
    response = client.patch("/items", json={"image_url": None})

    assert response.status_code == 200
    assert response.json()["changes"] == {"image_url": None}


def test_patch_allows_translations_without_ko(client) -> None:
    response = client.patch(
        "/items", json={"translations": [{"language_code": "EN", "title": "t"}]}
    )

    assert response.status_code == 200
    assert response.json()["changes"] == {}
