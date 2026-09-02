from __future__ import annotations

from pathlib import Path

import pytest

from sinustdd.adapters import PytestAdapter, TestRun
from sinustdd.diff import DiffClassification
from sinustdd.evidence import verify_ledger, write_phase_evidence
from sinustdd.models import Phase
from sinustdd.observer import Observer, ViolationEvent


def test_observer_subscription_and_notification() -> None:
    obs = Observer()
    delivered: list[ViolationEvent] = []

    obs.subscribe(lambda evt: delivered.append(evt))

    event = ViolationEvent(
        code="PROD_BEFORE_RED",
        cycle_id="cycle-1",
        inferred_phase=Phase.BASELINE,
        expected_invariant="production_diff == empty",
        observed_evidence="src/foo.py was modified",
        suggested_recovery="Revert src/foo.py and write a failing test first",
    )

    obs.notify_violation(event)
    assert len(delivered) == 1
    assert delivered[0].code == "PROD_BEFORE_RED"


def test_write_phase_evidence_and_ledger_verification(tmp_path: Path) -> None:
    # 1. Write baseline evidence
    p1, h1 = write_phase_evidence(
        root=tmp_path,
        cycle_id="cycle-abc",
        phase=Phase.BASELINE,
        repository_ref="commit-1",
        payload={"tests_passed": ["tests/test_1.py::test_init"]},
    )
    assert p1.is_file()
    assert verify_ledger(tmp_path, "cycle-abc")

    # 2. Write red evidence chained to baseline
    p2, h2 = write_phase_evidence(
        root=tmp_path,
        cycle_id="cycle-abc",
        phase=Phase.RED,
        repository_ref="commit-2",
        payload={"failed_tests": ["tests/test_2.py::test_fail"]},
    )
    assert p2.is_file()
    assert verify_ledger(tmp_path, "cycle-abc")

    # 3. Duplicate write should error
    with pytest.raises(FileExistsError):
        write_phase_evidence(
            root=tmp_path,
            cycle_id="cycle-abc",
            phase=Phase.RED,
            repository_ref="commit-2",
            payload={"failed_tests": ["tests/test_2.py::test_fail"]},
        )

    # 4. Tampering test: modify previous evidence file manually
    p1.write_text(
        p1.read_text(encoding="utf-8").replace("commit-1", "commit-hacked"), encoding="utf-8"
    )
    assert not verify_ledger(tmp_path, "cycle-abc")


def test_verify_ledger_gap_detection(tmp_path: Path) -> None:
    """Gap attack: ledger has baseline and green but skips red."""
    p_base, _ = write_phase_evidence(
        root=tmp_path,
        cycle_id="cycle-gap",
        phase=Phase.BASELINE,
        repository_ref="commit-1",
        payload={"tests_passed": ["tests/test_1.py::test_ok"]},
    )
    # Manually write green skipping red
    p_green, _ = write_phase_evidence(
        root=tmp_path,
        cycle_id="cycle-gap",
        phase=Phase.GREEN,
        repository_ref="commit-2",
        payload={"tests_passed": ["tests/test_1.py::test_ok"]},
    )
    assert p_base.is_file()
    assert p_green.is_file()
    assert not verify_ledger(tmp_path, "cycle-gap")


def test_observer_observe_once_flows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = PytestAdapter()
    obs = Observer(tmp_path, adapter=adapter)
    delivered: list[ViolationEvent] = []
    obs.subscribe(lambda e: delivered.append(e))

    # 1. Idle repository clean -> auto begins baseline
    def mock_run_tests_clean(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            tests_passed=["tests/test_old.py::test_ok"],
            output="OK",
        )

    def mock_diff_clean(cwd: Path, base_ref: str | None = None):
        return DiffClassification()

    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_clean)
    monkeypatch.setattr("sinustdd.observer.classify_diff", mock_diff_clean)

    res = obs.observe_once()
    assert res["transition_recorded"]
    assert res["inferred_phase"] == Phase.BASELINE
    assert res["silent"]

    # 2. Hard violation: Agent writes production before Red
    def mock_diff_prod(cwd: Path, base_ref: str | None = None):
        return DiffClassification(
            production_files_modified=["src/foo.py"], has_production_changes=True
        )

    monkeypatch.setattr("sinustdd.observer.classify_diff", mock_diff_prod)
    res_violation = obs.observe_once()
    assert res_violation["violation_detected"]
    assert res_violation["code"] == "PROD_BEFORE_RED"
    assert len(delivered) == 1

    # 3. Valid RED transition: new test fails against baseline
    test_file = tmp_path / "tests" / "test_new.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_x(): assert 1 == 2", encoding="utf-8")

    def mock_diff_red(cwd: Path, base_ref: str | None = None):
        return DiffClassification(test_files_added=["tests/test_new.py"], has_test_changes=True)

    def mock_run_tests_red(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=False,
            returncode=1,
            tests_failed=["tests/test_new.py::test_x"],
            output="FAILED",
            failure_fingerprint="sig123",
        )

    monkeypatch.setattr("sinustdd.observer.classify_diff", mock_diff_red)
    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_red)
    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_diff_red)

    res_red = obs.observe_once()
    assert res_red["transition_recorded"]
    assert res_red["inferred_phase"] == Phase.RED
    assert res_red["silent"]

    # 4. Valid GREEN transition: production code implemented, all tests pass
    def mock_diff_green(cwd: Path, base_ref: str | None = None):
        return DiffClassification(
            test_files_added=["tests/test_new.py"],
            production_files_added=["src/feature.py"],
            has_test_changes=True,
            has_production_changes=True,
        )

    monkeypatch.setattr("sinustdd.observer.classify_diff", mock_diff_green)
    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_clean)
    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_diff_green)

    res_green = obs.observe_once()
    assert res_green["transition_recorded"]
    assert res_green["inferred_phase"] == Phase.GREEN
    assert res_green["silent"]
