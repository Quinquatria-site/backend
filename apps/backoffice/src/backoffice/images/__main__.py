"""cleanup을 한 번 실행하는 진입점.

실행 주기는 코드에 넣지 않는다. 배포 환경의 스케줄러가 정하며 계약은
`docs/deploy/s3-image-storage.md`에 있다. API 프로세스와 분리돼 있어
인스턴스가 여러 개여도 중복 실행이 해롭지 않다.
"""

import asyncio
import logging
from datetime import UTC, datetime

from backoffice.config import get_settings
from backoffice.images.cleanup import sweep
from backoffice.images.masking import suppress_sdk_signature_logs
from backoffice.images.s3 import S3ObjectStore
from quinquatria_persistence import Database


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # basicConfig 뒤에 건다. 스케줄러가 레벨을 DEBUG로 올려도 서명은 안 남는다.
    suppress_sdk_signature_logs()
    settings = get_settings()
    database = Database(settings.database_url)
    store = S3ObjectStore(
        bucket=settings.s3_bucket,
        region=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
    )
    try:
        report = await sweep(
            database,
            store,
            now=datetime.now(UTC),
            grace_seconds=settings.cleanup_grace_seconds,
            batch_size=settings.cleanup_batch_size,
        )
        logging.getLogger(__name__).info(
            "cleanup 완료: deleted=%s failed=%s orphans=%s",
            report.deleted,
            report.failed,
            report.orphans,
        )
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
