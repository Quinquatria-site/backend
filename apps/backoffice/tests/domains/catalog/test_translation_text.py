"""명세 §2.2 번역 텍스트 규칙이 카탈로그 라우트와 DB 왕복에서 지켜지는지."""

import json

import pytest

from ._helpers import (
    category_body,
    create_category,
    create_place,
    menu_body,
    place_body,
)

EMOJI = "🎉 👨\u200d👩\u200d👧 ❤\ufe0f 🇰🇷"


async def _post_raw(api, url: str, body: dict):
    # 짝 없는 서로게이트는 httpx의 json=으로 인코딩되지 않는다.
    raw = json.dumps(body, ensure_ascii=True).encode()
    return await api.post(
        url, content=raw, headers={"Content-Type": "application/json"}
    )


async def test_category_name_is_trimmed(api) -> None:
    created = await create_category(
        api, translations=[{"language_code": "KO", "name": "  주점\u3000"}]
    )

    assert created["translations"][0]["name"] == "주점"


@pytest.mark.parametrize("name", ["", "   ", "주\x00점", "주\n점"])
async def test_category_rejects_invalid_name(api, name) -> None:
    response = await api.post(
        "/api/v1/categories",
        json=category_body(translations=[{"language_code": "KO", "name": name}]),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_category_rejects_lone_surrogate(api) -> None:
    body = category_body(translations=[{"language_code": "KO", "name": "\ud83d"}])

    response = await _post_raw(api, "/api/v1/categories", body)

    assert response.status_code == 422


async def test_category_patch_rejects_blank_name(api) -> None:
    created = await create_category(api)

    response = await api.patch(
        f"/api/v1/categories/{created['id']}",
        json={"translations": [{"language_code": "EN", "name": " "}]},
    )

    assert response.status_code == 422


async def test_place_round_trips_emoji_and_description_line_breaks(api) -> None:
    category = await create_category(api)
    description = f"{EMOJI}\n둘째 줄\t탭"
    created = await create_place(
        api,
        category["id"],
        translations=[
            {
                "language_code": "KO",
                "name": f" {EMOJI} 주점 ",
                "host_college": EMOJI,
                "description": f"  {description}  ",
            }
        ],
    )

    response = await api.get(f"/api/v1/places/{created['id']}")

    translation = response.json()["translations"][0]
    assert translation["name"] == f"{EMOJI} 주점"
    assert translation["host_college"] == EMOJI
    assert translation["description"] == description


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host_college", " "),
        ("host_college", "대학\n이름"),
        ("description", "설명\x00"),
        ("description", "설명\x1b[31m"),
    ],
)
async def test_place_rejects_invalid_text(api, field, value) -> None:
    category = await create_category(api)
    translation = {"language_code": "KO", "name": "주점", "host_college": "통번역대학"}

    response = await api.post(
        "/api/v1/places",
        json=place_body(category["id"], translations=[translation | {field: value}]),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_menu_rejects_nul_in_description(api) -> None:
    category = await create_category(api)
    place = await create_place(api, category["id"])

    response = await api.post(
        "/api/v1/menus",
        json=menu_body(
            place["id"],
            translations=[
                {"language_code": "KO", "name": "떡볶이", "description": "a\x00b"}
            ],
        ),
    )

    assert response.status_code == 422
