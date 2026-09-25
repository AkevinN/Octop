"""``intranet_allow_*`` config keys: file values, env overrides, first write, type checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from octop.config import OctopConfig, load_config

KEYS = ("intranet_allow_cidrs", "intranet_allow_host_suffixes", "intranet_allow_http")


def _values(cfg: OctopConfig) -> tuple[object, ...]:
    return tuple(getattr(cfg, key) for key in KEYS)


def test_file_values_then_env_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "intranet_allow_cidrs": ["10.0.0.0/8"],
                "intranet_allow_host_suffixes": ["bank.intra"],
                "intranet_allow_http": True,
            }
        )
    )
    assert _values(load_config(path)) == (["10.0.0.0/8"], ["bank.intra"], True)

    monkeypatch.setenv("OCTOP_INTRANET_ALLOW_CIDRS", "10.0.0.0/8, 192.168.10.0/24")
    monkeypatch.setenv("OCTOP_INTRANET_ALLOW_HOST_SUFFIXES", "corp.bank.intra")
    monkeypatch.setenv("OCTOP_INTRANET_ALLOW_HTTP", "false")
    assert _values(load_config(path)) == (
        ["10.0.0.0/8", "192.168.10.0/24"],
        ["corp.bank.intra"],
        False,
    )


def test_first_write_contains_defaults(tmp_path: Path):
    path = tmp_path / "config.json"
    load_config(path)
    written = json.loads(path.read_text())
    assert [written[key] for key in KEYS] == [[], [], False]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("intranet_allow_cidrs", "10.0.0.0/8"),
        ("intranet_allow_cidrs", [1]),
        ("intranet_allow_host_suffixes", "bank.intra"),
        ("intranet_allow_http", "yes"),
    ],
)
def test_wrong_type_names_key_without_echoing_file(tmp_path: Path, key: str, value: object):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({key: value, "database": {"password": "sentinel-s3cret"}}))
    with pytest.raises(ValueError, match=key) as exc:
        load_config(path)
    assert "sentinel-s3cret" not in str(exc.value)
