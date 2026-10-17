"""cleanup 결과를 CloudWatch Embedded Metric Format(EMF) 레코드로 바꾼다.

CloudWatch Logs는 `_aws` 메타데이터가 붙은 JSON 로그에서 지표를 자동으로
뽑는다. 형식이 어긋나면 로그만 남고 지표가 생기지 않으므로 구조를 고정한다.
"""

import json
from datetime import UTC, datetime

from backoffice.images.cleanup import StorageReport, SweepReport
from backoffice.images.metrics import NAMESPACE, emf_record

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
SWEEP = SweepReport(deleted=2, failed=1, orphans=3, reclaimed_bytes=4096)
STORAGE = StorageReport(
    stored_objects=10, stored_bytes=50_000, trash_objects=4, trash_bytes=8_000
)


def _record() -> dict:
    return emf_record(SWEEP, STORAGE, bucket="example-bucket", now=NOW)


def test_record_declares_metrics_under_the_cleanup_namespace() -> None:
    directive = _record()["_aws"]["CloudWatchMetrics"][0]

    assert directive["Namespace"] == NAMESPACE
    assert directive["Dimensions"] == [["Bucket"]]
    assert {metric["Name"]: metric["Unit"] for metric in directive["Metrics"]} == {
        "Deleted": "Count",
        "Orphans": "Count",
        "Failed": "Count",
        "ReclaimedBytes": "Bytes",
        "StoredObjects": "Count",
        "StoredBytes": "Bytes",
        "TrashObjects": "Count",
        "TrashBytes": "Bytes",
    }


def test_record_carries_values_and_dimension_at_the_top_level() -> None:
    record = _record()

    assert record["Bucket"] == "example-bucket"
    assert record["Deleted"] == 2
    assert record["Orphans"] == 3
    assert record["Failed"] == 1
    assert record["ReclaimedBytes"] == 4096
    assert record["StoredObjects"] == 10
    assert record["StoredBytes"] == 50_000
    assert record["TrashObjects"] == 4
    assert record["TrashBytes"] == 8_000


def test_record_timestamp_is_epoch_milliseconds() -> None:
    assert _record()["_aws"]["Timestamp"] == int(NOW.timestamp() * 1000)


def test_record_is_json_serializable() -> None:
    assert json.loads(json.dumps(_record())) == _record()
