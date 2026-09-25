"""SSRF-guard consumers under the intranet allowlist (custom MCP, WeKnora, OAuth, voice)."""

from __future__ import annotations

import pytest
from tests.support.outbound import (
    ALLOW,
    HTTPS_ALLOW,
    HTTPS_ONLY,
    MCP_HTTPS_ONLY,
    MCP_PRIVATE,
    OK,
    PRIVATE,
    expected,
    fake_dns,
    outcome,
    use_intranet_allowlist,
)

from octop.infra.connectors.builder import normalize_weknora_base_url
from octop.infra.connectors.custom_mcp import validate_mcp_http_url
from octop.infra.connectors.oauth.mcp import _ensure_mcp_oauth_url
from octop.infra.voice.adapters import _guard_voice_base_url


@pytest.mark.parametrize(
    ("allow", "url", "result"),
    [
        ({"cidrs": ["10.0.0.0/8"]}, "https://10.20.30.40/mcp", OK),
        (HTTPS_ALLOW, "http://10.20.30.40:8080/mcp", MCP_HTTPS_ONLY),
        (ALLOW, "http://10.20.30.40:8080/mcp", OK),
        (ALLOW, "http://example.com/mcp", MCP_HTTPS_ONLY),
    ],
)
async def test_custom_mcp_url(allow: dict[str, object], url: str, result: object):
    with use_intranet_allowlist(**allow):
        assert await outcome(validate_mcp_http_url, url) == expected(url, result)


def test_weknora_base_url_accepts_intranet_http():
    with use_intranet_allowlist(**ALLOW):
        assert normalize_weknora_base_url("http://10.20.30.40:8080") == (
            "http://10.20.30.40:8080/api/v1"
        )


@pytest.mark.parametrize(("allow", "result"), [(HTTPS_ALLOW, OK), ({}, MCP_PRIVATE)])
async def test_mcp_oauth_endpoint_on_intranet_host(
    monkeypatch: pytest.MonkeyPatch, allow: dict[str, object], result: object
):
    fake_dns(monkeypatch)
    url = "https://sso.bank.intra/token"
    with use_intranet_allowlist(**allow):
        got = await outcome(
            _ensure_mcp_oauth_url, url, issuer="https://sso.bank.intra", field="token_endpoint"
        )
    assert got == expected(url, result)


@pytest.mark.parametrize(
    ("allow", "base_url", "result"),
    [
        (ALLOW, "http://10.1.2.3:8000/v1", None),
        (HTTPS_ALLOW, "http://10.1.2.3:8000/v1", HTTPS_ONLY),
        (ALLOW, "https://169.254.169.254", PRIVATE),
        (HTTPS_ALLOW, "https://169.254.169.254", PRIVATE),
    ],
)
async def test_voice_base_url_guard(
    monkeypatch: pytest.MonkeyPatch, allow: dict[str, object], base_url: str, result: object
):
    fake_dns(monkeypatch)
    with use_intranet_allowlist(**allow):
        assert await outcome(_guard_voice_base_url, base_url) == result
