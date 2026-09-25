"""``tests.support.pg_strict``: only a skipped ``postgresql`` test turns a green run red."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.support import pg_strict

OK = pytest.ExitCode.OK
FAILED = pytest.ExitCode.TESTS_FAILED


@pytest.mark.parametrize(
    ("skipped", "keywords", "exitstatus", "expected"),
    [
        (True, {"postgresql": 1}, OK, FAILED),
        (True, {"test_requires_postgresql": 1}, OK, OK),
        (False, {"postgresql": 1}, OK, OK),
        (True, {"postgresql": 1}, FAILED, FAILED),
    ],
    ids=["pg-skip", "other-skip", "pg-pass", "already-failed"],
)
def test_sessionfinish_exit_status(
    monkeypatch: pytest.MonkeyPatch,
    skipped: bool,
    keywords: dict[str, int],
    exitstatus: pytest.ExitCode,
    expected: pytest.ExitCode,
) -> None:
    monkeypatch.setattr(pg_strict, "_skipped", [])
    report = SimpleNamespace(skipped=skipped, keywords=keywords, nodeid="t.py::test_x")
    pg_strict.pytest_runtest_logreport(report)  # type: ignore[arg-type]
    session = SimpleNamespace(exitstatus=exitstatus)
    pg_strict.pytest_sessionfinish(session, exitstatus)  # type: ignore[arg-type]
    assert session.exitstatus == expected
