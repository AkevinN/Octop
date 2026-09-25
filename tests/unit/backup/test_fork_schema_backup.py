"""Backup manifests carry the fork watermark; restore prechecks and resets it."""

from __future__ import annotations

import json
import tarfile
from collections.abc import Callable, Iterator
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from tests.support.fork_migrations import use_fork_dir, write_demo_fork_migrations

from octop.config import DatabaseConfig
from octop.infra.backup import system_archive
from octop.infra.backup.manifest import MANIFEST_VERSION, BackupManifest
from octop.infra.backup.system_archive import create_system_backup, restore_system_backup
from octop.infra.db.fork_migrate import current_fork_version
from octop.infra.db.migrate import _max_discovered_version, _table_exists, run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.paths import PathLayout

UPSTREAM_MAX = _max_discovered_version("sqlite")


@pytest.fixture
def layout(tmp_path: Path) -> PathLayout:
    root = tmp_path / ".octop"
    root.mkdir()
    return PathLayout(root)


@pytest.fixture
def pool(
    layout: PathLayout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[SqlitePool]:
    """Migrated DB with no fork migrations yet."""
    use_fork_dir(monkeypatch, tmp_path / "empty")
    db = SqlitePool(layout.db)
    run_migrations(db)
    yield db
    db.close()


def _enable_demo_forks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_fork_dir(monkeypatch, write_demo_fork_migrations(tmp_path / "fork"))


def _archive(
    pool: SqlitePool,
    layout: PathLayout,
    dest: Path,
    edit: Callable[[dict[str, Any]], object] = lambda _m: None,
) -> dict[str, Any]:
    """Create a backup, apply *edit* to its manifest in place, return the manifest."""
    create_system_backup(
        paths=layout,
        agent_rows=[],
        pool=pool,
        db_config=DatabaseConfig(),
        dest=dest,
        include_config=False,
        include_workspaces=False,
    )
    with tarfile.open(dest, mode="r:gz") as tf:
        members = {m.name: tf.extractfile(m).read() for m in tf.getmembers() if m.isfile()}  # type: ignore[union-attr]
    manifest: dict[str, Any] = json.loads(members["manifest.json"])
    edit(manifest)
    members["manifest.json"] = json.dumps(manifest).encode()
    with tarfile.open(dest, mode="w:gz") as tf:
        for name, blob in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(blob)
            tf.addfile(info, BytesIO(blob))
    return manifest


def _restore(archive: Path, layout: PathLayout, pool: SqlitePool) -> None:
    restore_system_backup(
        archive, paths=layout, pool=pool, db_config=DatabaseConfig(), restore_config=False
    )


def test_manifest_fork_version_roundtrip_and_legacy_default() -> None:
    m = BackupManifest(
        manifest_version=MANIFEST_VERSION,
        octop_version="0.0.0",
        schema_version=UPSTREAM_MAX,
        created_at="t",
        home="h",
        fork_schema_version=3,
    )
    assert BackupManifest.load_text(m.to_json()).fork_schema_version == 3
    legacy = json.loads(m.to_json())
    del legacy["fork_schema_version"]
    assert BackupManifest.from_dict(legacy).fork_schema_version == 0
    assert MANIFEST_VERSION == 1


def test_backup_records_fork_watermark(
    pool: SqlitePool, layout: PathLayout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_demo_forks(tmp_path, monkeypatch)
    run_migrations(pool)
    assert _archive(pool, layout, tmp_path / "a.tar.gz")["fork_schema_version"] == 2


def test_restore_legacy_archive_applies_fork_migrations(
    pool: SqlitePool, layout: PathLayout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "legacy.tar.gz"
    _archive(pool, layout, archive, lambda m: m.pop("fork_schema_version"))
    _enable_demo_forks(tmp_path, monkeypatch)
    _restore(archive, layout, pool)
    assert current_fork_version(pool) == 2
    assert _table_exists(pool, "fork_demo_ref")


def test_refuse_newer_fork_archive_before_database_replace(
    pool: SqlitePool, layout: PathLayout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_demo_forks(tmp_path, monkeypatch)
    run_migrations(pool)
    archive = tmp_path / "newer.tar.gz"
    _archive(pool, layout, archive, lambda m: m.update(fork_schema_version=99))
    with pool.connect() as conn:
        conn.execute(
            "INSERT INTO users(username, password_hash, role, created_at) "
            "VALUES ('still-here', 'hash', 'admin', 1)"
        )

    with pytest.raises(OctopError) as excinfo:
        _restore(archive, layout, pool)

    assert excinfo.value.code == ErrorCode.BACKUP_SCHEMA_INCOMPATIBLE
    assert excinfo.value.details == {
        "archive_schema_version": f"{UPSTREAM_MAX}+fork99",
        "runtime_schema_version": f"{UPSTREAM_MAX}+fork2",
        "archive_fork_schema_version": 99,
        "runtime_fork_schema_version": 2,
    }
    with pool.connect() as conn:
        assert conn.execute("SELECT 1 FROM users WHERE username = 'still-here'").fetchone()


def test_restore_resets_stale_fork_watermark_from_manifest(
    pool: SqlitePool, layout: PathLayout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "before-fork.tar.gz"
    _archive(pool, layout, archive)
    _enable_demo_forks(tmp_path, monkeypatch)
    run_migrations(pool)

    def restore_like_pg_clean(_src: Path, target: SqlitePool) -> None:
        # pg_restore --clean rebuilds dumped objects but leaves the live watermark.
        with target.connect() as conn:
            conn.execute("DROP TABLE fork_demo_ref")

    monkeypatch.setattr(system_archive, "restore_sqlite_into_pool", restore_like_pg_clean)
    _restore(archive, layout, pool)
    assert current_fork_version(pool) == 2
    assert _table_exists(pool, "fork_demo_ref")
