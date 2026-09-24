"""같은 분실물에 번역을 동시에 추가할 때의 계약 (명세 §5.2).

PATCH가 대상 행을 잠그지 않으면 두 요청이 모두 "그 언어 번역 없음"을 보고
insert해 unique 위반이 500으로 새어 나간다. 잠금으로 직렬화하면 뒤에 온
요청은 앞선 번역을 update하고 last-write-wins가 된다.
"""

import asyncio

from quinquatria_persistence.enums import LanguageCode
from quinquatria_persistence.models import LostItemTranslation

from ._support import URL, body

BLOCKED_FOR = 0.5
"""앞선 transaction이 끝나기 전에 PATCH가 출발하도록 두는 시간."""


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
            api.patch(
                f"{URL}/{created['id']}",
                json={"translations": [{"language_code": "EN", "title": "second"}]},
            )
        )
        await asyncio.sleep(BLOCKED_FOR)

    response = await patching
    assert response.status_code == 200
    english = [t for t in response.json()["translations"] if t["language_code"] == "EN"]
    assert [t["title"] for t in english] == ["second"]
