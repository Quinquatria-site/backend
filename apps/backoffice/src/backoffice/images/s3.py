"""aioboto3로 구현한 `ObjectStore`.

운영에서는 credential을 넘기지 않는다. workload IAM role의 임시 credential을
기본 탐색 체인이 찾는다. 명시 인자는 서명을 오프라인에서 시험하는 테스트만
쓴다.
"""

from collections.abc import AsyncIterator

import aioboto3
from botocore.exceptions import ClientError

from backoffice.images.store import ObjectHead, ObjectSummary

_MISSING = {"404", "NoSuchKey", "NotFound"}


class S3ObjectStore:
    """단일 bucket에 대한 S3 접근."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._session = aioboto3.Session(
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def _client(self):
        return self._session.client("s3", endpoint_url=self._endpoint_url)

    async def presign_put(self, key: str, *, content_type: str, expires_in: int) -> str:
        """`PutObject` 한 작업과 필수 헤더에만 유효한 URL을 만든다.

        `IfNoneMatch`를 서명 대상에 넣어야 S3가 조건부 쓰기를 강제한다. 빠지면
        같은 key를 덮어쓸 수 있다.
        """
        async with self._client() as s3:
            return await s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ContentType": content_type,
                    "IfNoneMatch": "*",
                },
                ExpiresIn=expires_in,
            )

    async def head(self, key: str) -> ObjectHead | None:
        async with self._client() as s3:
            try:
                response = await s3.head_object(Bucket=self._bucket, Key=key)
            except ClientError as error:
                if error.response["Error"]["Code"] in _MISSING:
                    return None
                raise
        return ObjectHead(
            content_type=response.get("ContentType", ""),
            content_length=int(response["ContentLength"]),
        )

    async def get_range(self, key: str, *, start: int, end: int) -> bytes:
        async with self._client() as s3:
            try:
                response = await s3.get_object(
                    Bucket=self._bucket, Key=key, Range=f"bytes={start}-{end}"
                )
            except ClientError as error:
                if error.response["Error"]["Code"] in _MISSING:
                    return b""
                raise
            async with response["Body"] as body:
                return await body.read()

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def list_prefix(self, prefix: str) -> AsyncIterator[ObjectSummary]:
        async with self._client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for item in page.get("Contents", ()):
                    yield ObjectSummary(
                        key=item["Key"], last_modified=item["LastModified"]
                    )
