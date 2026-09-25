"""Apply intranet-fork migrations.

Each file is ``forkNNN_description.sql`` (SQLite) or ``forkNNN_description.pg.sql``
(PostgreSQL), stored next to the upstream ``NNN_`` files. Upstream ``_discover``
never matches them, and the watermark lives in ``_fork_schema_version`` so
``_schema_version`` and its clamp ladder stay untouched. ``run_migrations``
calls :func:`run_fork_migrations` last.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from octop.infra.db.migrate import _split_pg_sql, _table_exists
from octop.infra.db.pool import DatabasePool

logger = logging.getLogger(__name__)

_FORK_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_FORK_FILE_RE = re.compile(r"^fork(\d{3})_[a-z0-9_]+(\.pg)?\.sql$")

ForkPyStep = Callable[[Any, str], None]
# version -> step run after that version's SQL on the same transaction connection
# (``(conn, dialect)``). Steps must be idempotent, use ``?`` placeholders, never commit.
_FORK_PY_STEPS: dict[int, ForkPyStep] = {}


def discover_fork_migrations(dialect: str) -> list[tuple[int, Path]]:
    want_pg = dialect == "postgresql"
    found: dict[int, Path] = {}
    for entry in sorted(_FORK_MIGRATIONS_DIR.iterdir()):
        name = entry.name
        if not (name.startswith("fork") and name.endswith(".sql")):
            continue
        m = _FORK_FILE_RE.match(name)
        if m is None:
            raise RuntimeError(
                f"Malformed fork migration file name {name!r}: "
                "expected forkNNN_description.sql / forkNNN_description.pg.sql"
            )
        if (m.group(2) is not None) != want_pg:
            continue
        version = int(m.group(1))
        prior = found.get(version)
        if prior is not None:
            raise RuntimeError(
                f"Duplicate fork migration version {version:03d}: {prior.name} and {name}"
            )
        found[version] = entry
    return sorted(found.items())


def max_fork_version(dialect: str) -> int:
    return max((v for v, _ in discover_fork_migrations(dialect)), default=0)


def _ensure_version_table(conn: Any) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _fork_schema_version "
        "(id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL)"
    )
    conn.execute(
        "INSERT INTO _fork_schema_version (id, version) "
        "SELECT 1, 0 WHERE NOT EXISTS (SELECT 1 FROM _fork_schema_version)"
    )


def _read_version(conn: Any, suffix: str = "") -> int:
    row = conn.execute(f"SELECT version FROM _fork_schema_version WHERE id = 1{suffix}").fetchone()
    return int(row[0]) if row is not None else 0


def current_fork_version(db: DatabasePool) -> int:
    if not _table_exists(db, "_fork_schema_version"):
        return 0
    with db.connect() as conn:
        return _read_version(conn)


def set_fork_version(db: DatabasePool, version: int) -> None:
    with db.transaction() as conn:
        _ensure_version_table(conn)
        conn.execute("UPDATE _fork_schema_version SET version = ? WHERE id = 1", (version,))


def run_fork_migrations(db: DatabasePool) -> None:
    with db.transaction() as conn:
        _ensure_version_table(conn)
    migrations = discover_fork_migrations(db.dialect)
    latest = migrations[-1][0] if migrations else 0
    current = current_fork_version(db)
    if current > latest:
        logger.warning(
            "fork schema version %d is newer than the latest fork migration %d in this build; "
            "skipping fork migrations",
            current,
            latest,
        )
        return
    lock = " FOR UPDATE" if db.dialect == "postgresql" else ""
    for version, path in migrations:
        if version <= current:
            continue
        with db.transaction() as conn:
            if _read_version(conn, lock) >= version:
                continue
            for stmt in _split_pg_sql(path.read_text(encoding="utf-8")):
                conn.execute(stmt)
            step = _FORK_PY_STEPS.get(version)
            if step is not None:
                step(conn, db.dialect)
            conn.execute("UPDATE _fork_schema_version SET version = ? WHERE id = 1", (version,))
        logger.info("applied fork migration %s", path.name)
