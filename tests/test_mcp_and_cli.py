from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sinustdd.adapters import PytestAdapter, TestRun
from sinustdd.cli import info, status
from sinustdd.engine import SinusTDDEngine
from sinustdd.mcp import mcp


def test_cli_commands_coverage(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sinustdd.cli import begin, complete, green, red, refactor

    adapter = PytestAdapter()
    test_engine = SinusTDDEngine(tmp_path, adapter=adapter)
    monkeypatch.setattr("sinustdd.cli._engine", lambda: test_engine)

    def mock_run_tests_clean(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            tests_passed=["tests/test_a.py::test_init"],
            output="OK",
        )

    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_clean)

    info()
    status()
    begin()

    # Try invalid red
    red()

    # Mock red pass
    def mock_classify_diff_red(cwd: Path, base_ref: str | None = None):
        from sinustdd.diff import DiffClassification

        return DiffClassification(test_files_added=["tests/test_a.py"], has_test_changes=True)

    def mock_run_tests_failed(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=False,
            returncode=1,
            tests_failed=["tests/test_a.py::test_x"],
            output="FAILED",
            failure_fingerprint="123",
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff_red)
    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_failed)
    red()

    # Mock green pass
    def mock_classify_diff_green(cwd: Path, base_ref: str | None = None):
        from sinustdd.diff import DiffClassification

        return DiffClassification(
            test_files_added=["tests/test_a.py"],
            production_files_added=["src/a.py"],
            has_test_changes=True,
            has_production_changes=True,
        )

    def mock_run_tests_passed(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            tests_passed=["tests/test_a.py::test_x"],
            output="PASSED",
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff_green)
    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_passed)
    green()
    refactor()
    complete()

    captured = capsys.readouterr()
    assert "Cycle" in captured.out


def test_mcp_tools_and_execution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from sinustdd.mcp import (
        sinustdd_begin,
        sinustdd_complete,
        sinustdd_green,
        sinustdd_red,
        sinustdd_refactor,
        sinustdd_status,
    )

    adapter = PytestAdapter()
    test_engine = SinusTDDEngine(tmp_path, adapter=adapter)
    monkeypatch.setattr("sinustdd.mcp._engine", lambda: test_engine)

    # 1. Status idle
    st = sinustdd_status()
    assert not st["active"]

    # 2. Begin (mock clean baseline)
    def mock_run_tests_clean(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            tests_passed=["tests/test_b.py::test_init"],
            output="OK",
        )

    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_clean)
    b = sinustdd_begin()
    assert b["phase"] == "baseline"

    # 3. Mock red
    def mock_classify_diff_red(cwd: Path, base_ref: str | None = None):
        from sinustdd.diff import DiffClassification

        return DiffClassification(test_files_added=["tests/test_b.py"], has_test_changes=True)

    def mock_run_tests_failed(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=False,
            returncode=1,
            tests_failed=["tests/test_b.py::test_y"],
            output="FAILED",
            failure_fingerprint="456",
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff_red)
    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_failed)
    r = sinustdd_red()
    assert r["failed_tests"] == ["tests/test_b.py::test_y"]

    # 4. Mock green
    def mock_classify_diff_green(cwd: Path, base_ref: str | None = None):
        from sinustdd.diff import DiffClassification

        return DiffClassification(
            test_files_added=["tests/test_b.py"],
            production_files_added=["src/b.py"],
            has_test_changes=True,
            has_production_changes=True,
        )

    def mock_run_tests_passed(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            tests_passed=["tests/test_b.py::test_y"],
            output="PASSED",
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff_green)
    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_passed)
    g = sinustdd_green()
    assert "src/b.py" in g["production_files_modified"]

    # 5. Refactor & complete
    ref = sinustdd_refactor()
    assert "tests_passed" in ref
    comp = sinustdd_complete()
    assert comp["phase"] == "completed"

    async def _check() -> None:
        tools = await mcp.list_tools()
        assert len(tools) == 6

    asyncio.run(_check())
