"""분실물 요청끼리 이미지를 두고 겹칠 때의 계약 (명세 §4.6).

이미지는 분실물 하나에만 붙고, 경쟁에서 진 요청은 500이 아니라 409
`IMAGE_ALREADY_ATTACHED`를 받는다. 분실물이 사라지면 그 이미지는 참조 없이
`ATTACHED`로 남지 않고 `DETACHED`가 되어 cleanup 대상이 된다.
"""

import asyncio

from sqlalchemy import select

from backoffice.crud.images import replace_image
from backoffice.domains.lost_items import routes
from quinquatria_persistence.enums import ImageStatus
from quinquatria_persistence.models import Image, LostItem

from ._support import (
    URL,
    attached_orphans,
    body,
    image_status,
    seed_image,
    wait_until_blocked,
)


async def _lost_item_images(database) -> list[str | None]:
    async with database.session() as session:
        rows = await session.scalars(
            select(Image.s3_key)
            .select_from(LostItem)
            .outerjoin(Image, Image.id == LostItem.image_id)
            .order_by(LostItem.id)
        )
        return list(rows)


async def test_two_posts_with_the_same_image_attach_it_once(
    api, database, object_store, commit_gate
) -> None:
    key = await seed_image(database, object_store, "a")

    first = await commit_gate.hold(api.post(URL, json=body(image_url=key)))
    second = asyncio.create_task(api.post(URL, json=body(image_url=key)))
    await wait_until_blocked(database)
    commit_gate.release()
    first, second = await asyncio.gather(first, second)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "IMAGE_ALREADY_ATTACHED"
    assert await _lost_item_images(database) == [key]
    assert await image_status(database, key) is ImageStatus.ATTACHED


async def test_patch_racing_a_post_for_the_same_image_is_rejected(
    api, database, object_store, commit_gate
) -> None:
    key = await seed_image(database, object_store, "a")
    existing = (await api.post(URL, json=body())).json()

    posting = await commit_gate.hold(api.post(URL, json=body(image_url=key)))
    patching = asyncio.create_task(
        api.patch(f"{URL}/{existing['id']}", json={"image_url": key})
    )
    await wait_until_blocked(database)
    commit_gate.release()
    posted, patched = await asyncio.gather(posting, patching)

    assert posted.status_code == 201
    assert patched.status_code == 409
    assert patched.json()["code"] == "IMAGE_ALREADY_ATTACHED"
    assert await _lost_item_images(database) == [None, key]
    assert await image_status(database, key) is ImageStatus.ATTACHED


async def test_delete_after_a_pending_image_replace_detaches_the_new_image(
    api, database, object_store, commit_gate
) -> None:
    first = await seed_image(database, object_store, "a")
    second = await seed_image(database, object_store, "b")
    created = (await api.post(URL, json=body(image_url=first))).json()
    item = f"{URL}/{created['id']}"

    patching = await commit_gate.hold(api.patch(item, json={"image_url": second}))
    deleting = asyncio.create_task(api.delete(item))
    await wait_until_blocked(database)
    commit_gate.release()
    patched, deleted = await asyncio.gather(patching, deleting)

    assert (patched.status_code, deleted.status_code) == (200, 204)
    assert await _lost_item_images(database) == []
    assert await image_status(database, first) is ImageStatus.DETACHED
    assert await image_status(database, second) is ImageStatus.DETACHED
    assert await attached_orphans(database) == 0


async def test_delete_releases_the_image_a_concurrent_patch_attached(
    api, database, object_store, monkeypatch
) -> None:
    """DELETE가 `image_id`를 읽은 뒤 PATCH가 이미지를 바꿔도 고아가 남지 않는다.

    DELETE가 행을 잠그지 않으면 PATCH가 A→B를 commit하고, DELETE는 읽어 둔
    A만 해제해 B가 참조 없이 `ATTACHED`로 남는다. cleanup은 이를 회수하지 않는다.
    그 틈을 재현하려면 commit 직전이 아니라 `image_id`를 읽은 직후에 멈춰야 한다.
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
    await wait_until_blocked(database)
    resume.set()
    deleted, patched = await asyncio.gather(deleting, patching)

    assert deleted.status_code == 204
    assert patched.status_code == 404
    assert await _lost_item_images(database) == []
    assert await image_status(database, first) is ImageStatus.DETACHED
    assert await image_status(database, second) is ImageStatus.UPLOADING
    assert await attached_orphans(database) == 0
