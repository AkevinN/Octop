"""Intranet i18n overlays: merge semantics, lookups and en/zh parity (w0-04)."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.support import i18n_bundles as bundles

from octop.api.routers import i18n as i18n_router
from octop.i18n import all_keys_for_locale, all_skill_labels, all_tool_labels, lookup, overlay, tr
from octop.i18n.loader import _load_all, flatten_keys

PROBE = "intranet-probe"
_UPSTREAM_DIRS = {
    "backend": bundles.REPO_ROOT / "src" / "octop" / "i18n",
    "dashboard": bundles.DASHBOARD_LOCALES,
}


@pytest.fixture
def overlay_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Point the backend overlay at ``tmp_path``; ``_load_all`` is re-read on both sides."""
    monkeypatch.setattr(overlay, "_OVERLAY_ROOT", tmp_path)
    _load_all.cache_clear()
    yield tmp_path
    _load_all.cache_clear()


def _shape_conflicts(
    base: Mapping[str, Any], extra: Mapping[str, Any], prefix: str = ""
) -> list[str]:
    out: list[str] = []
    for key, value in extra.items():
        if key not in base:
            continue
        prev, path = base[key], f"{prefix}{key}"
        if isinstance(prev, Mapping) and isinstance(value, Mapping):
            out += _shape_conflicts(prev, value, f"{path}.")
        elif isinstance(prev, Mapping) or isinstance(value, Mapping):
            out.append(path)
    return out


def test_deep_merge_overrides_leaves_keeps_siblings_and_copies() -> None:
    base = {"a": {"x": "1", "y": "2"}, "b": "3"}
    extra = {"a": {"x": "X", "n": {"k": "v"}}, "c": "C"}
    before = copy.deepcopy((base, extra))
    merged = overlay.deep_merge(base, extra)
    assert merged == {"a": {"x": "X", "y": "2", "n": {"k": "v"}}, "b": "3", "c": "C"}
    assert (base, extra) == before


def test_backend_overlay_reaches_every_lookup_and_api(overlay_dir: Path) -> None:
    probe = {
        "slash": {"help": {"title": PROBE}},
        "tools": {"intranet_probe_tool": PROBE},
        "skills": {PROBE: PROBE},
        "intranet_probe": {"k": PROBE},
    }
    for loc in ("en", "zh"):
        (overlay_dir / f"{loc}.json").write_text(json.dumps(probe), encoding="utf-8")

    assert tr("slash.help.title", "en") == PROBE
    assert lookup("intranet_probe.k", "zh") == PROBE
    assert "intranet_probe.k" in all_keys_for_locale("en")
    assert all_tool_labels("zh")["intranet_probe_tool"] == PROBE
    assert all_tool_labels("zh")["read_file"] == "读取文件"  # upstream sibling untouched
    assert all_skill_labels("en")[PROBE] == PROBE

    app = FastAPI()
    app.include_router(i18n_router.router, prefix="/api")
    with TestClient(app) as client:
        for path, key in (("/api/i18n/tools", "intranet_probe_tool"), ("/api/i18n/skills", PROBE)):
            body = client.get(path, headers={"Accept-Language": "zh"}).json()
            assert body["labels"][key] == PROBE


@pytest.mark.parametrize(
    ("content", "error"),
    [(None, FileNotFoundError), ("{bad json", json.JSONDecodeError), ("[]", ValueError)],
)
def test_bad_backend_overlay_fails_first_load(
    overlay_dir: Path, content: str | None, error: type[Exception]
) -> None:
    (overlay_dir / "zh.json").write_text("{}", encoding="utf-8")
    if content is not None:
        (overlay_dir / "en.json").write_text(content, encoding="utf-8")
    with pytest.raises(error):
        _load_all()


@pytest.mark.parametrize("upstream", _UPSTREAM_DIRS.values(), ids=list(_UPSTREAM_DIRS))
def test_overlay_en_zh_parity_and_shape(upstream: Path) -> None:
    extras = {loc: bundles.read_json(upstream / "intranet" / f"{loc}.json") for loc in ("en", "zh")}
    diff = flatten_keys(extras["en"]) ^ flatten_keys(extras["zh"])
    assert not diff, f"en/zh overlay keys differ: {sorted(diff)}"
    for loc, extra in extras.items():
        conflicts = _shape_conflicts(bundles.read_json(upstream / f"{loc}.json"), extra)
        assert not conflicts, f"{loc} overlay swaps a string/object at: {conflicts}"


def test_merged_dashboard_bundle_applies_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "en.json").write_text('{"common": {"save": "X"}}', encoding="utf-8")
    monkeypatch.setattr(bundles, "DASHBOARD_OVERLAY_DIR", tmp_path)
    upstream = bundles.read_json(bundles.DASHBOARD_LOCALES / "en.json")
    assert bundles.merged_dashboard_bundle("en")["common"] == {**upstream["common"], "save": "X"}
