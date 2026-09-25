"""Merged (upstream + intranet overlay) i18n bundles, as the server and dashboard see them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from octop.i18n.loader import _load_all
from octop.i18n.overlay import deep_merge
from octop.infra.utils.locale import Locale

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_LOCALES = REPO_ROOT / "dashboard" / "src" / "locales"
DASHBOARD_OVERLAY_DIR = DASHBOARD_LOCALES / "intranet"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def merged_backend_bundle(locale: Locale) -> dict[str, Any]:
    return _load_all()[locale]


def merged_dashboard_bundle(locale: Locale) -> dict[str, Any]:
    """Mirror of ``i18n.ts``: upstream locale JSON with the intranet overlay deep-merged over it."""
    upstream = read_json(DASHBOARD_LOCALES / f"{locale}.json")
    return deep_merge(upstream, read_json(DASHBOARD_OVERLAY_DIR / f"{locale}.json"))
