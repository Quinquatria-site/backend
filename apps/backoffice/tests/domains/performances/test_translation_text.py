"""명세 §2.2 번역 텍스트 규칙이 공연 라우트와 DB 왕복에서 지켜지는지."""

import json

import pytest

from ._support import body, create

EMOJI = "🎉 👨\u200d👩\u200d👧 ❤\ufe0f 🇰🇷"


async def test_round_trips_trimmed_emoji_and_description_line_breaks(api) -> None:
    description = f"{EMOJI}\n둘째 줄\t탭"
    created = await create(
        api,
        translations=[
            {
                "language_code": "KO",
                "title": f"  {EMOJI} 공연 ",
                "description": f"\n{description}  ",
            }
        ],
    )

    response = await api.get(f"/api/v1/performances/{created['id']}")

    translation = response.json()["translations"][0]
    assert translation["title"] == f"{EMOJI} 공연"
    assert translation["description"] == description


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", ""),
        ("title", "  "),
        ("title", "공연\n제목"),
        ("title", "공연\x00"),
        ("description", "설명\x00"),
        ("description", "설명\x07"),
    ],
)
async def test_create_rejects_invalid_text(api, field, value) -> None:
    translation = {"language_code": "KO", "title": "공연"} | {field: value}

    response = await api.post(
        "/api/v1/performances", json=body(translations=[translation])
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_create_rejects_lone_surrogate(api) -> None:
    raw = json.dumps(body("\udc00"), ensure_ascii=True).encode()

    response = await api.post(
        "/api/v1/performances",
        content=raw,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


async def test_patch_rejects_blank_title(api) -> None:
    created = await create(api)

    response = await api.patch(
        f"/api/v1/performances/{created['id']}",
        json={"translations": [{"language_code": "EN", "title": "\u3000"}]},
    )

    assert response.status_code == 422
