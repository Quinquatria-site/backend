"""카탈로그 테스트의 요청 본문과 이미지 업로드 도우미."""

from itertools import count
from typing import Any

import httpx

from ..._images import FakeObjectStore, put_object

WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 64


async def upload(
    api: httpx.AsyncClient, store: FakeObjectStore, resource_type: str
) -> str:
    """발급 API로 key를 받고 S3 업로드까지 끝낸 것처럼 객체를 둔다."""
    response = await api.post(
        "/api/v1/uploads/images/presigned-url",
        json={
            "resource_type": resource_type,
            "content_type": "image/webp",
            "size": len(WEBP),
        },
    )
    assert response.status_code == 200, response.text
    key = response.json()["object_key"]
    put_object(store, key, body=WEBP, content_type="image/webp")
    return key


def category_body(**overrides: Any) -> dict[str, Any]:
    return {
        "code": "PUB",
        "translations": [{"language_code": "KO", "name": "주점"}],
    } | overrides


async def create_category(api: httpx.AsyncClient, **overrides: Any) -> dict:
    response = await api.post("/api/v1/categories", json=category_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


_sequences = count(1)
"""같은 카테고리에 장소를 여럿 만들어도 번호가 겹치지 않게 기본값을 늘려 준다."""


def place_body(category_id: int, /, **overrides: Any) -> dict[str, Any]:
    return {
        "category_id": category_id,
        "category_sequence": next(_sequences),
        "x": 127.42,
        "y": 36.18,
        "start_hour": "2026-10-06T10:00:00+09:00",
        "end_hour": "2026-10-06T22:00:00+09:00",
        "translations": [
            {"language_code": "KO", "name": "주점", "host_college": "통번역대학"}
        ],
    } | overrides


async def create_place(
    api: httpx.AsyncClient, category_id: int, /, **overrides
) -> dict:
    response = await api.post(
        "/api/v1/places", json=place_body(category_id, **overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


def menu_body(place_id: int, /, **overrides: Any) -> dict[str, Any]:
    return {
        "place_id": place_id,
        "price": 5000,
        "translations": [{"language_code": "KO", "name": "떡볶이"}],
    } | overrides


async def create_menu(api: httpx.AsyncClient, place_id: int, /, **overrides) -> dict:
    response = await api.post("/api/v1/menus", json=menu_body(place_id, **overrides))
    assert response.status_code == 201, response.text
    return response.json()
