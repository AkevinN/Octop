"""Fork CI gates (w0-02) must survive upstream syncs of ci.yml and the root Makefile."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_DSN = "OCTOP_TEST_DATABASE_URL"


def _ci_jobs() -> dict[str, Any]:
    ci = _REPO / ".github" / "workflows" / "ci.yml"
    jobs: dict[str, Any] = yaml.safe_load(ci.read_text(encoding="utf-8"))["jobs"]
    return jobs


@pytest.mark.parametrize(
    ("job", "targets"),
    [
        ("frontend", ["make install-frontend", "make check-frontend"]),
        ("postgresql", ["make test-postgresql"]),
    ],
)
def test_ci_fork_job_runs_make_targets(job: str, targets: list[str]) -> None:
    spec = _ci_jobs()[job]
    assert "sync-develop-after-" in spec["if"]
    runs = [step.get("run") for step in spec["steps"]]
    assert all(target in runs for target in targets)


def test_ci_postgresql_service_and_dsn_scoped_to_its_step() -> None:
    jobs = _ci_jobs()
    pg = jobs.pop("postgresql")
    assert pg["services"]["postgres"]["image"].startswith("postgres:")
    assert [s["run"] for s in pg["steps"] if _DSN in s.get("env", {})] == ["make test-postgresql"]
    assert _DSN not in json.dumps({k: v for k, v in pg.items() if k != "steps"})
    assert _DSN not in json.dumps(jobs)


def test_makefile_intranet_defines_gate_targets() -> None:
    root = (_REPO / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^include Makefile\.intranet$", root, re.M)
    intranet = (_REPO / "Makefile.intranet").read_text(encoding="utf-8")
    for target in (
        "help-intranet",
        "install-frontend",
        "test-frontend",
        "check-frontend",
        "test-postgresql",
    ):
        assert re.search(rf"^{target}:", intranet, re.M), target
