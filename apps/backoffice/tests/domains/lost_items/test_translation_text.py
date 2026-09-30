"""명세 §2.2 번역 텍스트 규칙이 분실물 라우트와 DB 왕복에서 지켜지는지."""

import json

import pytest

from ._support import URL, body, ko

EMOJI = "🎉 👨\u200d👩\u200d👧 ❤\ufe0f 🇰🇷"


async def test_round_trips_trimmed_emoji_and_description_line_breaks(api) -> None:
    description = f"{EMOJI}\n검정색\t가죽"
    created = await api.post(
        URL,
        json=body(
            translations=[
                ko(
                    f" {EMOJI} 지갑 ",
                    description=f"  {description}\n",
                    found_location=f"\u3000{EMOJI} 본관 1층 ",
                )
            ]
        ),
    )
    assert created.status_code == 201, created.text

    response = await api.get(f"{URL}/{created.json()['id']}")

    translation = response.json()["translations"][0]
    assert translation["title"] == f"{EMOJI} 지갑"
    assert translation["description"] == description
    assert translation["found_location"] == f"{EMOJI} 본관 1층"


async def test_blank_optional_fields_become_empty(api) -> None:
    created = await api.post(
        URL, json=body(translations=[ko(description="  ", found_location="\t")])
    )

    assert created.status_code == 201, created.text
    translation = created.json()["translations"][0]
    assert translation["description"] == ""
    assert translation["found_location"] == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", ""),
        ("title", "   "),
        ("title", "지\n갑"),
        ("title", "지갑\x00"),
        ("found_location", "본관\n1층"),
        ("found_location", "본관\x00"),
        ("description", "설명\x00"),
        ("description", "설명\x7f"),
    ],
)
async def test_create_rejects_invalid_text(api, field, value) -> None:
    translation = ko() | {field: value}

    response = await api.post(URL, json=body(translations=[translation]))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_create_rejects_lone_surrogate(api) -> None:
    raw = json.dumps(body(translations=[ko("\ud83d")]), ensure_ascii=True).encode()

    response = await api.post(
        URL, content=raw, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


async def test_patch_rejects_blank_title(api) -> None:
    created = await api.post(URL, json=body())

    response = await api.patch(
        f"{URL}/{created.json()['id']}",
        json={"translations": [{"language_code": "EN", "title": " "}]},
    )

    assert response.status_code == 422
