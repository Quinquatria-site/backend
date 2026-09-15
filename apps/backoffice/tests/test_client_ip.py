"""명세 §4.1의 "신뢰하는 reverse proxy가 확정한 client IP"를 검증한다.

가장 왼쪽 값은 클라이언트가 위조할 수 있으므로 절대 신뢰하지 않는다.
"""

import pytest
from starlette.requests import Request

from backoffice.auth.client_ip import client_ip


def _request(
    forwarded_for: str | None = None, peer: str | None = "10.0.0.1"
) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/token",
            "headers": headers,
            "client": (peer, 51234) if peer else None,
        }
    )


def test_single_trusted_proxy_takes_the_only_entry() -> None:
    assert client_ip(_request("203.0.113.7"), trusted_proxy_hops=1) == "203.0.113.7"


def test_two_trusted_proxies_skip_the_inner_proxy() -> None:
    request = _request("203.0.113.7, 198.51.100.4")

    assert client_ip(request, trusted_proxy_hops=2) == "203.0.113.7"


def test_client_supplied_prefix_is_ignored() -> None:
    """클라이언트가 헤더를 미리 채워 보내도 오른쪽부터 세면 영향이 없다."""
    request = _request("1.1.1.1, 203.0.113.7, 198.51.100.4")

    assert client_ip(request, trusted_proxy_hops=2) == "203.0.113.7"


def test_zero_hops_ignores_the_header_entirely() -> None:
    request = _request("1.1.1.1")

    assert client_ip(request, trusted_proxy_hops=0) == "10.0.0.1"


def test_missing_header_falls_back_to_the_peer() -> None:
    assert client_ip(_request(None), trusted_proxy_hops=1) == "10.0.0.1"


def test_shorter_list_than_hops_takes_the_leftmost() -> None:
    request = _request("198.51.100.4")

    assert client_ip(request, trusted_proxy_hops=2) == "198.51.100.4"


def test_whitespace_and_empty_entries_are_ignored() -> None:
    request = _request("  203.0.113.7 ,, 198.51.100.4  ")

    assert client_ip(request, trusted_proxy_hops=2) == "203.0.113.7"


@pytest.mark.parametrize("hops", [0, 1, 2])
def test_missing_peer_never_raises(hops: int) -> None:
    """ASGI scope에 client가 없을 수 있으므로 문자열을 항상 돌려준다."""
    assert client_ip(_request(None, peer=None), trusted_proxy_hops=hops) == "unknown"
