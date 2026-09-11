import pytest
from pydantic import BaseModel, ValidationError

from common.pagination import Page


class _Item(BaseModel):
    id: int
    name: str


def test_serializes_to_the_spec_shape() -> None:
    page = Page[_Item](
        items=[_Item(id=1, name="주점")],
        page=1,
        size=20,
        total=1,
    )

    assert page.model_dump() == {
        "items": [{"id": 1, "name": "주점"}],
        "page": 1,
        "size": 20,
        "total": 1,
    }


def test_empty_page_keeps_every_field() -> None:
    assert Page[_Item](items=[], page=3, size=20, total=0).model_dump() == {
        "items": [],
        "page": 3,
        "size": 20,
        "total": 0,
    }


def test_field_order_matches_the_spec() -> None:
    page = Page[_Item](items=[], page=1, size=20, total=0)

    assert list(page.model_dump()) == ["items", "page", "size", "total"]


def test_is_generic_over_the_item_type() -> None:
    assert Page[int](items=[1, 2], page=1, size=20, total=2).items == [1, 2]


def test_rejects_page_below_one() -> None:
    with pytest.raises(ValidationError):
        Page[int](items=[], page=0, size=20, total=0)


def test_rejects_negative_total() -> None:
    with pytest.raises(ValidationError):
        Page[int](items=[], page=1, size=20, total=-1)


def test_rejects_size_above_the_maximum() -> None:
    with pytest.raises(ValidationError):
        Page[int](items=[], page=1, size=101, total=0)
