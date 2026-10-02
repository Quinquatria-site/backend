"""카테고리 번역 삭제 (명세 §5.2). 카테고리 자체는 삭제하지 않는다 (§6)."""

from ._helpers import seeded_category


async def test_delete_translation_removes_only_that_language(api) -> None:
    created = await seeded_category(api)

    response = await api.delete(f"/api/v1/categories/{created['id']}/translations/EN")

    assert response.status_code == 204
    assert response.content == b""
    assert "content-type" not in response.headers
    body = (await api.get(f"/api/v1/categories/{created['id']}")).json()
    assert [row["language_code"] for row in body["translations"]] == ["CHN", "KO"]


async def test_delete_ko_translation_is_conflict(api) -> None:
    created = await seeded_category(api)

    response = await api.delete(f"/api/v1/categories/{created['id']}/translations/KO")

    assert response.status_code == 409
    assert response.json()["code"] == "DELETE_CONFLICT"


async def test_delete_absent_translation_is_404(api) -> None:
    created = await seeded_category(api)
    await api.delete(f"/api/v1/categories/{created['id']}/translations/CHN")

    response = await api.delete(f"/api/v1/categories/{created['id']}/translations/CHN")

    assert response.status_code == 404


async def test_delete_translation_of_missing_category_is_404(api) -> None:
    response = await api.delete("/api/v1/categories/999/translations/EN")

    assert response.status_code == 404
