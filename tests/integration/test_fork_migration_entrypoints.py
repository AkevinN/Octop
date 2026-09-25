"""Every control-plane entry point applies fork migrations (via ``run_migrations``)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from octop.cli.commands.init import init
from octop.cli.support.db import open_cli_services
from octop.config import DatabaseConfig
from octop.infra.db.fork_migrate import current_fork_version
from octop.infra.db.migrate import _table_exists
from octop.infra.db.pool import SqlitePool
from octop.infra.db.rebind import (
    assert_control_plane_database_empty,
    persist_database_config,
    rebind_control_plane,
)
from octop.infra.utils.paths import PathLayout
from tests.support.app import octop_client
from tests.support.fork_migrations import use_fork_dir, write_demo_fork_migrations


@pytest.fixture
def fork_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return use_fork_dir(monkeypatch, write_demo_fork_migrations(tmp_path / "fork", versions=(1,)))


def _fork_version_at(path: Path) -> int:
    db = SqlitePool(path)
    try:
        return current_fork_version(db)
    finally:
        db.close()


async def test_server_bind_rebind_and_restart(tmp_octop_home: Path, fork_dir: Path) -> None:
    async with octop_client(tmp_octop_home) as (_client, srv):  # greenfield: bind_control_plane
        assert srv.services is not None
        assert current_fork_version(srv.services.db) == 1
        persist_database_config(srv.paths.config, DatabaseConfig(sqlite_path="rebound.db"))
        rebind_control_plane(srv)
        assert current_fork_version(srv.services.db) == 1

    write_demo_fork_migrations(fork_dir, versions=(2,))
    async with octop_client(tmp_octop_home) as (_client, srv):  # existing DB: start()
        assert srv.services is not None
        assert current_fork_version(srv.services.db) == 2
        assert _table_exists(srv.services.db, "fork_demo_ref")


def test_offline_entrypoints(tmp_path: Path, fork_dir: Path) -> None:
    probe_home = PathLayout(tmp_path / "probe")
    assert_control_plane_database_empty(DatabaseConfig(sqlite_path="probe.db"), probe_home)
    assert _fork_version_at(probe_home.root / "probe.db") == 1

    with open_cli_services(tmp_path / "cli") as services:
        assert current_fork_version(services.db) == 1

    home = tmp_path / "init"
    result = CliRunner().invoke(
        init,
        ["--yes", "--admin-username", "admin", "--admin-password", "Fork-Migr4tion!"],
        env={"OCTOP_HOME": str(home)},
    )
    assert result.exit_code == 0, result.output
    assert _fork_version_at(PathLayout(home).db) == 1
