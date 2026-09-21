"""object key와 용도 사이의 매핑.

I/O가 없는 순수 함수만 둔다. key는 서버가 UUID로 만들며 client 입력이 섞이지
않는다. 파일명을 받으면 확장자 스푸핑과 경로 조작의 입구가 생긴다.
"""

from uuid import uuid4

from quinquatria_persistence.enums import ImageContentType, ImageResourceType

PREFIXES: dict[ImageResourceType, str] = {
    ImageResourceType.CATEGORY_ICON: "images/category/",
    ImageResourceType.PLACE_IMAGE: "images/place/",
    ImageResourceType.MENU_IMAGE: "images/menu/",
    ImageResourceType.PERFORMANCE_IMAGE: "images/performance/",
    ImageResourceType.LOST_ITEM_IMAGE: "images/lost-item/",
}
"""명세 §4.5의 resource_type과 prefix 매핑. IAM 최소 권한이 이 경계를 쓴다."""

EXTENSIONS: dict[ImageContentType, str] = {
    ImageContentType.JPEG: ".jpg",
    ImageContentType.PNG: ".png",
    ImageContentType.WEBP: ".webp",
}


def build_object_key(
    resource_type: ImageResourceType, content_type: ImageContentType
) -> str:
    """용도별 prefix 아래에 UUID 이름으로 key를 만든다."""
    return f"{PREFIXES[resource_type]}{uuid4()}{EXTENSIONS[content_type]}"


def matches_prefix(object_key: str, resource_type: ImageResourceType) -> bool:
    """key가 그 용도의 prefix 바로 아래에 있는지 본다.

    `startswith`만으로는 `images/place/../menu/x`처럼 상위로 빠져나가는 key가
    통과하므로, 남은 부분에 구분자가 더 없는지도 확인한다.
    """
    prefix = PREFIXES[resource_type]
    if not object_key.startswith(prefix):
        return False
    name = object_key[len(prefix) :]
    return bool(name) and "/" not in name and ".." not in name
