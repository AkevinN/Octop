"""Test-only auth guard exemptions stay wired to real code and out of production."""

from __future__ import annotations

import dataclasses
import pkgutil
import re
from pathlib import Path

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from tests.support import auth_guards
from tests.support.auth_guards import (
    CAPTCHA_SEAMS,
    REAL_AUTH_GUARD_MODULES,
    apply_test_dependency_overrides,
    captcha_exempt,
)

from octop.config import OctopConfig

_SWITCH = re.compile(
    r"(bypass|exempt|skip)_?(captcha|reauth)|(captcha|reauth)_?(bypass|exempt|skip)",
    re.IGNORECASE,
)


@pytest.mark.real_auth_guards
def test_captcha_seams_resolve() -> None:
    for seam in CAPTCHA_SEAMS:
        target = pkgutil.resolve_name(seam)
        assert callable(target) and target is not captcha_exempt, seam


def test_captcha_seams_patched_by_default() -> None:
    assert all(pkgutil.resolve_name(seam) is captcha_exempt for seam in CAPTCHA_SEAMS)


def test_real_guard_modules_exist(repo_root: Path) -> None:
    stale = sorted(m for m in REAL_AUTH_GUARD_MODULES if not (repo_root / m).is_file())
    assert stale == [], f"update REAL_AUTH_GUARD_MODULES: {stale}"


async def _deny() -> None:
    raise HTTPException(status_code=403)


async def _allow() -> None:
    return None


@pytest.mark.parametrize(
    "status",
    [200, pytest.param(403, marks=pytest.mark.real_auth_guards)],
)
async def test_dependency_overrides_follow_opt_out(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    app = FastAPI()

    @app.get("/guarded", dependencies=[Depends(_deny)])
    async def _guarded() -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setitem(auth_guards.DEPENDENCY_OVERRIDES, _deny, _allow)
    apply_test_dependency_overrides(app)
    assert bool(app.dependency_overrides) is (status == 200)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        assert (await client.get("/guarded")).status_code == status


def test_no_production_exemption_switch(repo_root: Path) -> None:
    assert [f.name for f in dataclasses.fields(OctopConfig) if _SWITCH.search(f.name)] == []
    src = repo_root / "src" / "octop"
    offenders = []
    for path in src.rglob("*.py"):
        if path.relative_to(src).parts[0] == "dashboard":
            continue
        text = path.read_text(encoding="utf-8")
        if "tests.support" in text or _SWITCH.search(text):
            offenders.append(path.relative_to(repo_root).as_posix())
    assert offenders == []
