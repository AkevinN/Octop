"""Intranet connector catalog overrides (fork-owned).

``catalog.py`` builds ``_CATALOG`` with :func:`compose_catalog`. Never import
``catalog`` at module level here (circular import); import the dataclasses inside
:func:`_fork_entries`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from octop.infra.connectors.catalog import ConnectorCatalogEntry

# Upstream kinds hidden in the intranet build; name the owning spec in a trailing comment.
_FORK_REMOVED: frozenset[str] = frozenset()


def _fork_entries() -> tuple[ConnectorCatalogEntry, ...]:
    """Intranet-only entries, listed after every upstream entry."""
    return ()


def compose_catalog(
    base: tuple[ConnectorCatalogEntry, ...],
) -> tuple[ConnectorCatalogEntry, ...]:
    return tuple(e for e in base if e.kind not in _FORK_REMOVED) + _fork_entries()
