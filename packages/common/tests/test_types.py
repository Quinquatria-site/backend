from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import BaseModel, ValidationError

from backend.packages.common.src.common.types import AwareDatetime, Price, ResourceId


class _Model(BaseModel):
    resource_id: ResourceId
    price: Price
    moment: AwareDatetime


def _model(**overrides: object) -> _Model:
    values: dict[str, object] = {
        "resource_id": 1,
        "price": 0,
        "moment": "2026-10-06T18:00:00+09:00",
    }
    return _Model(**(values | overrides))


def test_resource_id_accepts_one() -> None:
    assert _model(resource_id=1).resource_id == 1


def test_resource_id_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        _model(resource_id=0)


def test_resource_id_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        _model(resource_id=-1)


def test_price_accepts_zero() -> None:
    assert _model(price=0).price == 0


def test_price_rejects_negative() -> None:
    with pytest.raises(ValidationError):
        _model(price=-1)


def test_datetime_accepts_offset_string() -> None:
    kst = timezone(timedelta(hours=9))

    assert _model().moment == datetime(2026, 10, 6, 18, 0, tzinfo=kst)


def test_datetime_rejects_naive_string() -> None:
    with pytest.raises(ValidationError):
        _model(moment="2026-10-06T18:00:00")


def test_datetime_accepts_utc() -> None:
    assert _model(moment="2026-10-06T09:00:00Z").moment == datetime(
        2026, 10, 6, 9, 0, tzinfo=UTC
    )


def test_datetime_serializes_with_offset() -> None:
    assert '"moment":"2026-10-06T18:00:00+09:00"' in _model().model_dump_json()
