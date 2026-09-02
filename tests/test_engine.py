from __future__ import annotations

from pathlib import Path

import pytest

from sinustdd.engine import SinusTDDEngine, StateTransitionError
from sinustdd.models import Phase


def test_engine_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = SinusTDDEngine(tmp_path)

    # 1. Initial state
    st = engine.status()
    assert not st["active"]
    assert st["phase"] == Phase.IDLE
    assert st["theta"] == 0.0

    # 2. Begin cycle (mock passing baseline)
    def mock_run_tests_clean(cwd: Path):
        from sinustdd.runner import TestExecutionResult

        return TestExecutionResult(
            passed=True, returncode=0, passed_tests=["tests/test_x.py::test_1"], output="OK"
        )

    monkeypatch.setattr("sinustdd.engine.run_tests", mock_run_tests_clean)
    cycle = engine.begin()
    assert cycle.phase == Phase.BASELINE
    assert engine.status()["active"]

    # 3. Cannot begin twice
    with pytest.raises(StateTransitionError):
        engine.begin()

    # 4. Mock red phase failure: test failure with only tests modified
    def mock_classify_diff_red(cwd: Path, base_ref: str | None = None):
        from sinustdd.diff import DiffClassification

        return DiffClassification(
            test_files_added=["tests/test_feature.py"],
            has_test_changes=True,
            has_production_changes=False,
        )

    def mock_run_tests_failed(cwd: Path):
        from sinustdd.runner import TestExecutionResult

        return TestExecutionResult(
            passed=False,
            returncode=1,
            output="FAILED tests/test_feature.py::test_new",
            failed_tests=["tests/test_feature.py::test_new"],
            failure_fingerprint="abc123hash",
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff_red)
    monkeypatch.setattr("sinustdd.engine.run_tests", mock_run_tests_failed)

    red_witness = engine.mark_red()
    assert red_witness.failed_tests == ["tests/test_feature.py::test_new"]
    assert engine.status()["phase"] == Phase.RED

    # 5. Mock green phase transition: production implemented, all tests pass
    def mock_classify_diff_green(cwd: Path, base_ref: str | None = None):
        from sinustdd.diff import DiffClassification

        return DiffClassification(
            test_files_added=["tests/test_feature.py"],
            production_files_added=["src/feature.py"],
            has_test_changes=True,
            has_production_changes=True,
        )

    def mock_run_tests_passed(cwd: Path):
        from sinustdd.runner import TestExecutionResult

        return TestExecutionResult(
            passed=True,
            returncode=0,
            output="PASSED tests/test_feature.py::test_new",
            passed_tests=["tests/test_feature.py::test_new"],
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff_green)
    monkeypatch.setattr("sinustdd.engine.run_tests", mock_run_tests_passed)

    green_witness = engine.mark_green()
    assert "src/feature.py" in green_witness.production_files_modified
    assert engine.status()["phase"] == Phase.GREEN

    # 6. Refactor phase
    refactor_wit = engine.mark_refactor()
    assert len(refactor_wit.tests_passed) > 0
    assert engine.status()["phase"] == Phase.REFACTOR

    # 7. Complete cycle
    completed_cycle = engine.complete()
    assert completed_cycle.phase == Phase.COMPLETED
    assert not engine.status()["active"]
