"""Intranet allowlist: configuration checks and the SSRF guard's release points."""

from __future__ import annotations

import re
from ipaddress import ip_network
from typing import Any

import httpx
import pytest
from tests.support.outbound import (
    ALLOW,
    BASELINE_CASES,
    HTTPS_ALLOW,
    HTTPS_ONLY,
    OK,
    PRIVATE,
    check_outbound,
    expected,
    fake_dns,
    outcome,
    record_pinned,
    use_intranet_allowlist,
)

from octop.infra.connectors.custom_mcp import validate_mcp_http_url
from octop.infra.utils.intranet_allowlist import (
    IntranetAllowlist,
    configure_intranet_allowlist,
    current_intranet_allowlist,
)
from octop.infra.utils.ssrf_guard import (
    UnsafeOutboundUrl,
    intranet_http_allowed,
    safe_request,
    validate_https_url,
)

HARD_DENIED = [
    "https://169.254.169.254/latest/meta-data",
    "https://[::ffff:169.254.169.254]/",
    "https://127.0.0.1/",
    "https://[::1]/",
    "https://0.0.0.0/",
    "https://224.0.0.1/",
    "https://240.0.0.1/",
    "https://[fe80::1]/",
]


def test_configure_normalizes_dedupes_and_resets():
    with use_intranet_allowlist(
        cidrs=["10.0.0.0/8", "192.168.10.0/24", "fd00::/8", "10.9.9.9", "10.0.0.0/8"],
        host_suffixes=["Bank.Intra.", ".corp.bank.intra", "bank.intra"],
    ) as allow:
        assert current_intranet_allowlist() is allow
        assert allow == IntranetAllowlist(
            networks=tuple(
                ip_network(n) for n in ("10.0.0.0/8", "192.168.10.0/24", "fd00::/8", "10.9.9.9/32")
            ),
            host_suffixes=("bank.intra", "corp.bank.intra"),
        )
    assert current_intranet_allowlist().is_empty


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        *[
            ({"cidrs": [c]}, f"intranet_allow_cidrs: invalid entry {c!r}")
            for c in (
                "10.1.2.3/8",
                "not-a-cidr",
                "0.0.0.0/0",
                "127.0.0.0/8",
                "169.254.0.0/16",
                "224.0.0.0/4",
                "240.0.0.0/4",
                "::/0",
                "fe80::/10",
                "::ffff:0:0/96",
            )
        ],
        *[
            (
                {"cidrs": ["10.0.0.0/8"], "host_suffixes": [s]},
                f"intranet_allow_host_suffixes: invalid entry {s!r}",
            )
            for s in (
                "",
                "*.bank.intra",
                "bank.intra/x",
                "bank.intra:80",
                "bank intra",
                "10.1.2.3",
                "localhost",
                "a.localhost",
                "intra",
                "bank..intra",
            )
        ],
        (
            {"host_suffixes": ["bank.intra"]},
            "intranet_allow_host_suffixes requires intranet_allow_cidrs",
        ),
        ({"allow_http": True}, "intranet_allow_http requires intranet_allow_cidrs"),
    ],
)
def test_invalid_config_raises_and_keeps_current(kwargs: dict[str, Any], message: str):
    with use_intranet_allowlist(**ALLOW) as current:
        with pytest.raises(ValueError, match=f"^{re.escape(message)}"):
            configure_intranet_allowlist(**kwargs)
        assert current_intranet_allowlist() is current


@pytest.mark.parametrize(
    ("allow", "url", "result"),
    [
        (HTTPS_ALLOW, "https://10.20.30.40/mcp", OK),
        (HTTPS_ALLOW, "https://[::ffff:10.1.2.3]/", OK),
        (HTTPS_ALLOW, "https://172.16.0.5/", PRIVATE),
        (HTTPS_ALLOW, "http://10.20.30.40:8080/", HTTPS_ONLY),
        (ALLOW, "http://10.20.30.40:8080/mcp", OK),
        (ALLOW, "http://example.com/", HTTPS_ONLY),
        (ALLOW, "http://172.16.0.5/", HTTPS_ONLY),
        (ALLOW, "https://localhost/", (UnsafeOutboundUrl, "f: localhost is not allowed")),
        *[(ALLOW, url, PRIVATE) for url in HARD_DENIED],
    ],
)
async def test_literal_release_points(allow: dict[str, object], url: str, result: object):
    with use_intranet_allowlist(**allow):
        assert await outcome(validate_https_url, url, field="f") == expected(url, result)


@pytest.mark.parametrize(
    ("url", "result", "port"),
    [
        ("https://oa.bank.intra/x", OK, 443),
        ("https://a.b.bank.intra/x", OK, 443),
        ("https://pub.bank.intra/x", OK, 443),
        ("https://mixed.bank.intra/x", PRIVATE, 443),
        ("https://lo.bank.intra/x", PRIVATE, 443),
        ("https://other.bank.intra/x", PRIVATE, 443),
        ("https://evil.example.com/x", PRIVATE, 443),
        ("https://evilbank.intra/x", PRIVATE, 443),
        ("http://oa.bank.intra/x", OK, 80),
        ("http://pub.bank.intra/x", HTTPS_ONLY, 80),
        ("http://mixed.bank.intra/x", HTTPS_ONLY, 80),
    ],
)
async def test_resolved_release_point_pins_and_blocks_rebinding(
    monkeypatch: pytest.MonkeyPatch, url: str, result: object, port: int
):
    with use_intranet_allowlist(**ALLOW):
        lookups = await check_outbound(monkeypatch, url, result)
    assert {p for _host, p in lookups} == {port}


async def test_redirect_from_allowlisted_host_is_not_followed(monkeypatch: pytest.MonkeyPatch):
    fake_dns(monkeypatch)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://169.254.169.254/"})

    record_pinned(monkeypatch, handler)
    with use_intranet_allowlist(**ALLOW):
        response = await safe_request("GET", "https://oa.bank.intra/x")
    assert response.status_code == 302
    assert len(seen) == 1


@pytest.mark.parametrize(
    ("allow", "url", "allowed"),
    [
        (ALLOW, "http://10.20.30.40:8080/mcp", True),
        (ALLOW, "http://bank.intra/", True),
        (ALLOW, "http://a.b.bank.intra./", True),
        (ALLOW, "http://evilbank.intra/", False),
        (ALLOW, "http://bank.intra.evil.com/", False),
        (ALLOW, "http://example.com/", False),
        (ALLOW, "http://172.16.0.5/", False),
        (HTTPS_ALLOW, "http://10.20.30.40:8080/mcp", False),
        ({}, "http://10.20.30.40:8080/mcp", False),
    ],
)
def test_intranet_http_allowed(allow: dict[str, object], url: str, allowed: bool):
    with use_intranet_allowlist(**allow):
        assert intranet_http_allowed(url) is allowed


@pytest.mark.parametrize(
    ("url", "https_result", "mcp_result"), [c for c in BASELINE_CASES if OK in c[1:]]
)
def test_allowlist_only_relaxes(url: str, https_result: object, mcp_result: object):
    with use_intranet_allowlist(**ALLOW):
        if https_result == OK:
            assert validate_https_url(url, field="f") == url
        if mcp_result == OK:
            assert validate_mcp_http_url(url) == url
