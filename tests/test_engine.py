from __future__ import annotations

from pathlib import Path

import pytest

from sinustdd.adapters import PytestAdapter, TestRun
from sinustdd.behavior import BehaviorMode, TestSpec
from sinustdd.engine import SinusTDDEngine, StateTransitionError
from sinustdd.models import (
    IntentRecord,
    OutcomeReflection,
    Phase,
    SpecificationSource,
)


def test_engine_lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = PytestAdapter()
    engine = SinusTDDEngine(tmp_path, adapter=adapter)

    # 1. Initial state
    st = engine.status()
    assert not st["active"]
    assert st["phase"] == Phase.IDLE
    assert st["theta"] == 0.0

    # 2. Begin cycle (mock passing baseline) with IntentRecord
    def mock_run_tests_clean(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            tests_passed=["tests/test_x.py::test_1"],
            output="OK",
        )

    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_clean)
    intent = IntentRecord(
        source_reference="RFC-0042",
        intent="Reject expired tokens while keeping valid tokens functional with test_new",
        interpretation="Reject expired tokens while keeping valid tokens functional",
        intended_change="src/auth.py verification logic",
        intended_proof="tests/test_feature.py::test_new",
    )
    cycle = engine.begin(
        specification_source=SpecificationSource.RFC,
        specification_reference="RFC-0042",
        intent_record=intent,
    )
    assert cycle.phase == Phase.BASELINE
    assert cycle.specification_source == SpecificationSource.RFC
    assert cycle.specification_reference == "RFC-0042"
    assert cycle.intent_record is not None
    assert "Reject expired tokens" in cycle.intent_record.interpretation
    assert engine.status()["active"]
    assert len(cycle.evidence_chain) == 1

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

    def mock_run_tests_failed(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=False,
            returncode=1,
            output="FAILED tests/test_feature.py::test_new",
            tests_failed=["tests/test_feature.py::test_new"],
            failure_fingerprint="abc123hash",
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff_red)
    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_failed)

    red_witness = engine.mark_red()
    assert red_witness.failed_tests == ["tests/test_feature.py::test_new"]
    assert engine.status()["phase"] == Phase.RED

    active_c = engine.store.load_active_cycle()
    assert active_c is not None
    assert len(active_c.transitions) == 2
    # Verify from_phase transition correctness: BASELINE -> RED
    assert active_c.transitions[-1].from_phase == Phase.BASELINE

    # 5. Mock green phase transition: production implemented, all tests pass
    def mock_classify_diff_green(cwd: Path, base_ref: str | None = None):
        from sinustdd.diff import DiffClassification

        return DiffClassification(
            test_files_added=["tests/test_feature.py"],
            production_files_added=["src/feature.py"],
            has_test_changes=True,
            has_production_changes=True,
        )

    def mock_run_tests_passed(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            output="PASSED tests/test_feature.py::test_new",
            tests_passed=["tests/test_feature.py::test_new"],
        )

    monkeypatch.setattr("sinustdd.engine.classify_diff", mock_classify_diff_green)
    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_passed)

    green_witness = engine.mark_green()
    assert "src/feature.py" in green_witness.production_files_modified
    assert engine.status()["phase"] == Phase.GREEN

    active_c2 = engine.store.load_active_cycle()
    assert active_c2 is not None
    assert active_c2.transitions[-1].from_phase == Phase.RED

    # 6. Refactor phase
    refactor_wit = engine.mark_refactor()
    assert len(refactor_wit.tests_passed) > 0
    assert engine.status()["phase"] == Phase.REFACTOR

    active_c3 = engine.store.load_active_cycle()
    assert active_c3 is not None
    assert active_c3.transitions[-1].from_phase == Phase.GREEN

    # 7. Complete cycle with Socratic OutcomeReflection
    reflection = OutcomeReflection(
        diverged_from_intent=False,
        reflection_notes="Implemented exact RFC expiration semantics without regression",
        discovered_insights="Session store requires atomic TTL checks",
    )
    completed_cycle = engine.complete(reflection=reflection)
    assert completed_cycle.phase == Phase.COMPLETED
    assert not engine.status()["active"]
    assert completed_cycle.outcome_reflection is not None
    assert not completed_cycle.outcome_reflection.diverged_from_intent
    assert completed_cycle.transitions[-1].from_phase == Phase.REFACTOR


def test_behavior_mode_required_enforcement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = PytestAdapter()
    engine = SinusTDDEngine(tmp_path, adapter=adapter, behavior_mode=BehaviorMode.REQUIRED)

    def mock_run_tests_clean(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            tests_passed=["tests/test_1.py::test_init"],
            output="OK",
        )

    monkeypatch.setattr(adapter, "run_tests", mock_run_tests_clean)

    # 1. Attempt begin without test_spec -> Rejected!
    with pytest.raises(StateTransitionError, match="BehaviorMode.REQUIRED is active"):
        engine.begin()

    # 2. Begin with valid TestSpec -> Accepted!
    spec = TestSpec(
        spec_id="spec_auth_login",
        scenario_ref="Valid credentials login",
        target_unit="auth",
        given=["Valid user"],
        when="Submits login",
        then=["Receives JWT"],
    )
    cycle = engine.begin(
        specification_source=SpecificationSource.ACCEPTANCE_CRITERIA,
        specification_reference="JIRA-402",
        test_spec=spec,
    )
    assert cycle.phase == Phase.BASELINE
    assert cycle.test_spec_id == "spec_auth_login"
