"""카탈로그 테스트의 요청 본문과 이미지 업로드 도우미."""

from itertools import count
from typing import Any

import httpx
from sqlalchemy import text

from quinquatria_persistence import Database

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


SEEDED_CATEGORIES = {
    "PUB": (1, {"KO": "주점", "EN": "Pub", "CHN": "酒馆"}),
    "BOOTH": (2, {"KO": "부스", "EN": "Booth", "CHN": "摊位"}),
    "FOODTRUCK": (3, {"KO": "푸드트럭", "EN": "Food Truck", "CHN": "餐车"}),
    "MEDI": (4, {"KO": "의무실", "EN": "Medical Room", "CHN": "医务室"}),
    "TRASHCAN": (5, {"KO": "쓰레기통", "EN": "Trash Can", "CHN": "垃圾桶"}),
    "PHOTOBOOTH": (6, {"KO": "포토부스", "EN": "Photo Booth", "CHN": "拍照亭"}),
}
"""migration이 넣는 고정 카테고리 (명세 §5.3). 테스트 DB는 매번 비우므로 다시 넣는다."""


async def seed_categories(database: Database) -> None:
    async with database.engine.begin() as connection:
        for code, (category_id, names) in SEEDED_CATEGORIES.items():
            await connection.execute(
                text(
                    "INSERT INTO category (id, code) OVERRIDING SYSTEM VALUE "
                    "VALUES (:id, CAST(:code AS category_code))"
                ),
                {"id": category_id, "code": code},
            )
            for language, name in names.items():
                await connection.execute(
                    text(
                        "INSERT INTO category_translation "
                        "(category_id, language_code, name) "
                        "VALUES (:id, CAST(:language AS language_code), :name)"
                    ),
                    {"id": category_id, "language": language, "name": name},
                )


async def seeded_category(
    api: httpx.AsyncClient, code: str = "PUB", /, **changes: Any
) -> dict:
    """시드 카테고리. `changes`가 있으면 `PATCH`로 반영한 결과를 돌려준다."""
    category_id = SEEDED_CATEGORIES[code][0]
    if changes:
        response = await api.patch(f"/api/v1/categories/{category_id}", json=changes)
        assert response.status_code == 200, response.text
    else:
        response = await api.get(f"/api/v1/categories/{category_id}")
        assert response.status_code == 200, response.text
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
