"""object key는 서버만 만든다.

client가 파일명이나 key를 정할 수 있으면 prefix 최소 권한과 용도별 분리가
무의미해진다. 명세 §4.5는 원본 파일명을 아예 받지 않는다.
"""

from uuid import UUID

import pytest

from backoffice.images.keys import (
    EXTENSIONS,
    PREFIXES,
    build_object_key,
    matches_prefix,
)
from quinquatria_persistence.enums import ImageContentType, ImageResourceType


@pytest.mark.parametrize(
    ("resource_type", "prefix"),
    [
        (ImageResourceType.CATEGORY_ICON, "images/category/"),
        (ImageResourceType.PLACE_IMAGE, "images/place/"),
        (ImageResourceType.MENU_IMAGE, "images/menu/"),
        (ImageResourceType.PERFORMANCE_IMAGE, "images/performance/"),
        (ImageResourceType.LOST_ITEM_IMAGE, "images/lost-item/"),
    ],
)
def test_prefixes_follow_the_spec(
    resource_type: ImageResourceType, prefix: str
) -> None:
    assert PREFIXES[resource_type] == prefix


@pytest.mark.parametrize(
    ("content_type", "extension"),
    [
        (ImageContentType.JPEG, ".jpg"),
        (ImageContentType.PNG, ".png"),
        (ImageContentType.WEBP, ".webp"),
    ],
)
def test_extensions_follow_the_content_type(
    content_type: ImageContentType, extension: str
) -> None:
    assert EXTENSIONS[content_type] == extension


def test_every_resource_type_has_a_prefix() -> None:
    assert set(PREFIXES) == set(ImageResourceType)


def test_every_content_type_has_an_extension() -> None:
    assert set(EXTENSIONS) == set(ImageContentType)


def test_key_is_prefix_plus_uuid_plus_extension() -> None:
    key = build_object_key(ImageResourceType.PLACE_IMAGE, ImageContentType.WEBP)

    assert key.startswith("images/place/")
    assert key.endswith(".webp")
    UUID(key.removeprefix("images/place/").removesuffix(".webp"))


def test_keys_do_not_repeat() -> None:
    keys = {
        build_object_key(ImageResourceType.MENU_IMAGE, ImageContentType.PNG)
        for _ in range(100)
    }

    assert len(keys) == 100


def test_matching_prefix_is_accepted() -> None:
    key = build_object_key(ImageResourceType.MENU_IMAGE, ImageContentType.PNG)

    assert matches_prefix(key, ImageResourceType.MENU_IMAGE)


def test_prefix_from_another_resource_is_rejected() -> None:
    key = build_object_key(ImageResourceType.MENU_IMAGE, ImageContentType.PNG)

    assert not matches_prefix(key, ImageResourceType.PLACE_IMAGE)


@pytest.mark.parametrize(
    "key",
    [
        "images/place/../menu/escape.webp",
        "/images/place/leading-slash.webp",
        "images/place2/near-miss.webp",
        "",
    ],
)
def test_crafted_keys_do_not_pass_as_place_images(key: str) -> None:
    """연결 단계에서 손으로 만든 key가 prefix 검사를 통과하면 안 된다."""
    assert not matches_prefix(key, ImageResourceType.PLACE_IMAGE)
