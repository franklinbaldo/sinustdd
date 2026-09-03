from __future__ import annotations

from pathlib import Path

import pytest

from sinustdd.adapters import PytestAdapter, TestRun
from sinustdd.diff import DiffClassification
from sinustdd.engine import SinusTDDEngine
from sinustdd.models import Cycle, GreenWitness, Phase
from sinustdd.workspace_guard import WorkspaceGuard


class RecordingGuard(WorkspaceGuard):
    def __init__(self) -> None:
        self.enforce_red_calls = 0
        self.enforce_green_calls: list[list[str]] = []
        self.restore_calls = 0

    def enforce_red(self) -> list[Path]:
        self.enforce_red_calls += 1
        return []

    def enforce_green(self, verification_paths: list[str]) -> list[Path]:
        self.enforce_green_calls.append(list(verification_paths))
        return []

    def restore(self) -> list[Path]:
        self.restore_calls += 1
        return []

    def explain(self, path: Path) -> str:
        return f"recording guard: {path}"


def test_engine_enforces_red_after_baseline_and_green_after_red_witness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = PytestAdapter()
    guard = RecordingGuard()

    test_file = tmp_path / "tests" / "test_feature.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_new(): assert False\n", encoding="utf-8")

    def clean_run(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            output="PASSED baseline",
            tests_passed=["tests/test_existing.py::test_existing"],
        )

    monkeypatch.setattr(adapter, "run_tests", clean_run)

    engine = SinusTDDEngine(tmp_path, adapter=adapter, workspace_guard=guard)
    engine.begin(label="guard RED workspace")

    assert guard.enforce_red_calls == 1
    assert guard.enforce_green_calls == []
    assert guard.restore_calls == 0

    monkeypatch.setattr(
        "sinustdd.engine.classify_diff",
        lambda *args, **kwargs: DiffClassification(
            test_files_added=["tests/test_feature.py"],
            has_test_changes=True,
            has_production_changes=False,
        ),
    )

    def red_run(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=False,
            returncode=1,
            output="FAILED tests/test_feature.py::test_new",
            tests_failed=["tests/test_feature.py::test_new"],
            failure_fingerprint="workspace-guard-red",
        )

    monkeypatch.setattr(adapter, "run_tests", red_run)

    engine.mark_red()

    assert guard.enforce_red_calls == 1
    assert guard.enforce_green_calls == [["tests/test_feature.py"]]
    assert guard.restore_calls == 0


def test_engine_restores_guard_when_cycle_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = PytestAdapter()
    guard = RecordingGuard()
    engine = SinusTDDEngine(tmp_path, adapter=adapter, workspace_guard=guard)

    assert engine.store.load_active_cycle() is None

    completed_candidate = Cycle(
        cycle_id="cycle-complete-guard",
        phase=Phase.GREEN,
        baseline_commit="baseline",
        green_witness=GreenWitness(
            production_files_modified=["src/feature.py"],
            test_files_hashes_verified={},
            tests_passed=["tests/test_feature.py::test_feature"],
        ),
    )
    engine.store.save_active_cycle(completed_candidate)
    monkeypatch.setattr(engine, "_verify_ledger_integrity", lambda cycle_id: None)
    monkeypatch.setattr(
        adapter,
        "run_tests",
        lambda root, selection=None: TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            output="PASSED",
            tests_passed=["tests/test_feature.py::test_feature"],
        ),
    )

    engine.complete()

    assert guard.restore_calls == 1
