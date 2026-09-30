"""같은 분실물의 번역을 동시에 바꿀 때의 계약 (명세 §5.2).

PATCH가 대상 행을 잠그지 않으면 두 요청이 모두 "그 언어 번역 없음"을 보고
insert해 unique 위반이 500으로 새어 나간다. 잠금으로 직렬화하면 뒤에 온
요청은 앞선 번역을 update하고 last-write-wins가 된다.

실행 순서는 `commit_gate`(commit 직전 정지)와 `wait_until_blocked`(DB 잠금
대기 확인)로 고정한다.
"""

import asyncio

from quinquatria_persistence.enums import LanguageCode
from quinquatria_persistence.models import LostItemTranslation

from ._support import URL, body, ko, stored_translations, wait_until_blocked


def en(title: str) -> dict[str, object]:
    return {"translations": [{"language_code": "EN", "title": title}]}


async def test_patch_adding_a_language_waits_for_a_pending_insert(
    api, database
) -> None:
    created = (await api.post(URL, json=body())).json()

    async with database.transaction() as pending:
        pending.add(
            LostItemTranslation(
                lost_item_id=created["id"],
                language_code=LanguageCode.EN,
                title="first",
            )
        )
        await pending.flush()
        patching = asyncio.create_task(
            api.patch(f"{URL}/{created['id']}", json=en("second"))
        )
        await wait_until_blocked(database)

    response = await patching
    assert response.status_code == 200
    english = [t for t in response.json()["translations"] if t["language_code"] == "EN"]
    assert [t["title"] for t in english] == ["second"]
    assert await stored_translations(database, created["id"]) == [
        ("EN", "second"),
        ("KO", "지갑"),
    ]


async def test_two_patches_adding_the_same_language_end_last_write_wins(
    api, database, commit_gate
) -> None:
    created = (await api.post(URL, json=body())).json()
    item = f"{URL}/{created['id']}"

    first = await commit_gate.hold(api.patch(item, json=en("first")))
    second = asyncio.create_task(api.patch(item, json=en("second")))
    await wait_until_blocked(database)
    commit_gate.release()
    first, second = await asyncio.gather(first, second)

    assert (first.status_code, second.status_code) == (200, 200)
    assert await stored_translations(database, created["id"]) == [
        ("EN", "second"),
        ("KO", "지갑"),
    ]


async def test_translation_delete_after_a_pending_upsert_removes_it(
    api, database, commit_gate
) -> None:
    created = (await api.post(URL, json=body())).json()
    item = f"{URL}/{created['id']}"

    patching = await commit_gate.hold(api.patch(item, json=en("wallet")))
    deleting = asyncio.create_task(api.delete(f"{item}/translations/EN"))
    await wait_until_blocked(database)
    commit_gate.release()
    patched, deleted = await asyncio.gather(patching, deleting)

    assert (patched.status_code, deleted.status_code) == (200, 204)
    assert await stored_translations(database, created["id"]) == [("KO", "지갑")]


async def test_upsert_after_a_pending_translation_delete_inserts_again(
    api, database, commit_gate
) -> None:
    """DELETE가 소유자를 잠그지 않으면 PATCH가 지워질 행을 update해 500이 된다."""
    created = (
        await api.post(URL, json=body(translations=[ko(), *en("old")["translations"]]))
    ).json()
    item = f"{URL}/{created['id']}"

    deleting = await commit_gate.hold(api.delete(f"{item}/translations/EN"))
    patching = asyncio.create_task(api.patch(item, json=en("new")))
    await wait_until_blocked(database)
    commit_gate.release()
    deleted, patched = await asyncio.gather(deleting, patching)

    assert (deleted.status_code, patched.status_code) == (204, 200)
    english = [t for t in patched.json()["translations"] if t["language_code"] == "EN"]
    assert [t["title"] for t in english] == ["new"]
    assert await stored_translations(database, created["id"]) == [
        ("EN", "new"),
        ("KO", "지갑"),
    ]
