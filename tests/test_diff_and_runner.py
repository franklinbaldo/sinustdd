from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sinustdd.adapters import CargoAdapter, LeanAdapter, VitestAdapter
from sinustdd.diff import classify_diff, get_head_commit, run_git
from sinustdd.runner import run_tests


def test_diff_and_git_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 1. run_git helper
    def mock_subprocess_run(cmd, cwd, capture_output, text, encoding, check):
        class MockProc:
            returncode = 0
            stdout = "M\tsrc/foo.py\nA\ttests/test_bar.py\n"
            stderr = ""

        return MockProc()

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)
    res = run_git("status", cwd=tmp_path)
    assert "src/foo.py" in res

    diff = classify_diff(tmp_path)
    assert diff.has_test_changes
    assert diff.has_production_changes
    assert "tests/test_bar.py" in diff.test_files_added
    assert "src/foo.py" in diff.production_files_modified

    head = get_head_commit(tmp_path)
    assert head


def test_adapter_specific_artifact_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Mock git diff returning diverse ecosystem artifacts
    def mock_subprocess_run(cmd, cwd, capture_output, text, encoding, check):
        class MockProc:
            returncode = 0
            stdout = (
                "A\ttests/auth.test.ts\n"
                "M\tsrc/auth.ts\n"
                "A\ttests/auth_test.rs\n"
                "M\tsrc/auth.rs\n"
                "A\ttests/AuthSpec.lean\n"
                "M\tAuth.lean\n"
            )
            stderr = ""

        return MockProc()

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    # 1. Vitest classification
    diff_ts = classify_diff(tmp_path, adapter=VitestAdapter())
    assert "tests/auth.test.ts" in diff_ts.test_files_added
    assert "src/auth.ts" in diff_ts.production_files_modified

    # 2. Cargo classification
    diff_rs = classify_diff(tmp_path, adapter=CargoAdapter())
    assert "tests/auth_test.rs" in diff_rs.test_files_added
    assert "src/auth.rs" in diff_rs.production_files_modified

    # 3. Lean classification
    diff_lean = classify_diff(tmp_path, adapter=LeanAdapter())
    assert "tests/AuthSpec.lean" in diff_lean.test_files_added
    assert "Auth.lean" in diff_lean.production_files_modified


def test_runner_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_pytest_run_fail(cmd, cwd, capture_output, text, encoding, check):
        class MockProc:
            returncode = 1
            stdout = "tests/test_a.py::test_fail FAILED\ntests/test_b.py::test_ok PASSED\n"
            stderr = ""

        return MockProc()

    monkeypatch.setattr(subprocess, "run", mock_pytest_run_fail)
    res = run_tests(tmp_path)
    assert not res.passed
    assert "tests/test_a.py::test_fail" in res.failed_tests
    assert "tests/test_b.py::test_ok" in res.passed_tests
    assert res.failure_fingerprint != ""
