"""Non-Python fork isolation hooks survive upstream merges (w0-04).

The Python hooks (i18n loader, ``_mount_routers``, ``_CATALOG``) are guarded by
behaviour tests; these three files have no pytest-visible behaviour.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("rel_path", "pattern", "min_count"),
    [
        ("dashboard/src/i18n.ts", r'from "\./i18nIntranet"', 1),
        ("dashboard/src/i18n.ts", r"applyIntranetOverlay\(", 2),
        ("Makefile.intranet", r"^relock:", 1),
        ("Makefile.intranet", r'^\t@echo "  relock ', 1),
        ("docs/api.md", r"\A(?:[^\n]*\n){0,4}[^\n]*api-intranet\.md", 1),
    ],
    ids=["i18n-import", "i18n-calls", "relock-target", "relock-help", "api-md-pointer"],
)
def test_fork_hook_present(rel_path: str, pattern: str, min_count: int) -> None:
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    found = len(re.findall(pattern, text, re.MULTILINE))
    assert found >= min_count, f"{rel_path}: fork hook {pattern!r} found {found}x"
