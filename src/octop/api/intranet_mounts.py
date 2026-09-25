"""Upstream routers the intranet build does not mount (fork-owned).

List a router as ``"<module>:<attribute>"`` with the owning spec in a trailing
comment, e.g. ``"octop.api.routers.search:router",  # w1-03``. A router mounted
more than once is dropped everywhere. Physically deleted routers drop their
import and ``_RouterMount`` line in ``app.py`` instead.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from octop.api.app import _RouterMount

_FORK_DISABLED_MOUNTS: frozenset[str] = frozenset()


def resolve_router_ref(ref: str) -> APIRouter:
    """Resolve ``module:attribute``; import, attribute and type errors propagate (fail closed)."""
    module, _, attr = ref.partition(":")
    router = getattr(importlib.import_module(module), attr)
    if not isinstance(router, APIRouter):
        raise TypeError(f"{ref} is not a fastapi.APIRouter")
    return router


def without_fork_disabled(mounts: Sequence[_RouterMount]) -> list[_RouterMount]:
    """``mounts`` minus those whose router is (by identity) listed in ``_FORK_DISABLED_MOUNTS``."""
    disabled = {id(resolve_router_ref(ref)) for ref in _FORK_DISABLED_MOUNTS}
    return [m for m in mounts if id(m.router) not in disabled]
