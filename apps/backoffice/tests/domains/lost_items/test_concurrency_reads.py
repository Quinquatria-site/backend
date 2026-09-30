"""쓰기 transaction과 겹친 GET의 계약.

GET은 쓰기의 잠금을 기다리지 않고 마지막으로 commit된 상태를 돌려준다.
commit 전 변경은 보이지 않고, commit 뒤에는 바로 보인다.
"""

import asyncio

from ._support import URL, body

PROMPTLY = 5
"""GET이 잠금에 막히지 않았다고 볼 상한. 막히면 쓰기가 풀릴 때까지 끝나지 않는다."""


async def _get(api, path: str):
    return await asyncio.wait_for(api.get(path), timeout=PROMPTLY)


async def test_pending_create_is_hidden_until_commit(api, commit_gate) -> None:
    posting = await commit_gate.hold(api.post(URL, json=body()))

    during = await _get(api, URL)
    commit_gate.release()
    created = (await posting).json()
    after = await _get(api, URL)

    assert during.json()["total"] == 0
    assert [item["id"] for item in after.json()["items"]] == [created["id"]]


async def test_pending_update_is_hidden_until_commit(api, commit_gate) -> None:
    created = (await api.post(URL, json=body())).json()
    item = f"{URL}/{created['id']}"

    patching = await commit_gate.hold(
        api.patch(
            item,
            json={
                "is_returned": True,
                "translations": [{"language_code": "EN", "title": "wallet"}],
            },
        )
    )
    during = await _get(api, item)
    commit_gate.release()
    assert (await patching).status_code == 200
    after = await _get(api, item)

    assert during.json() == created
    assert after.json()["is_returned"] is True
    assert [t["language_code"] for t in after.json()["translations"]] == ["EN", "KO"]


async def test_pending_delete_is_hidden_until_commit(api, commit_gate) -> None:
    created = (await api.post(URL, json=body())).json()
    item = f"{URL}/{created['id']}"

    deleting = await commit_gate.hold(api.delete(item))
    during = await _get(api, item)
    commit_gate.release()
    assert (await deleting).status_code == 204
    after = await _get(api, item)

    assert during.status_code == 200
    assert during.json() == created
    assert after.status_code == 404
