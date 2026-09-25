"""Default-config snapshot of the outbound SSRF guard (upstream 757fd12).

Passes unchanged before and after the intranet allowlist: with nothing
configured, every return value, exception type and message is the upstream one.
"""

from __future__ import annotations

import pytest
from tests.support.outbound import (
    BASELINE_CASES,
    HTTPS_ONLY,
    OK,
    PRIVATE,
    check_outbound,
    expected,
    outcome,
)

from octop.infra.connectors.custom_mcp import validate_mcp_http_url
from octop.infra.utils.ssrf_guard import UnsafeOutboundUrl, validate_https_url


@pytest.mark.parametrize(("url", "https_result", "mcp_result"), BASELINE_CASES)
async def test_literal_checks_match_baseline(url: str, https_result: object, mcp_result: object):
    assert await outcome(validate_https_url, url, field="f") == expected(url, https_result)
    assert await outcome(validate_mcp_http_url, url) == expected(url, mcp_result)


@pytest.mark.parametrize(
    ("url", "result"),
    [
        ("https://pub.example.com/x", OK),
        ("https://oa.bank.intra/x", PRIVATE),
        ("https://evil.example.com/x", PRIVATE),
        ("https://mixed.bank.intra/x", PRIVATE),
        (
            "https://nodns.bank.intra/x",
            (UnsafeOutboundUrl, "cannot resolve hostname 'nodns.bank.intra'"),
        ),
        ("http://pub.example.com/x", HTTPS_ONLY),
    ],
)
async def test_resolution_matches_baseline(
    monkeypatch: pytest.MonkeyPatch, url: str, result: object
):
    lookups = await check_outbound(monkeypatch, url, result)
    assert all(port == 443 for _host, port in lookups)
