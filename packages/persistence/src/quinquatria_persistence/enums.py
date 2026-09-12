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
