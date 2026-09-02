from __future__ import annotations

from pathlib import Path

import pytest

from sinustdd.diff import DiffClassification
from sinustdd.engine import SinusTDDEngine, StateTransitionError
from sinustdd.models import Phase
from sinustdd.runner import TestExecutionResult


def test_adversarial_baseline_already_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attack 1: Agent tries to begin a cycle while tests are already broken."""
    engine = SinusTDDEngine(tmp_path)

    def mock_run_tests_broken(cwd: Path):
        return TestExecutionResult(
            passed=False,
            returncode=1,
            output="FAILED tests/test_old.py::test_legacy",
            failed_tests=["tests/test_old.py::test_legacy"],
        )

    monkeypatch.setattr("sinustdd.engine.run_tests", mock_run_tests_broken)

    with pytest.raises(StateTransitionError, match="baseline suite has failing tests"):
        engine.begin()


def test_adversarial_red_with_production_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attack 2: Agent tries to write production code during RED phase."""
    engine = SinusTDDEngine(tmp_path)

    def mock_run_tests_clean(cwd: Path):
        return TestExecutionResult(
            passed=True, returncode=0, passed_tests=["tests/test_old.py::test_ok"], output="OK"
        )

    monkeypatch.setattr("sinustdd.engine.run_tests", mock_run_tests_clean)
    engine.begin()

    def mock_classify_diff_cheating(cwd: Path, base_ref: str | None = None):
        return DiffClassification(
            test_files_added=["tests/test_new.py"],
            production_files_added=["src/cheat.py"],
            has_test_changes=True,
            has_production_changes=True,
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff_cheating)

    with pytest.raises(StateTransitionError, match="production code was modified"):
        engine.mark_red()


def test_adversarial_red_disconnected_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attack 3: Agent introduces test_a.py, but an unrelated test_b.py failed."""
    engine = SinusTDDEngine(tmp_path)

    def mock_run_tests_clean(cwd: Path):
        return TestExecutionResult(
            passed=True, returncode=0, passed_tests=["tests/test_old.py::test_ok"], output="OK"
        )

    monkeypatch.setattr("sinustdd.engine.run_tests", mock_run_tests_clean)
    engine.begin()

    def mock_classify_diff(cwd: Path, base_ref: str | None = None):
        return DiffClassification(
            test_files_added=["tests/test_a.py"],
            has_test_changes=True,
            has_production_changes=False,
        )

    def mock_run_tests_unrelated_fail(cwd: Path):
        return TestExecutionResult(
            passed=False,
            returncode=1,
            output="FAILED tests/test_other.py::test_unrelated",
            failed_tests=["tests/test_other.py::test_unrelated"],
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff)
    monkeypatch.setattr("sinustdd.engine.run_tests", mock_run_tests_unrelated_fail)

    with pytest.raises(StateTransitionError, match="Disconnected failure detected"):
        engine.mark_red()


def test_adversarial_green_tampering_test_assertions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attack 4: Agent records RED witness, then weakens/modifies the test file during GREEN."""
    engine = SinusTDDEngine(tmp_path)

    # 1. Baseline ok
    def mock_run_tests_clean(cwd: Path):
        return TestExecutionResult(
            passed=True, returncode=0, passed_tests=["tests/test_old.py::test_ok"], output="OK"
        )

    monkeypatch.setattr("sinustdd.engine.run_tests", mock_run_tests_clean)
    engine.begin()

    # 2. Legitimate RED
    test_file = tmp_path / "tests" / "test_auth.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_strict(): assert 1 == 2", encoding="utf-8")

    def mock_classify_diff_red(cwd: Path, base_ref: str | None = None):
        return DiffClassification(
            test_files_added=["tests/test_auth.py"],
            has_test_changes=True,
            has_production_changes=False,
        )

    def mock_run_tests_fail(cwd: Path):
        return TestExecutionResult(
            passed=False,
            returncode=1,
            output="FAILED tests/test_auth.py::test_strict",
            failed_tests=["tests/test_auth.py::test_strict"],
            failure_fingerprint="auth_fail_hash",
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff_red)
    monkeypatch.setattr("sinustdd.engine.run_tests", mock_run_tests_fail)

    engine.mark_red()
    assert engine.status()["phase"] == Phase.RED

    # 3. Agent tampers with test file to make it trivially pass ("moving the goalposts")
    test_file.write_text("def test_strict(): assert True", encoding="utf-8")

    def mock_classify_diff_green(cwd: Path, base_ref: str | None = None):
        return DiffClassification(
            test_files_added=["tests/test_auth.py"],
            production_files_added=["src/auth.py"],
            has_test_changes=True,
            has_production_changes=True,
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff_green)
    monkeypatch.setattr("sinustdd.engine.run_tests", mock_run_tests_clean)

    with pytest.raises(StateTransitionError, match="Test assertion tampering detected"):
        engine.mark_green()
