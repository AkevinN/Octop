"""pytest plugin for ``make test-postgresql``: a skipped PostgreSQL test fails the run.

``requires_postgresql`` skips every ``postgresql``-marked test when
``OCTOP_TEST_DATABASE_URL`` is unset, and some tests skip when client tools
(``pg_dump``) are missing. Inside the dedicated PG gate a skip means "not
verified", so this plugin turns an otherwise green session red and lists the
skipped node ids. Load explicitly with ``-p tests.support.pg_strict``.
"""

from __future__ import annotations

import pytest

MARKER = "postgresql"
_skipped: list[str] = []


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped and MARKER in report.keywords:
        _skipped.append(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _skipped and exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    if _skipped:
        terminalreporter.write_line(
            f"[pg-strict] {len(_skipped)} postgresql test(s) skipped; failing the run:", red=True
        )
        for nodeid in _skipped:
            terminalreporter.write_line(f"  {nodeid}")
