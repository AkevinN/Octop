"""SSRF-guard test helpers: allowlist scope, fake DNS, pinned transport, baseline corpus."""

from __future__ import annotations

import inspect
import ipaddress
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest

from octop.infra.utils import ssrf_guard
from octop.infra.utils.intranet_allowlist import IntranetAllowlist, configure_intranet_allowlist
from octop.infra.utils.ssrf_guard import UnsafeOutboundUrl

# Representative allowlists: https-only, and with plain http enabled.
HTTPS_ALLOW: dict[str, Any] = {"cidrs": ["10.0.0.0/8"], "host_suffixes": ["bank.intra"]}
ALLOW: dict[str, Any] = {**HTTPS_ALLOW, "allow_http": True}

OK = "ok"  # expected result: the call returns the URL unchanged
PRIVATE = (UnsafeOutboundUrl, "private or reserved IP addresses are not allowed")
HTTPS_ONLY = (UnsafeOutboundUrl, "only https URLs are allowed")
MCP_PRIVATE = (ValueError, PRIVATE[1])
MCP_HTTPS_ONLY = (ValueError, "non-local url must use https")
BAD_PORT = (ValueError, "Port could not be cast to integer value as 'abc'")

# Upstream (757fd12) results with no allowlist:
# (url, validate_https_url(url, field="f"), validate_mcp_http_url(url)).
BASELINE_CASES: list[tuple[str, object, object]] = [
    ("http://mcp.notion.com/token", HTTPS_ONLY, MCP_HTTPS_ONLY),
    ("https://127.0.0.1/token", PRIVATE, OK),
    ("https://10.0.0.1/token", PRIVATE, MCP_PRIVATE),
    ("https://localhost/token", (UnsafeOutboundUrl, "f: localhost is not allowed"), OK),
    ("https://169.254.169.254/latest/meta-data", PRIVATE, MCP_PRIVATE),
    ("https://[::1]/x", PRIVATE, OK),
    ("https://[::ffff:10.0.0.1]/x", PRIVATE, MCP_PRIVATE),
    ("https://0.0.0.0/", PRIVATE, MCP_PRIVATE),
    ("https://224.0.0.1/", PRIVATE, MCP_PRIVATE),
    ("https://240.0.0.1/", PRIVATE, MCP_PRIVATE),
    ("https://[fe80::1]/", PRIVATE, MCP_PRIVATE),
    (
        "https:///nohost",
        (UnsafeOutboundUrl, "missing hostname"),
        (ValueError, "url missing hostname"),
    ),
    ("ftp://example.com/", HTTPS_ONLY, (ValueError, "url must be http or https")),
    ("HTTPS://Example.COM./a", OK, OK),
    ("https://100.100.100.200/latest/meta-data", OK, OK),
    ("http://10.20.30.40:8080/mcp", HTTPS_ONLY, MCP_HTTPS_ONLY),
    ("https://10.20.30.40/mcp", PRIVATE, MCP_PRIVATE),
    ("https://example.com:abc/", BAD_PORT, BAD_PORT),
    ("http://localhost:8080/mcp", HTTPS_ONLY, OK),
    ("https://oa.bank.intra/x", OK, OK),
]

DNS: dict[str, list[str]] = {
    "pub.example.com": ["93.184.216.34"],
    "pub.bank.intra": ["1.2.3.4"],
    "oa.bank.intra": ["10.1.2.3"],
    "a.b.bank.intra": ["10.1.2.3"],
    "sso.bank.intra": ["10.2.3.4"],
    "evil.example.com": ["10.1.2.3"],
    "evilbank.intra": ["10.1.2.3"],
    "mixed.bank.intra": ["10.1.2.3", "169.254.169.254"],
    "lo.bank.intra": ["127.0.0.1"],
    "other.bank.intra": ["172.16.0.5"],
}


@contextmanager
def use_intranet_allowlist(**kwargs: Any) -> Iterator[IntranetAllowlist]:
    """Install an allowlist for the block, then reset to empty (no cross-test leaks)."""
    try:
        yield configure_intranet_allowlist(**kwargs)
    finally:
        configure_intranet_allowlist()


def expected(url: str, result: object) -> object:
    return url if result == OK else result


async def outcome(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """``fn(...)`` (awaited if needed), or ``(type(exc), str(exc))`` for exact comparison."""
    try:
        result = fn(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result
    except Exception as exc:
        return type(exc), str(exc)


def fake_dns(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    """Serve :data:`DNS` from ``socket.getaddrinfo``; return the ``(host, port)`` lookups."""
    lookups: list[tuple[str, int]] = []

    def getaddrinfo(host: str, port: int, *_args: Any, **_kwargs: Any) -> list[Any]:
        lookups.append((host, port))
        try:
            ips = [str(ipaddress.ip_address(host))]
        except ValueError:
            if host not in DNS:
                raise socket.gaierror(socket.EAI_NONAME, "unknown host") from None
            ips = DNS[host]
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (ip, port),
            )
            for ip in ips
        ]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return lookups


def record_pinned(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response] = lambda _r: httpx.Response(200),
) -> list[tuple[str, str]]:
    """Replace ``PinnedIPTransport`` with a mock; return the ``(host, pin_ip)`` it was built with."""
    pins: list[tuple[str, str]] = []

    def transport(target_host: str, pin_ip: str) -> httpx.MockTransport:
        pins.append((target_host, pin_ip))
        return httpx.MockTransport(handler)

    monkeypatch.setattr(ssrf_guard, "PinnedIPTransport", transport)
    return pins


async def check_outbound(
    monkeypatch: pytest.MonkeyPatch, url: str, result: object
) -> list[tuple[str, int]]:
    """Assert ``validate_https_url_resolved`` and ``safe_request`` both yield ``result``.

    A passing URL is fetched through a transport pinned to the host's first DNS
    answer; a rejected one never builds a transport. Returns the DNS lookups.
    """
    lookups = fake_dns(monkeypatch)
    pins = record_pinned(monkeypatch)
    assert await outcome(ssrf_guard.validate_https_url_resolved, url) == expected(url, result)
    response = await outcome(ssrf_guard.safe_request, "GET", url)
    if result == OK:
        host = urlparse(url).hostname or ""
        assert response.status_code == 200
        assert pins == [(host, DNS[host][0])]
    else:
        assert response == result
        assert pins == []
    return lookups
