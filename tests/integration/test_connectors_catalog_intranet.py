"""``GET /api/connectors/catalog`` serves the fork-composed catalog (w0-04)."""

from __future__ import annotations

import dataclasses

import pytest

from octop.infra.connectors import catalog, catalog_intranet


async def test_catalog_api_hides_removed_and_appends_fork_entries(
    env, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _srv, auth = env
    probe = dataclasses.replace(catalog._BASE[-1], kind="bank-probe")
    monkeypatch.setattr(catalog_intranet, "_FORK_REMOVED", frozenset({"notion"}))
    monkeypatch.setattr(catalog_intranet, "_fork_entries", lambda: (probe,))
    monkeypatch.setattr(catalog, "_CATALOG", catalog_intranet.compose_catalog(catalog._BASE))

    r = await client.get("/api/connectors/catalog", headers=auth)
    assert r.status_code == 200
    kinds = [e["kind"] for e in r.json()]
    assert "notion" not in kinds
    assert kinds[-1] == "bank-probe"
