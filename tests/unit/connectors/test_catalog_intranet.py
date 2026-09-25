"""Connector catalog = upstream ``_BASE`` minus ``_FORK_REMOVED`` plus ``_fork_entries()`` (w0-04)."""

from __future__ import annotations

import subprocess
import sys
from collections import Counter

from octop.infra.connectors import catalog, catalog_intranet
from octop.infra.connectors.catalog import list_catalog

# Fresh interpreter, fork module first: the sets must already apply when catalog.py
# composes _CATALOG at import, with _fork_entries() importing the dataclass lazily.
_FORK_PROBE = """
import dataclasses
from octop.infra.connectors import catalog_intranet as ci

def probe_entries():
    from octop.infra.connectors.catalog import _BASE
    return (dataclasses.replace(_BASE[-1], kind="bank-probe"),)

ci._FORK_REMOVED = frozenset({"notion"})
ci._fork_entries = probe_entries
from octop.infra.connectors.catalog import get_catalog_entry, list_catalog, mcp_oauth_remote_kinds
kinds = [e.kind for e in list_catalog()]
assert "notion" not in kinds and kinds[-1] == "bank-probe", kinds
assert get_catalog_entry("notion") is None and get_catalog_entry("bank-probe") is not None
assert "notion" not in mcp_oauth_remote_kinds()
"""


def test_catalog_is_composed_and_fork_sets_are_valid() -> None:
    expected = [e for e in catalog._BASE if e.kind not in catalog_intranet._FORK_REMOVED]
    assert list_catalog() == expected + list(catalog_intranet._fork_entries())
    stale = catalog_intranet._FORK_REMOVED - {e.kind for e in catalog._BASE}
    assert not stale, f"_FORK_REMOVED names kinds upstream no longer has: {sorted(stale)}"
    dupes = [k for k, n in Counter(e.kind for e in list_catalog()).items() if n > 1]
    assert not dupes, f"duplicate connector kinds: {dupes}"


def test_fork_sets_apply_at_import_in_either_order() -> None:
    subprocess.run([sys.executable, "-c", _FORK_PROBE], check=True)
    catalog_first = (
        "import octop.infra.connectors.catalog as c, octop.infra.connectors.catalog_intranet\n"
        "c.list_catalog()\n"
    )
    subprocess.run([sys.executable, "-c", catalog_first], check=True)
