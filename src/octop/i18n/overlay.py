"""Intranet fork i18n overlay (fork-owned; upstream never edits this module).

Fork strings live in ``octop/i18n/intranet/{en,zh}.json`` and are deep-merged over
the upstream bundles by ``loader._load_all``. Never add or delete keys in the
upstream ``en.json`` / ``zh.json`` from the fork; keep the en/zh overlay key sets equal.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Any

_OVERLAY_ROOT: Traversable = resources.files("octop.i18n").joinpath("intranet")


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """New dict: nested mappings merge recursively, otherwise the overlay value wins.

    Mirrors i18next ``addResourceBundle(lng, ns, bundle, true, true)``; neither
    argument is mutated.
    """
    out = dict(base)
    for key, value in overlay.items():
        prev = out.get(key)
        if isinstance(prev, Mapping) and isinstance(value, Mapping):
            value = deep_merge(prev, value)
        out[key] = value
    return out


def read_overlay(locale: str) -> dict[str, Any]:
    """Parse ``intranet/<locale>.json``; a missing, invalid or non-object file raises."""
    text = _OVERLAY_ROOT.joinpath(f"{locale}.json").read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"i18n overlay intranet/{locale}.json must be a JSON object")
    return data
