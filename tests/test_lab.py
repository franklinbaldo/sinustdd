from __future__ import annotations

from pathlib import Path

import pytest

from sinustdd.adapters import PytestAdapter, TestRun
from sinustdd.lab import CausalLab, GuardMode


def test_causal_lab_init_and_refs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lab = CausalLab(tmp_path, mode=GuardMode.CHECKPOINT)
    assert lab.mode == GuardMode.CHECKPOINT

    calls: list[list[str]] = []

    def mock_run_git(*args: str, cwd: Path | None = None) -> str:
        calls.append(list(args))
        return "ok"

    monkeypatch.setattr(lab, "_run_git", mock_run_git)

    ref = lab.create_checkpoint_ref("cycle-10", "red", "commit_sha_123")
    assert ref == "refs/sinustdd/cycles/cycle-10/red"
    assert ["update-ref", "refs/sinustdd/cycles/cycle-10/red", "commit_sha_123"] in calls


def test_causal_lab_worktree_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lab = CausalLab(tmp_path, mode=GuardMode.OBSERVE)
    calls: list[list[str]] = []

    def mock_run_git(*args: str, cwd: Path | None = None) -> str:
        calls.append(list(args))
        return "ok"

    monkeypatch.setattr(lab, "_run_git", mock_run_git)

    wt = lab.setup_worktree("base_sha")
    assert wt == lab.lab_dir
    lab.teardown()


def test_causal_lab_reenact_cycle_simulation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab = CausalLab(tmp_path, mode=GuardMode.OBSERVE)
    adapter = PytestAdapter()

    # Mock setup and teardown worktree
    fake_lab_dir = tmp_path / "fake_lab"
    fake_lab_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(lab, "setup_worktree", lambda base: fake_lab_dir)
    monkeypatch.setattr(lab, "teardown", lambda: None)

    # 1. Happy path: baseline green -> inject test -> fail -> inject prod -> green
    step = 0

    def mock_run_tests(root: Path, selection: list[str] | None = None) -> TestRun:
        nonlocal step
        step += 1
        if step == 1:
            return TestRun(
                adapter_name="pytest",
                passed=True,
                returncode=0,
                output="OK",
                tests_passed=["test_1"],
            )
        elif step == 2:
            return TestRun(
                adapter_name="pytest",
                passed=False,
                returncode=1,
                output="FAILED",
                tests_failed=["test_2"],
                failure_fingerprint="sig2",
            )
        else:
            return TestRun(
                adapter_name="pytest",
                passed=True,
                returncode=0,
                output="OK",
                tests_passed=["test_1", "test_2"],
            )

    monkeypatch.setattr(adapter, "run_tests", mock_run_tests)

    # Create dummy source files
    t_file = tmp_path / "tests" / "test_x.py"
    t_file.parent.mkdir(parents=True, exist_ok=True)
    t_file.write_text("assert 1 == 2", encoding="utf-8")

    p_file = tmp_path / "src" / "x.py"
    p_file.parent.mkdir(parents=True, exist_ok=True)
    p_file.write_text("x = 1", encoding="utf-8")

    res = lab.reenact_cycle(
        baseline_commit="commit_base",
        test_files=["tests/test_x.py"],
        production_files=["src/x.py"],
        adapter=adapter,
    )
    assert res.valid
    assert res.red_verified
    assert res.green_verified
    assert res.baseline_intact


def test_causal_lab_reenact_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lab = CausalLab(tmp_path, mode=GuardMode.OBSERVE)
    adapter = PytestAdapter()

    fake_lab_dir = tmp_path / "fake_lab"
    fake_lab_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(lab, "setup_worktree", lambda base: fake_lab_dir)
    monkeypatch.setattr(lab, "teardown", lambda: None)

    # Case: broken baseline
    def mock_broken_base(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=False,
            returncode=1,
            output="FAIL",
            tests_failed=["test_legacy"],
        )

    monkeypatch.setattr(adapter, "run_tests", mock_broken_base)
    r1 = lab.reenact_cycle(
        baseline_commit="base",
        test_files=[],
        production_files=[],
        adapter=adapter,
    )
    assert not r1.valid
    assert not r1.baseline_intact

    # Case: tautological test
    def mock_tautology(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            output="OK",
            tests_passed=["test_tautology"],
        )

    monkeypatch.setattr(adapter, "run_tests", mock_tautology)
    r2 = lab.reenact_cycle(
        baseline_commit="base",
        test_files=[],
        production_files=[],
        adapter=adapter,
    )
    assert not r2.valid
    assert not r2.red_verified
