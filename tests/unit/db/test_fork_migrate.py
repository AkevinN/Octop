"""Fork migration namespace: discovery, watermark, runner, ``run_migrations`` hook."""

from __future__ import annotations

import ast
import logging
import re
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from tests.support.fork_migrations import use_fork_dir, write_demo_fork_migrations

from octop.infra.db import fork_migrate, migrate
from octop.infra.db.fork_migrate import (
    current_fork_version,
    discover_fork_migrations,
    max_fork_version,
    run_fork_migrations,
    set_fork_version,
)
from octop.infra.db.migrate import _current_version, _table_exists, run_migrations
from octop.infra.db.pool import SqlitePool

UPSTREAM_MAX = migrate._max_discovered_version("sqlite")


@pytest.fixture
def pool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SqlitePool]:
    """Upstream-current SQLite DB; the demo fork pair is pending."""
    use_fork_dir(monkeypatch, tmp_path / "empty")
    db = SqlitePool(tmp_path / "octop.db")
    run_migrations(db)
    use_fork_dir(monkeypatch, write_demo_fork_migrations(tmp_path / "fork"))
    yield db
    db.close()


def _names(found: list[tuple[int, Path]]) -> list[tuple[int, str]]:
    return [(v, p.name) for v, p in found]


def test_upstream_discovery_ignores_fork_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialects = ("sqlite", "postgresql")
    before = {
        d: (_names(migrate._discover(d)), migrate._max_discovered_version(d)) for d in dialects
    }
    mixed = tmp_path / "mixed"
    shutil.copytree(migrate._MIGRATIONS_DIR, mixed)
    write_demo_fork_migrations(mixed)
    monkeypatch.setattr(migrate, "_MIGRATIONS_DIR", mixed)
    for d in dialects:
        assert (_names(migrate._discover(d)), migrate._max_discovered_version(d)) == before[d]


def test_discover_splits_dialects_in_version_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_fork_dir(monkeypatch, write_demo_fork_migrations(tmp_path / "fork", versions=(2, 1)))
    assert _names(discover_fork_migrations("sqlite")) == [
        (1, "fork001_demo.sql"),
        (2, "fork002_demo_ref.sql"),
    ]
    assert _names(discover_fork_migrations("postgresql")) == [
        (1, "fork001_demo.pg.sql"),
        (2, "fork002_demo_ref.pg.sql"),
    ]
    assert max_fork_version("sqlite") == 2


@pytest.mark.parametrize(
    ("names", "fragment"),
    [
        (["fork001_a.sql", "fork001_b.sql"], "fork001_a.sql and fork001_b.sql"),
        (["forkX_bad.sql"], "forkX_bad.sql"),
        (["fork01_a.sql"], "fork01_a.sql"),
        (["fork001_Bad.sql"], "fork001_Bad.sql"),
    ],
)
def test_discover_rejects_duplicate_or_malformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, names: list[str], fragment: str
) -> None:
    directory = use_fork_dir(monkeypatch, tmp_path / "fork")
    for name in names:
        (directory / name).write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match=re.escape(fragment)):
        discover_fork_migrations("sqlite")


def test_watermark_table_is_single_row(pool: SqlitePool) -> None:
    with pool.connect() as conn:
        conn.execute("DROP TABLE _fork_schema_version")
    assert current_fork_version(pool) == 0
    set_fork_version(pool, 3)
    set_fork_version(pool, 4)
    assert current_fork_version(pool) == 4
    with pool.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM _fork_schema_version").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO _fork_schema_version (id, version) VALUES (2, 0)")


def test_runner_applies_pending_versions_without_touching_upstream(pool: SqlitePool) -> None:
    with pool.connect() as conn:
        conn.execute("DROP TABLE _fork_schema_version")
    run_fork_migrations(pool)
    assert current_fork_version(pool) == 2
    assert _table_exists(pool, "fork_demo")
    assert _table_exists(pool, "fork_demo_ref")
    assert _current_version(pool) == UPSTREAM_MAX


def test_runner_is_idempotent(pool: SqlitePool, monkeypatch: pytest.MonkeyPatch) -> None:
    run_fork_migrations(pool)

    def fail(_sql: str) -> list[str]:
        raise AssertionError("applied migration re-executed")

    monkeypatch.setattr(fork_migrate, "_split_pg_sql", fail)
    run_fork_migrations(pool)
    assert current_fork_version(pool) == 2


def test_failed_statement_rolls_back_whole_version(pool: SqlitePool, tmp_path: Path) -> None:
    (tmp_path / "fork" / "fork002_demo_ref.sql").write_text(
        "CREATE TABLE fork_half (id INTEGER);\nINSERT INTO no_such_table VALUES (1);\n",
        encoding="utf-8",
    )
    with pytest.raises(sqlite3.OperationalError):
        run_fork_migrations(pool)
    assert current_fork_version(pool) == 1
    assert not _table_exists(pool, "fork_half")


def test_py_step_runs_after_sql_before_watermark_in_same_transaction(
    pool: SqlitePool, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, int]] = []

    def step(conn: sqlite3.Connection, dialect: str) -> None:
        seen.append(
            (dialect, conn.execute("SELECT version FROM _fork_schema_version").fetchone()[0])
        )
        conn.execute("INSERT INTO fork_demo_ref (id) VALUES (1)")
        raise RuntimeError("step failed")

    monkeypatch.setitem(fork_migrate._FORK_PY_STEPS, 2, step)
    with pytest.raises(RuntimeError, match="step failed"):
        run_fork_migrations(pool)
    assert seen == [("sqlite", 1)]
    assert current_fork_version(pool) == 1
    assert not _table_exists(pool, "fork_demo_ref")


def test_newer_database_watermark_is_left_alone(
    pool: SqlitePool, caplog: pytest.LogCaptureFixture
) -> None:
    set_fork_version(pool, 9)
    with caplog.at_level(logging.WARNING, logger=fork_migrate.__name__):
        run_fork_migrations(pool)
    assert current_fork_version(pool) == 9
    assert not _table_exists(pool, "fork_demo")
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("9" in m and "2" in m for m in warnings)


@pytest.mark.parametrize(
    "prepare",
    [
        None,
        ["DROP TABLE user_sso_identities", "UPDATE _schema_version SET version = 14"],
        ["UPDATE _schema_version SET version = 20"],
    ],
    ids=["fresh", "from-v14", "clamped"],
)
def test_run_migrations_applies_fork_after_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prepare: list[str] | None
) -> None:
    fork_dir = use_fork_dir(monkeypatch, tmp_path / "fork")
    db = SqlitePool(tmp_path / "octop.db")
    try:
        if prepare is not None:
            run_migrations(db)
            with db.connect() as conn:
                for stmt in prepare:
                    conn.execute(stmt)
        write_demo_fork_migrations(fork_dir)
        run_migrations(db)
        assert _current_version(db) == UPSTREAM_MAX
        assert current_fork_version(db) == 2
        assert _table_exists(db, "fork_demo_ref")
    finally:
        db.close()


def test_run_migrations_ends_with_fork_runner() -> None:
    tree = ast.parse(Path(migrate.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_migrations")
    assert ast.unparse(fn.body[-1]) == "run_fork_migrations(db)"


def test_repo_fork_migrations_are_paired_and_idempotent() -> None:
    sqlite = {v: p.name.removesuffix(".sql") for v, p in discover_fork_migrations("sqlite")}
    pg = discover_fork_migrations("postgresql")
    assert sqlite == {v: p.name.removesuffix(".pg.sql") for v, p in pg}
    assert set(fork_migrate._FORK_PY_STEPS) <= set(sqlite)
    ddl = re.compile(r"(?i)\bcreate\s+(unique\s+)?(table|index)\b|\badd\s+column\b")
    for _version, path in pg:
        for stmt in migrate._split_pg_sql(path.read_text(encoding="utf-8")):
            if ddl.search(stmt):
                assert re.search(r"(?i)\bif\s+not\s+exists\b", stmt), f"{path.name}: {stmt}"
