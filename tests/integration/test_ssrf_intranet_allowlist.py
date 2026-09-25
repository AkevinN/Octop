"""Intranet allowlist injection: server start / bind, CLI offline path, API end to end."""

from __future__ import annotations

import logging
from ipaddress import ip_network
from pathlib import Path

import pytest

from octop.cli.support.db import open_cli_services
from octop.infra.server import OctopServer
from octop.infra.utils.intranet_allowlist import (
    IntranetAllowlist,
    configure_intranet_allowlist,
    current_intranet_allowlist,
)
from tests.support.app import ensure_control_plane_bound, octop_client, write_octop_config
from tests.support.auth import auth_header, bootstrap_admin
from tests.support.outbound import ALLOW, use_intranet_allowlist

CONFIG = {
    "intranet_allow_cidrs": ["10.0.0.0/8"],
    "intranet_allow_host_suffixes": ["bank.intra"],
    "intranet_allow_http": True,
}
EXPECTED = IntranetAllowlist((ip_network("10.0.0.0/8"),), ("bank.intra",), True)
INTRANET_MCP = {
    "servers": {"srv": {"transport": "streamable_http", "url": "http://10.20.30.40:8080/mcp"}}
}


async def test_start_and_bind_inject_allowlist(
    tmp_octop_home: Path, caplog: pytest.LogCaptureFixture
):
    write_octop_config(tmp_octop_home, **CONFIG)
    caplog.set_level(logging.INFO, logger="octop.infra.server")
    with use_intranet_allowlist():
        async with octop_client(tmp_octop_home, bind_database=False) as (client, srv):
            assert current_intranet_allowlist() == EXPECTED
            configure_intranet_allowlist()
            await ensure_control_plane_bound(srv)
            assert current_intranet_allowlist() == EXPECTED
            await bootstrap_admin(client, tmp_octop_home)
            resp = await client.put(
                "/api/connectors/custom-mcp", headers=await auth_header(client), json=INTRANET_MCP
            )
    assert resp.status_code == 200, resp.text
    assert "intranet outbound allowlist active" in caplog.text


async def test_default_config_resets_stale_allowlist(tmp_octop_home: Path):
    with use_intranet_allowlist(**ALLOW):
        async with octop_client(tmp_octop_home) as (client, _srv):
            assert current_intranet_allowlist().is_empty
            await bootstrap_admin(client, tmp_octop_home)
            resp = await client.put(
                "/api/connectors/custom-mcp", headers=await auth_header(client), json=INTRANET_MCP
            )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CONNECTOR_INVALID_CREDENTIALS"


async def test_invalid_allowlist_aborts_start_before_database(
    tmp_octop_home: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path = tmp_octop_home / "octop.db"
    monkeypatch.setenv("OCTOP_DATABASE_SQLITE_PATH", str(db_path))  # no deferred-DB shortcut
    write_octop_config(tmp_octop_home, intranet_allow_cidrs=["0.0.0.0/0"])
    srv = OctopServer(home=tmp_octop_home)
    with pytest.raises(ValueError, match="intranet_allow_cidrs"):
        await srv.start()
    assert srv.services is None
    assert not db_path.exists()


def test_open_cli_services_injects_allowlist(tmp_octop_home: Path):
    write_octop_config(tmp_octop_home, **CONFIG)
    with use_intranet_allowlist(), open_cli_services(home=tmp_octop_home):
        assert current_intranet_allowlist() == EXPECTED
