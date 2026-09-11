import pytest
from pydantic import BaseModel, ValidationError

from backend.packages.common.src.common.enums import CategoryCode, LanguageCode, NoticeType, PerformanceType


def test_language_code_members() -> None:
    assert [member.value for member in LanguageCode] == ["KO", "EN", "CHN"]


def test_category_code_members() -> None:
    assert [member.value for member in CategoryCode] == [
        "PUB",
        "BOOTH",
        "FOODTRUCK",
        "MEDI",
        "BRACELET",
    ]


def test_performance_type_members() -> None:
    assert [member.value for member in PerformanceType] == [
        "ARTIST",
        "STUDENT",
        "SPECIAL",
    ]


def test_notice_type_members() -> None:
    assert [member.value for member in NoticeType] == ["PERMANENT", "GENERAL"]


def test_enum_compares_equal_to_its_string_value() -> None:
    assert LanguageCode.KO == "KO"


class _Model(BaseModel):
    language_code: LanguageCode


def test_validation_accepts_exact_uppercase_value() -> None:
    assert _Model(language_code="EN").language_code is LanguageCode.EN


def test_validation_rejects_lowercase_value() -> None:
    with pytest.raises(ValidationError):
        _Model(language_code="ko")


def test_serializes_to_plain_string() -> None:
    assert _Model(language_code=LanguageCode.CHN).model_dump() == {
        "language_code": "CHN"
    }
