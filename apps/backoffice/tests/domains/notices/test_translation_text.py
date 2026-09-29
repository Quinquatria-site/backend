"""명세 §2.2 번역 텍스트 규칙이 공지 라우트와 DB 왕복에서 지켜지는지."""

import json

import pytest
from httpx import AsyncClient

EMOJI = "🎉 👨\u200d👩\u200d👧 ❤\ufe0f 🇰🇷"
URL = "/api/v1/notices"


def _body(**fields: str) -> dict:
    translation = {"language_code": "KO", "title": "안전 수칙", "content": "안내"}
    return {"type": "GENERAL", "translations": [translation | fields]}


async def test_round_trips_trimmed_emoji_and_content_line_breaks(
    api: AsyncClient,
) -> None:
    content = f"{EMOJI}\n\n1. 줄서기\r\n\t2. 안전"
    created = await api.post(
        URL, json=_body(title=f" {EMOJI} 공지\u3000", content=f"  {content}\n")
    )
    assert created.status_code == 201, created.text

    response = await api.get(f"{URL}/{created.json()['id']}")

    translation = response.json()["translations"][0]
    assert translation["title"] == f"{EMOJI} 공지"
    assert translation["content"] == content


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", ""),
        ("title", " \t "),
        ("title", "공지\n제목"),
        ("title", "공지\x00"),
        ("content", ""),
        ("content", "\n\n"),
        ("content", "본문\x00"),
        ("content", "본문\x1b[2J"),
    ],
)
async def test_create_rejects_invalid_text(api: AsyncClient, field, value) -> None:
    response = await api.post(URL, json=_body(**{field: value}))

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_create_rejects_lone_surrogate(api: AsyncClient) -> None:
    raw = json.dumps(_body(content="\ud83d"), ensure_ascii=True).encode()

    response = await api.post(
        URL, content=raw, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


async def test_patch_rejects_blank_content(api: AsyncClient) -> None:
    created = await api.post(URL, json=_body())

    response = await api.patch(
        f"{URL}/{created.json()['id']}",
        json={"translations": [{"language_code": "EN", "title": "T", "content": " "}]},
    )

    assert response.status_code == 422
