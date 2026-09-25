"""Test-process-only exemptions for login captcha and step-up auth dependencies.

The root ``conftest.py`` relaxes these guards for every test by default; a test
opts back into the real guards with ``@pytest.mark.real_auth_guards`` or by
listing its module in ``REAL_AUTH_GUARD_MODULES``. Everything here works through
``monkeypatch`` / ``app.dependency_overrides`` inside the test process — production
code must never grow a matching config switch (``test_no_production_exemption_switch``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI

REAL_AUTH_GUARDS_MARK = "real_auth_guards"

# Dotted paths of captcha checks bound where the login path calls them.
CAPTCHA_SEAMS: tuple[str, ...] = ("octop.api.routers.auth.ensure_captcha",)

# ``{dependency: replacement}`` applied to every test app. Keys must be stable
# module-level callables: factory closures (e.g. ``require_permission(...)``) are
# new objects per call, so a factory must ``Depends`` a stable inner dependency
# and register that one instead. Empty until a spec adds such a dependency.
DEPENDENCY_OVERRIDES: dict[Callable[..., Any], Callable[..., Any]] = {}

# Test modules that always run the real guards (repo-relative nodeid paths).
REAL_AUTH_GUARD_MODULES: frozenset[str] = frozenset({"tests/integration/test_captcha_api.py"})

_active = False


async def captcha_exempt(*_args: Any, **_kwargs: Any) -> None:
    return None


def wants_real_guards(node: pytest.Item) -> bool:
    return (
        node.get_closest_marker(REAL_AUTH_GUARDS_MARK) is not None
        or node.nodeid.split("::", 1)[0] in REAL_AUTH_GUARD_MODULES
    )


def relax_auth_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    for seam in CAPTCHA_SEAMS:
        monkeypatch.setattr(seam, captcha_exempt)
    monkeypatch.setattr(f"{__name__}._active", True)


def apply_test_dependency_overrides(app: FastAPI) -> None:
    if _active:
        app.dependency_overrides.update(DEPENDENCY_OVERRIDES)
