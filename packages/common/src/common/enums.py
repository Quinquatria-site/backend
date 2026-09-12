"""API 명세 §2.3이 정의한 공통 enum.

허용값은 대소문자를 구분한다. 다른 값은 호출부에서 422 VALIDATION_ERROR로
처리한다.
"""

from enum import StrEnum


class LanguageCode(StrEnum):
    KO = "KO"
    EN = "EN"
    CHN = "CHN"


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
