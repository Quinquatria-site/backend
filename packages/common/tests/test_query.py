import pytest
from pydantic import ValidationError

from common.enums import LanguageCode
from common.query import LanguageQuery, ListQuery, NoQuery, PageQuery


def test_list_query_defaults_match_the_spec() -> None:
    query = ListQuery()

    assert query.language_code is LanguageCode.KO
    assert query.page == 1
    assert query.size == 20


def test_language_query_defaults_to_korean() -> None:
    assert LanguageQuery().language_code is LanguageCode.KO


def test_list_query_accepts_the_size_boundaries() -> None:
    assert ListQuery(size=1).size == 1
    assert ListQuery(size=100).size == 100


def test_list_query_rejects_page_below_one() -> None:
    with pytest.raises(ValidationError):
        ListQuery(page=0)


def test_list_query_rejects_size_above_one_hundred() -> None:
    with pytest.raises(ValidationError):
        ListQuery(size=101)


def test_list_query_rejects_size_below_one() -> None:
    with pytest.raises(ValidationError):
        ListQuery(size=0)


def test_language_code_is_case_sensitive() -> None:
    with pytest.raises(ValidationError):
        ListQuery(language_code="ko")


@pytest.mark.parametrize("model", [NoQuery, LanguageQuery, PageQuery, ListQuery])
def test_every_query_model_forbids_unknown_parameters(model: type) -> None:
    with pytest.raises(ValidationError):
        model(unknown="1")


def test_no_query_accepts_nothing_and_stays_empty() -> None:
    assert NoQuery().model_dump() == {}


def test_page_query_has_no_language_code() -> None:
    assert "language_code" not in PageQuery.model_fields


def test_subclass_inherits_the_forbid_rule() -> None:
    class PlaceListQuery(ListQuery):
        category_id: int | None = None

    assert PlaceListQuery(category_id=1).category_id == 1
    with pytest.raises(ValidationError):
        PlaceListQuery(unknown="1")
