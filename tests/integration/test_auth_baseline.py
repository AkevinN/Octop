"""Self-tests for the shared test auth baseline (w0-03)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.users.permissions import ALL_PERMISSION_KEYS, PERMISSIONS
from tests.support import scenarios
from tests.support.auth import (
    ADMIN_SLOTS,
    TEST_ADMIN_ACCOUNTS,
    TEST_PASSWORD,
    bearer,
    bootstrap_admin,
)
from tests.support.auth_guards import CAPTCHA_SEAMS, DEPENDENCY_OVERRIDES


@pytest.mark.parametrize(
    "account",
    [{}, {"username": "root2", "password": "OtherPass34"}],
    ids=["default", "custom"],
)
async def test_bootstrap_admin_grants_all_permission_keys(
    patched_app_client: Any, account: dict[str, str]
) -> None:
    client, _srv, home = patched_app_client
    r = await bootstrap_admin(client, home, **account)
    assert r.status_code == 201
    body = r.json()
    row = await client.get(f"/api/users/{body['id']}", headers=bearer(body["access_token"]))
    assert row.json()["permissions"] == sorted(ALL_PERMISSION_KEYS)


async def test_bootstrap_admin_raises_when_grant_fails(
    patched_app_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _refuse(*_args: Any) -> None:
        raise OctopError(ErrorCode.FORBIDDEN, "grant refused")

    monkeypatch.setattr("octop.api.routers.users._assert_can_assign", _refuse)
    client, _srv, home = patched_app_client
    with pytest.raises(httpx.HTTPStatusError):
        await bootstrap_admin(client, home)


async def test_env_admin_survives_simulated_bypass_removal(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "octop.api.deps.user_has_permission",
        lambda user, key: key in PERMISSIONS and key in (user.permissions or []),
    )
    client, _srv, auth = env
    for path in ("/api/admin/providers", "/api/users", "/api/admin/audit-log"):
        assert (await client.get(path, headers=auth)).status_code == 200, path


@pytest.mark.real_auth_guards
async def test_captcha_seam_is_on_login_path(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _require(*_args: Any, **_kwargs: Any) -> None:
        raise OctopError(ErrorCode.CAPTCHA_REQUIRED, "captcha required")

    for seam in CAPTCHA_SEAMS:
        monkeypatch.setattr(seam, _require)
    client, _srv, _auth = env
    r = await client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "CAPTCHA_REQUIRED"


async def _probe() -> None:
    return None


async def _probe_replacement() -> None:
    return None


@pytest.fixture
def _registered_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(DEPENDENCY_OVERRIDES, _probe, _probe_replacement)


@pytest.mark.usefixtures("_registered_probe")
async def test_test_apps_apply_registered_overrides(env: Any, env_terminal: Any) -> None:
    for app in (env[0]._octop_app, env_terminal[1]):
        assert app.dependency_overrides[_probe] is _probe_replacement


async def test_env_admins_reserve_three_slots(env: Any, env_admins: Any) -> None:
    client, srv, admins = env_admins
    assert env[1] is srv
    assert env[2] == admins.system
    assert set(admins.usernames) == set(ADMIN_SLOTS)
    for slot in ADMIN_SLOTS:
        me = await client.get("/api/auth/me", headers=getattr(admins, slot))
        assert me.json()["username"] == admins.usernames[slot]
    # Until w3-03 ships three accounts, every slot aliases the single admin.
    assert admins.system == admins.security == admins.audit
    assert set(TEST_ADMIN_ACCOUNTS.values()) == {("admin", TEST_PASSWORD)}


@pytest.mark.parametrize("split", [True, False], ids=["user_admin_auth", "default"])
async def test_boundary_env_routes_user_management(
    env_admins: Any, monkeypatch: pytest.MonkeyPatch, split: bool
) -> None:
    client, srv, admins = env_admins
    admin_auth = dict(admins.system)  # distinct object, so ``is`` tells the two apart
    seen: list[dict[str, str]] = []
    for name in ("create_user", "resolve_user_id"):
        original = getattr(scenarios, name)

        async def _spy(
            c: Any, auth: dict[str, str], *a: Any, _orig: Any = original, **kw: Any
        ) -> Any:
            seen.append(auth)
            return await _orig(c, auth, *a, **kw)

        monkeypatch.setattr(scenarios, name, _spy)

    extra = {"user_admin_auth": admins.security} if split else {}
    await scenarios.bootstrap_boundary_env(client, srv, admin_auth, **extra)
    expected = admins.security if split else admin_auth
    assert len(seen) == 4
    assert all(auth is expected for auth in seen)
