"""Harmonic state machine engine orchestrating causal TDD proof verification."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sinustdd.adapters import VerificationAdapter, get_adapter
from sinustdd.behavior import BehaviorMode, TestSpec
from sinustdd.diff import (
    classify_diff,
    compute_test_files_hashes,
    get_head_commit,
)
from sinustdd.evidence import verify_ledger, write_phase_evidence
from sinustdd.models import (
    BaselineWitness,
    Cycle,
    GreenWitness,
    IntentRecord,
    OutcomeReflection,
    Phase,
    RedWitness,
    RefactorWitness,
    SpecificationSource,
    Transition,
)
from sinustdd.store import SessionStore
from sinustdd.workspace_guard import WorkspaceGuard


def _safe_classify_diff(root: Path, base_ref: str | None, adapter: VerificationAdapter) -> Any:
    """Invoke classify_diff safely supporting mock callables with or without adapter kwarg."""
    try:
        return classify_diff(root, base_ref, adapter=adapter)
    except TypeError:
        return classify_diff(root, base_ref)


class StateTransitionError(Exception):
    """Raised when an invalid or unverified phase transition is attempted."""


class SinusTDDEngine:
    def __init__(
        self,
        root: Path,
        adapter: VerificationAdapter | None = None,
        behavior_mode: BehaviorMode = BehaviorMode.OFF,
        workspace_guard: WorkspaceGuard | None = None,
    ) -> None:
        self.root = root
        self.store = SessionStore(root)
        self.adapter = adapter or get_adapter(root)
        self.behavior_mode = behavior_mode
        self.workspace_guard = workspace_guard

    def _verify_ledger_integrity(self, cycle_id: str) -> None:
        if not verify_ledger(self.root, cycle_id):
            msg = f"Ledger verification failed for {cycle_id}! Chain is tampered or non-contiguous."
            raise StateTransitionError(msg)

    def status(self) -> dict[str, Any]:
        cycle = self.store.load_active_cycle()
        if cycle is None:
            return {
                "active": False,
                "phase": Phase.IDLE,
                "theta": Phase.IDLE.theta,
                "behavior_mode": self.behavior_mode.value,
                "workspace_guard_enabled": self.workspace_guard is not None,
                "message": "No active TDD cycle. Run sinustdd begin to start.",
            }
        return {
            "active": True,
            "cycle_id": cycle.cycle_id,
            "phase": cycle.phase,
            "theta": cycle.phase.theta,
            "behavior_mode": self.behavior_mode.value,
            "workspace_guard_enabled": self.workspace_guard is not None,
            "specification_source": cycle.specification_source.value,
            "specification_reference": cycle.specification_reference,
            "intent_record": (cycle.intent_record.model_dump() if cycle.intent_record else None),
            "outcome_reflection": (
                cycle.outcome_reflection.model_dump() if cycle.outcome_reflection else None
            ),
            "test_spec_id": cycle.test_spec_id,
            "baseline_commit": cycle.baseline_commit,
            "baseline_witness": (
                cycle.baseline_witness.model_dump() if cycle.baseline_witness else None
            ),
            "red_witness": cycle.red_witness.model_dump() if cycle.red_witness else None,
            "green_witness": cycle.green_witness.model_dump() if cycle.green_witness else None,
            "refactor_witness": (
                cycle.refactor_witness.model_dump() if cycle.refactor_witness else None
            ),
            "evidence_chain": cycle.evidence_chain,
        }

    def begin(
        self,
        *,
        label: str = "",
        specification_source: SpecificationSource = SpecificationSource.UNSPECIFIED,
        specification_reference: str = "",
        intent_record: IntentRecord | None = None,
        test_spec: TestSpec | None = None,
    ) -> Cycle:
        active = self.store.load_active_cycle()
        if active is not None and active.phase != Phase.COMPLETED:
            msg = f"Cycle {active.cycle_id} is already in progress (phase: {active.phase})."
            raise StateTransitionError(msg)

        if self.behavior_mode == BehaviorMode.REQUIRED and test_spec is None:
            msg = (
                "BehaviorMode.REQUIRED is active: Cannot begin cycle without a valid TestSpec. "
                "Compile behavior scenarios to TestSpec or provide an explicit specification."
            )
            raise StateTransitionError(msg)

        test_run = self.adapter.run_tests(self.root)
        if not test_run.passed:
            msg = (
                f"Cannot begin TDD cycle: baseline suite has failing tests! "
                f"Failed: {test_run.tests_failed}. The baseline must be completely green."
            )
            raise StateTransitionError(msg)

        head = get_head_commit(self.root)
        cycle_id = f"cycle-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        suite_sig = hashlib.sha256("\n".join(sorted(test_run.tests_passed)).encode()).hexdigest()
        baseline_wit = BaselineWitness(
            baseline_commit=head,
            tests_passed=test_run.tests_passed,
            suite_fingerprint=suite_sig,
        )

        payload: dict[str, Any] = baseline_wit.model_dump()
        if label:
            payload["label"] = label
        payload["specification_source"] = specification_source.value
        if specification_reference:
            payload["specification_reference"] = specification_reference
        if intent_record:
            payload["intent_record"] = intent_record.model_dump()
        if test_spec:
            payload["test_spec"] = test_spec.model_dump()

        ev_path, _ = write_phase_evidence(
            root=self.root,
            cycle_id=cycle_id,
            phase=Phase.BASELINE,
            repository_ref=head,
            payload=payload,
        )

        self._verify_ledger_integrity(cycle_id)

        cycle = Cycle(
            cycle_id=cycle_id,
            label=label,
            phase=Phase.BASELINE,
            baseline_commit=head,
            specification_source=specification_source,
            specification_reference=specification_reference,
            intent_record=intent_record,
            test_spec_id=test_spec.spec_id if test_spec else None,
            baseline_witness=baseline_wit,
            transitions=[Transition(from_phase=Phase.IDLE, to_phase=Phase.BASELINE)],
            evidence_chain=[str(ev_path)],
        )

        self.store.save_active_cycle(cycle)
        if self.workspace_guard is not None:
            self.workspace_guard.enforce_red()
        return cycle

    def mark_red(self) -> RedWitness:
        cycle = self.store.load_active_cycle()
        if cycle is None:
            msg = "No active cycle found. Run sinustdd begin first."
            raise StateTransitionError(msg)
        if cycle.phase not in (Phase.BASELINE, Phase.RED):
            msg = f"Cannot transition to RED from phase '{cycle.phase}'."
            raise StateTransitionError(msg)

        self._verify_ledger_integrity(cycle.cycle_id)

        diff = _safe_classify_diff(self.root, cycle.baseline_commit, self.adapter)
        if diff.has_production_changes:
            msg = (
                "Invariant violation in RED phase: production code was modified! "
                f"Modified: {diff.production_files_modified + diff.production_files_added}. "
                "You must write ONLY tests during the RED phase."
            )
            raise StateTransitionError(msg)

        if not diff.has_test_changes:
            msg = (
                "No test changes detected. You must add or modify a test to prove "
                "a new failure mode."
            )
            raise StateTransitionError(msg)

        test_files = diff.test_files_added + diff.test_files_modified
        test_run = self.adapter.run_tests(self.root)

        if test_run.passed or not test_run.tests_failed:
            msg = (
                "Tautological test detected! The new test PASSED against baseline production code. "
                "A valid RED phase requires at least one failing test demonstrating "
                "the missing capability."
            )
            raise StateTransitionError(msg)

        relevant_failures: list[str] = []
        if test_run.structured_failures:
            for sf in test_run.structured_failures:
                if any(
                    tf in sf.source_file.replace("\\", "/") or sf.source_file in tf
                    for tf in test_files
                ):
                    relevant_failures.append(sf.test_id)
        else:
            for f in test_run.tests_failed:
                if any(tf in f.replace("\\", "/") for tf in test_files):
                    relevant_failures.append(f)

        if not relevant_failures:
            msg = (
                "Disconnected failure detected! The failing tests "
                f"({test_run.tests_failed}) do not originate from the tests "
                f"introduced in this phase ({test_files})."
            )
            raise StateTransitionError(msg)

        test_hashes = compute_test_files_hashes(self.root, test_files)

        witness = RedWitness(
            test_files=test_files,
            test_files_hashes=test_hashes,
            failed_tests=relevant_failures,
            failure_fingerprint=test_run.failure_fingerprint,
            baseline_commit=cycle.baseline_commit,
        )

        ev_path, _ = write_phase_evidence(
            root=self.root,
            cycle_id=cycle.cycle_id,
            phase=Phase.RED,
            repository_ref=get_head_commit(self.root),
            payload=witness.model_dump(),
        )

        self._verify_ledger_integrity(cycle.cycle_id)

        from_phase = cycle.phase
        cycle.phase = Phase.RED
        cycle.red_witness = witness
        cycle.transitions.append(Transition(from_phase=from_phase, to_phase=Phase.RED))
        cycle.evidence_chain.append(str(ev_path))

        self.store.save_active_cycle(cycle)
        if self.workspace_guard is not None:
            self.workspace_guard.restore()
        return witness

    def mark_green(self) -> GreenWitness:
        cycle = self.store.load_active_cycle()
        if cycle is None or cycle.red_witness is None:
            msg = (
                "Cannot transition to GREEN without a recorded RedWitness. Run sinustdd red first."
            )
            raise StateTransitionError(msg)
        if cycle.phase not in (Phase.RED, Phase.GREEN):
            msg = f"Cannot transition to GREEN from phase '{cycle.phase}'."
            raise StateTransitionError(msg)

        self._verify_ledger_integrity(cycle.cycle_id)

        current_test_hashes = compute_test_files_hashes(self.root, cycle.red_witness.test_files)
        for t_file, original_hash in cycle.red_witness.test_files_hashes.items():
            current_hash = current_test_hashes.get(t_file, "")
            if current_hash != original_hash:
                msg = (
                    f"Test assertion tampering detected! Test file '{t_file}' was modified "
                    "after RedWitness was recorded. Goalposts cannot be moved during GREEN phase."
                )
                raise StateTransitionError(msg)

        diff = _safe_classify_diff(self.root, cycle.baseline_commit, self.adapter)
        if not diff.has_production_changes:
            msg = (
                "Invariant violation in GREEN phase: no production code changes detected! "
                "You must implement the feature in src/ to resolve the red witness."
            )
            raise StateTransitionError(msg)

        test_run = self.adapter.run_tests(self.root)
        if not test_run.passed:
            msg = (
                f"Tests are still failing! Failed: {test_run.tests_failed}. "
                "GREEN phase requires all tests to pass."
            )
            raise StateTransitionError(msg)

        witness = GreenWitness(
            production_files_modified=diff.production_files_added + diff.production_files_modified,
            test_files_hashes_verified=current_test_hashes,
            tests_passed=test_run.tests_passed,
        )

        ev_path, _ = write_phase_evidence(
            root=self.root,
            cycle_id=cycle.cycle_id,
            phase=Phase.GREEN,
            repository_ref=get_head_commit(self.root),
            payload=witness.model_dump(),
        )

        self._verify_ledger_integrity(cycle.cycle_id)

        from_phase = cycle.phase
        cycle.phase = Phase.GREEN
        cycle.green_witness = witness
        cycle.transitions.append(Transition(from_phase=from_phase, to_phase=Phase.GREEN))
        cycle.evidence_chain.append(str(ev_path))

        self.store.save_active_cycle(cycle)
        return witness

    def mark_refactor(self) -> RefactorWitness:
        cycle = self.store.load_active_cycle()
        if cycle is None or cycle.green_witness is None:
            msg = "Cannot transition to REFACTOR before achieving GREEN phase."
            raise StateTransitionError(msg)

        self._verify_ledger_integrity(cycle.cycle_id)

        test_run = self.adapter.run_tests(self.root)
        if not test_run.passed:
            msg = f"Refactoring broke the test suite! Failed: {test_run.tests_failed}."
            raise StateTransitionError(msg)

        refactor_wit = RefactorWitness(tests_passed=test_run.tests_passed)

        ev_path, _ = write_phase_evidence(
            root=self.root,
            cycle_id=cycle.cycle_id,
            phase=Phase.REFACTOR,
            repository_ref=get_head_commit(self.root),
            payload=refactor_wit.model_dump(),
        )

        self._verify_ledger_integrity(cycle.cycle_id)

        from_phase = cycle.phase
        cycle.phase = Phase.REFACTOR
        cycle.refactor_witness = refactor_wit
        cycle.transitions.append(Transition(from_phase=from_phase, to_phase=Phase.REFACTOR))
        cycle.evidence_chain.append(str(ev_path))

        self.store.save_active_cycle(cycle)
        return refactor_wit

    def complete(self, reflection: OutcomeReflection | None = None) -> Cycle:
        cycle = self.store.load_active_cycle()
        if cycle is None:
            msg = "No active cycle to complete."
            raise StateTransitionError(msg)
        if cycle.phase not in (Phase.GREEN, Phase.REFACTOR):
            msg = f"Cannot complete cycle in phase '{cycle.phase}'. Must be GREEN or REFACTOR."
            raise StateTransitionError(msg)

        self._verify_ledger_integrity(cycle.cycle_id)

        test_run = self.adapter.run_tests(self.root)
        if not test_run.passed:
            msg = "Cannot complete cycle: tests are currently failing."
            raise StateTransitionError(msg)

        from_phase = cycle.phase
        cycle.phase = Phase.COMPLETED
        cycle.completed_at = datetime.now(UTC)
        cycle.outcome_reflection = reflection
        cycle.transitions.append(Transition(from_phase=from_phase, to_phase=Phase.COMPLETED))
        self.store.archive_cycle(cycle)
        return cycle
