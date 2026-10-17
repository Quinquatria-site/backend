"""cleanup 결과를 CloudWatch Embedded Metric Format(EMF) 레코드로 만든다.

이 레코드를 CloudWatch Logs에 한 줄로 보내면 로그로 남는 동시에 지표가
추출된다. 전송은 실행 환경이 맡고, 이 모듈은 AWS SDK에 의존하지 않는다.
"""

from datetime import datetime
from typing import Any

from backoffice.images.cleanup import StorageReport, SweepReport

NAMESPACE = "Quinquatria/ImageCleanup"
DIMENSION = "Bucket"

_UNITS = {
    "Deleted": "Count",
    "Orphans": "Count",
    "Failed": "Count",
    "ReclaimedBytes": "Bytes",
    "StoredObjects": "Count",
    "StoredBytes": "Bytes",
    "TrashObjects": "Count",
    "TrashBytes": "Bytes",
}


def emf_record(
    sweep: SweepReport, storage: StorageReport, *, bucket: str, now: datetime
) -> dict[str, Any]:
    values = {
        "Deleted": sweep.deleted,
        "Orphans": sweep.orphans,
        "Failed": sweep.failed,
        "ReclaimedBytes": sweep.reclaimed_bytes,
        "StoredObjects": storage.stored_objects,
        "StoredBytes": storage.stored_bytes,
        "TrashObjects": storage.trash_objects,
        "TrashBytes": storage.trash_bytes,
    }
    return {
        "_aws": {
            "Timestamp": int(now.timestamp() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [[DIMENSION]],
                    "Metrics": [
                        {"Name": name, "Unit": unit} for name, unit in _UNITS.items()
                    ],
                }
            ],
        },
        DIMENSION: bucket,
        **values,
    }
