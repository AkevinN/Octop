"""Demo fork migrations written under ``tmp_path`` — never into the real migrations dir."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from octop.infra.db import fork_migrate

# fork002 references a table created by upstream 015, proving fork runs last.
_DEMO = {
    1: ("demo", "CREATE TABLE IF NOT EXISTS fork_demo (id {int} PRIMARY KEY, note TEXT);\n"),
    2: (
        "demo_ref",
        "CREATE TABLE IF NOT EXISTS fork_demo_ref (id {int} PRIMARY KEY, "
        "identity_id {int} REFERENCES user_sso_identities(id));\n",
    ),
}


def write_demo_fork_migrations(directory: Path, versions: Iterable[int] = (1, 2)) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for version in versions:
        name, sql = _DEMO[version]
        stem = f"fork{version:03d}_{name}"
        (directory / f"{stem}.sql").write_text(sql.format(int="INTEGER"), encoding="utf-8")
        (directory / f"{stem}.pg.sql").write_text(sql.format(int="BIGINT"), encoding="utf-8")
    return directory


def use_fork_dir(monkeypatch: pytest.MonkeyPatch, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(fork_migrate, "_FORK_MIGRATIONS_DIR", directory)
    return directory
