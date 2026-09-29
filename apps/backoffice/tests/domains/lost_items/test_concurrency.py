"""같은 분실물에 번역을 동시에 추가할 때의 계약 (명세 §5.2).

PATCH가 대상 행을 잠그지 않으면 두 요청이 모두 "그 언어 번역 없음"을 보고
insert해 unique 위반이 500으로 새어 나간다. 잠금으로 직렬화하면 뒤에 온
요청은 앞선 번역을 update하고 last-write-wins가 된다.
"""

import asyncio

from sqlalchemy import func, select

from backoffice.crud.images import replace_image
from backoffice.domains.lost_items import routes
from quinquatria_persistence.enums import ImageStatus, LanguageCode
from quinquatria_persistence.models import Image, LostItem, LostItemTranslation

from ._support import URL, body, image_status, seed_image

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


async def test_delete_releases_the_image_a_concurrent_patch_attached(
    api, database, object_store, monkeypatch
) -> None:
    """DELETE가 `image_id`를 읽은 뒤 PATCH가 이미지를 바꿔도 고아가 남지 않는다.

    DELETE가 행을 잠그지 않으면 PATCH가 A→B를 commit하고, DELETE는 읽어 둔
    A만 해제해 B가 참조 없이 `ATTACHED`로 남는다. cleanup은 이를 회수하지 않는다.
    """
    first = await seed_image(database, object_store, "a")
    second = await seed_image(database, object_store, "b")
    created = (await api.post(URL, json=body(image_url=first))).json()

    read = asyncio.Event()
    resume = asyncio.Event()

    async def pausing(session, store, *, object_key, **kwargs):
        if object_key is None:
            read.set()
            await resume.wait()
        return await replace_image(session, store, object_key=object_key, **kwargs)

    monkeypatch.setattr(routes, "replace_image", pausing)
    deleting = asyncio.create_task(api.delete(f"{URL}/{created['id']}"))
    await asyncio.wait_for(read.wait(), timeout=5)
    patching = asyncio.create_task(
        api.patch(f"{URL}/{created['id']}", json={"image_url": second})
    )
    await asyncio.wait({patching}, timeout=BLOCKED_FOR)
    resume.set()
    deleted, patched = await asyncio.gather(deleting, patching)

    assert deleted.status_code == 204
    assert patched.status_code == 404
    assert await image_status(database, first) is ImageStatus.DETACHED
    assert await image_status(database, second) is ImageStatus.UPLOADING
    async with database.session() as session:
        orphans = await session.scalar(
            select(func.count())
            .select_from(Image)
            .where(Image.status == ImageStatus.ATTACHED)
            .where(
                ~Image.id.in_(
                    select(LostItem.image_id).where(LostItem.image_id.is_not(None))
                )
            )
        )
    assert orphans == 0
