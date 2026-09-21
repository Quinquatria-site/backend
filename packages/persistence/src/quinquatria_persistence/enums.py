"""Case-sensitive values shared by PostgreSQL models and API consumers."""

from enum import StrEnum


class LanguageCode(StrEnum):
    # Native PostgreSQL enums sort by declaration order.
    CHN = "CHN"
    EN = "EN"
    KO = "KO"


class CategoryCode(StrEnum):
    PUB = "PUB"
    BOOTH = "BOOTH"
    FOODTRUCK = "FOODTRUCK"
    MEDI = "MEDI"
    BRACELET = "BRACELET"


class PerformanceType(StrEnum):
    ARTIST = "ARTIST"
    STUDENT = "STUDENT"
    SPECIAL = "SPECIAL"


class NoticeType(StrEnum):
    PERMANENT = "PERMANENT"
    GENERAL = "GENERAL"


class ImageResourceType(StrEnum):
    CATEGORY_ICON = "CATEGORY_ICON"
    PLACE_IMAGE = "PLACE_IMAGE"
    MENU_IMAGE = "MENU_IMAGE"
    PERFORMANCE_IMAGE = "PERFORMANCE_IMAGE"
    LOST_ITEM_IMAGE = "LOST_ITEM_IMAGE"


class ImageContentType(StrEnum):
    # 값이 식별자가 될 수 없는 MIME 문자열이라, 이 enum을 쓰는 컬럼은
    # `values_callable`로 값을 저장하게 해야 한다. 기본값은 멤버 이름이다.
    JPEG = "image/jpeg"
    PNG = "image/png"
    WEBP = "image/webp"


class ImageStatus(StrEnum):
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    ATTACHED = "ATTACHED"
    DETACHED = "DETACHED"
