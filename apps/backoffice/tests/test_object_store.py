"""서명 조건은 실제 botocore signer로 검증한다.

presigned URL 생성은 네트워크 호출이 아니므로, 더미 credential만 있으면
오프라인에서 진짜 서명을 만들 수 있다. 서명 조건이 명세와 어긋나면 S3가
403을 돌려주고 업로드가 통째로 막히므로 페이크로 대신하지 않는다.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from backoffice.images.s3 import S3ObjectStore
from backoffice.images.store import ObjectSummary

from ._images import FakeObjectStore, put_object

BUCKET = "quinquatria-test"
REGION = "ap-northeast-2"
KEY = "images/place/example.webp"


def build_store(region: str) -> S3ObjectStore:
    # 정적 키를 설정에 두지 않는다는 규칙은 운영 코드에만 적용된다.
    # 테스트는 서명을 만들기 위해 더미 credential을 명시로 주입한다.
    return S3ObjectStore(
        bucket=BUCKET,
        region=region,
        access_key_id="AKIAIOSFODNN7EXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )


@pytest.fixture
def store() -> S3ObjectStore:
    return build_store(REGION)


async def test_presigned_url_points_at_the_requested_key(store: S3ObjectStore) -> None:
    url = await store.presign_put(KEY, content_type="image/webp", expires_in=300)

    assert urlparse(url).path.endswith(KEY)


async def test_presigned_url_expires_in_five_minutes(store: S3ObjectStore) -> None:
    url = await store.presign_put(KEY, content_type="image/webp", expires_in=300)

    assert parse_qs(urlparse(url).query)["X-Amz-Expires"] == ["300"]


async def test_content_type_and_if_none_match_are_signed(
    store: S3ObjectStore,
) -> None:
    """서명 대상에서 빠지면 S3가 헤더를 강제하지 않아 덮어쓰기가 뚫린다."""
    url = await store.presign_put(KEY, content_type="image/webp", expires_in=300)

    signed = parse_qs(urlparse(url).query)["X-Amz-SignedHeaders"][0].split(";")

    assert "content-type" in signed
    assert "if-none-match" in signed


async def test_signature_is_present(store: S3ObjectStore) -> None:
    url = await store.presign_put(KEY, content_type="image/webp", expires_in=300)

    assert parse_qs(urlparse(url).query)["X-Amz-Signature"]


# SigV2를 아직 받아주는 리전들. 서명 방식을 endpoint 해석에 맡기면 여기서만
# SigV2로 떨어지고, 헤더를 서명할 수단이 없어 If-None-Match가 사라진다.
@pytest.mark.parametrize("region", ["ap-northeast-2", "us-east-1", "eu-west-1"])
async def test_presign_uses_sigv4_in_every_region(region: str) -> None:
    url = await build_store(region).presign_put(
        KEY, content_type="image/webp", expires_in=300
    )

    query = parse_qs(urlparse(url).query)

    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    signed = query["X-Amz-SignedHeaders"][0].split(";")
    assert "content-type" in signed
    assert "if-none-match" in signed


async def test_fake_head_reports_the_stored_object() -> None:
    fake = FakeObjectStore()
    put_object(fake, KEY, body=b"RIFF\x00\x00\x00\x00WEBP", content_type="image/webp")

    head = await fake.head(KEY)

    assert head is not None
    assert head.content_type == "image/webp"
    assert head.content_length == 12


async def test_fake_head_returns_none_for_a_missing_object() -> None:
    assert await FakeObjectStore().head(KEY) is None


async def test_fake_get_range_returns_the_requested_window() -> None:
    fake = FakeObjectStore()
    put_object(fake, KEY, body=b"0123456789abcdef", content_type="image/webp")

    assert await fake.get_range(KEY, start=0, end=11) == b"0123456789ab"


async def test_fake_list_prefix_filters_and_sorts() -> None:
    fake = FakeObjectStore()
    now = datetime.now(UTC)
    put_object(fake, "images/place/b.webp", body=b"x", content_type="image/webp")
    put_object(
        fake,
        "images/place/a.webp",
        body=b"x",
        content_type="image/webp",
        last_modified=now - timedelta(days=2),
    )
    put_object(fake, "images/menu/c.webp", body=b"x", content_type="image/webp")

    listed = [summary async for summary in fake.list_prefix("images/place/")]

    assert [summary.key for summary in listed] == [
        "images/place/a.webp",
        "images/place/b.webp",
    ]
    assert isinstance(listed[0], ObjectSummary)


async def test_fake_delete_records_the_key() -> None:
    fake = FakeObjectStore()
    put_object(fake, KEY, body=b"x", content_type="image/webp")

    await fake.delete(KEY)

    assert fake.deleted == [KEY]
    assert KEY not in fake.objects
