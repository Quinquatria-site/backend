"""선두 바이트로 실제 형식을 판정한다.

presigned PUT은 Content-Type 헤더만 서명 조건으로 강제하고 본문은 보지
않는다. 헤더를 image/jpeg로 맞추고 임의의 binary를 올려도 S3는 200을
반환하므로, 연결 단계에서 내용을 직접 확인해야 한다.
"""

import pytest

from backoffice.images.signature import SIGNATURE_BYTES, matches
from quinquatria_persistence.enums import ImageContentType

JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 8
PNG_HEAD = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4
WEBP_HEAD = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBP"


def test_signature_window_covers_the_webp_marker() -> None:
    """WebP는 offset 8-11에 마커가 있어 12 byte를 읽어야 한다."""
    assert SIGNATURE_BYTES == 12


@pytest.mark.parametrize(
    ("head", "content_type"),
    [
        (JPEG_HEAD, ImageContentType.JPEG),
        (PNG_HEAD, ImageContentType.PNG),
        (WEBP_HEAD, ImageContentType.WEBP),
    ],
)
def test_matching_signature_is_accepted(
    head: bytes, content_type: ImageContentType
) -> None:
    assert matches(head, content_type)


@pytest.mark.parametrize(
    ("head", "content_type"),
    [
        (PNG_HEAD, ImageContentType.JPEG),
        (WEBP_HEAD, ImageContentType.JPEG),
        (JPEG_HEAD, ImageContentType.PNG),
        (WEBP_HEAD, ImageContentType.PNG),
        (JPEG_HEAD, ImageContentType.WEBP),
        (PNG_HEAD, ImageContentType.WEBP),
    ],
)
def test_signature_from_another_format_is_rejected(
    head: bytes, content_type: ImageContentType
) -> None:
    assert not matches(head, content_type)


@pytest.mark.parametrize("content_type", list(ImageContentType))
def test_arbitrary_payload_is_rejected(content_type: ImageContentType) -> None:
    """헤더만 맞춘 비이미지 업로드를 잡는 경로다."""
    assert not matches(b"#!/bin/sh\nrm -rf /", content_type)


@pytest.mark.parametrize("content_type", list(ImageContentType))
def test_empty_and_truncated_payloads_are_rejected(
    content_type: ImageContentType,
) -> None:
    assert not matches(b"", content_type)
    assert not matches(b"RI", content_type)


def test_riff_container_that_is_not_webp_is_rejected() -> None:
    """RIFF는 WAV 등도 쓰는 컨테이너라 앞 4 byte만으로는 부족하다."""
    assert not matches(b"RIFF" + b"\x24\x00\x00\x00" + b"WAVE", ImageContentType.WEBP)
