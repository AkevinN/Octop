"""``_FORK_DISABLED_MOUNTS`` keeps listed upstream routers out of ``build_app`` (w0-04)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from octop.api import intranet_mounts
from octop.api.app import build_app
from octop.config import CapabilitiesConfig, MobileCapabilities, OctopConfig

SEARCH = "octop.api.routers.search:router"
MOBILE = "octop.api.routers.mobile:router"  # mounted by the separate ``if enable_mobile:`` block
_CFG = OctopConfig(capabilities=CapabilitiesConfig(mobile=MobileCapabilities(enabled=True)))


def _build(monkeypatch: pytest.MonkeyPatch, refs: set[str]) -> FastAPI:
    monkeypatch.setattr(intranet_mounts, "_FORK_DISABLED_MOUNTS", frozenset(refs))
    return build_app(SimpleNamespace(services=None, config=_CFG))


def test_empty_set_returns_mounts_unchanged() -> None:
    mounts = [SimpleNamespace(router=object()) for _ in range(3)]
    kept = intranet_mounts.without_fork_disabled(mounts)
    assert [id(m) for m in kept] == [id(m) for m in mounts]


# Every registered ref must name a router build_app really mounts; SEARCH is the probe.
@pytest.mark.parametrize("ref", sorted(intranet_mounts._FORK_DISABLED_MOUNTS | {SEARCH, MOBILE}))
def test_disabled_router_is_not_mounted(monkeypatch: pytest.MonkeyPatch, ref: str) -> None:
    mounted = set(_build(monkeypatch, set()).openapi()["paths"])
    remaining = set(_build(monkeypatch, {ref}).openapi()["paths"])
    assert mounted - remaining, f"{ref} is not mounted by build_app"
    assert "/api/auth/login" in remaining
    if ref == SEARCH:
        assert mounted - remaining == {"/api/search/{provider_id}/test"}


@pytest.mark.parametrize(
    "ref",
    [
        "octop.api.routers.search",
        "octop.api.routers.no_such:router",
        "octop.api.routers.search:no_such",
        "octop.api.app:build_app",
    ],
)
def test_invalid_ref_fails_build(monkeypatch: pytest.MonkeyPatch, ref: str) -> None:
    with pytest.raises((ImportError, AttributeError, TypeError)):
        _build(monkeypatch, {ref})
