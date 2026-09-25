"""Gated PostgreSQL checks for fork migrations (see test_postgresql_control_plane.py)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from octop.infra.db import fork_migrate
from octop.infra.db.fork_migrate import current_fork_version, run_fork_migrations
from octop.infra.db.migrate import (
    _current_version,
    _max_discovered_version,
    _table_exists,
    run_migrations,
)
from tests.integration.test_postgresql_control_plane import _conninfo, _reset_public_schema
from tests.support.fork_migrations import use_fork_dir, write_demo_fork_migrations
from tests.support.postgresql import requires_postgresql

pytestmark = [requires_postgresql, pytest.mark.postgresql]


@pytest.fixture
def pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Upstream-current PG schema with no fork migrations applied yet."""
    from octop.infra.db.pool import PostgresPool

    db = PostgresPool(_conninfo())
    try:
        _reset_public_schema(db)
        use_fork_dir(monkeypatch, tmp_path / "empty")
        run_migrations(db)
        yield db
    finally:
        db.close()


def test_pg_fork_version_rolls_back_then_applies_once(
    pool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fork_dir = use_fork_dir(monkeypatch, write_demo_fork_migrations(tmp_path / "fork"))
    good = (fork_dir / "fork002_demo_ref.pg.sql").read_text(encoding="utf-8")
    (fork_dir / "fork002_demo_ref.pg.sql").write_text(
        "CREATE TABLE fork_half (id BIGINT);\nINSERT INTO no_such_table VALUES (1);\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="no_such_table"):
        run_fork_migrations(pool)
    assert current_fork_version(pool) == 1
    assert not _table_exists(pool, "fork_half")

    (fork_dir / "fork002_demo_ref.pg.sql").write_text(good, encoding="utf-8")
    run_fork_migrations(pool)
    assert current_fork_version(pool) == 2

    def fail(_sql: str) -> list[str]:
        raise AssertionError("applied migration re-executed")

    monkeypatch.setattr(fork_migrate, "_split_pg_sql", fail)
    run_fork_migrations(pool)
    assert current_fork_version(pool) == 2


def test_pg_clamped_schema_still_gets_fork_migrations(
    pool: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pool.connect() as conn:
        conn.execute("UPDATE _schema_version SET version = 20")
    use_fork_dir(monkeypatch, write_demo_fork_migrations(tmp_path / "fork"))
    run_migrations(pool)
    assert _current_version(pool) == _max_discovered_version("postgresql")
    assert current_fork_version(pool) == 2
    assert _table_exists(pool, "fork_demo_ref")


@pytest.mark.parametrize(("dump_has_watermark", "reset_to"), [(True, 1), (False, 0)])
def test_pg_restore_resets_watermark_from_manifest(
    pool: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dump_has_watermark: bool,
    reset_to: int,
) -> None:
    if not shutil.which("pg_dump") or not shutil.which("pg_restore"):
        pytest.skip("pg_dump/pg_restore not on PATH")
    from octop.config import DatabaseConfig
    from octop.infra.backup import system_archive
    from octop.infra.utils.paths import PathLayout

    fork_dir = use_fork_dir(monkeypatch, write_demo_fork_migrations(tmp_path / "fork", (1,)))
    run_migrations(pool)
    if not dump_has_watermark:  # e.g. an upstream build's backup
        with pool.connect() as conn:
            conn.execute("DROP TABLE _fork_schema_version")
    db_config = DatabaseConfig(driver="postgresql", url=_conninfo())
    layout = PathLayout(tmp_path / ".octop")
    layout.root.mkdir()
    archive = tmp_path / "pg-backup.tar.gz"
    system_archive.create_system_backup(
        paths=layout, agent_rows=[], pool=pool, db_config=db_config, dest=archive
    )
    write_demo_fork_migrations(fork_dir, (2,))
    run_migrations(pool)  # live watermark now 2; pg_restore --clean may keep it

    resets: list[int] = []
    real_set = system_archive.set_fork_version

    def spy(db: Any, version: int) -> None:
        resets.append(version)
        real_set(db, version)

    monkeypatch.setattr(system_archive, "set_fork_version", spy)
    system_archive.restore_system_backup(
        archive, paths=layout, pool=pool, db_config=db_config, restore_config=False
    )
    assert resets == [reset_to]
    assert current_fork_version(pool) == 2
    assert _table_exists(pool, "fork_demo_ref")
