"""Harmonic state machine engine orchestrating causal TDD proof verification."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sinustdd.diff import (
    classify_diff,
    compute_test_files_hashes,
    get_head_commit,
)
from sinustdd.evidence import write_phase_evidence
from sinustdd.models import (
    BaselineWitness,
    Cycle,
    GreenWitness,
    Phase,
    RedWitness,
    RefactorWitness,
    Transition,
)
from sinustdd.runner import run_tests
from sinustdd.store import SessionStore


class StateTransitionError(Exception):
    """Raised when an invalid or unverified phase transition is attempted."""


class SinusTDDEngine:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = SessionStore(root)

    def status(self) -> dict[str, Any]:
        cycle = self.store.load_active_cycle()
        if cycle is None:
            return {
                "active": False,
                "phase": Phase.IDLE,
                "theta": Phase.IDLE.theta,
                "message": "No active TDD cycle. Run sinustdd begin to start.",
            }
        return {
            "active": True,
            "cycle_id": cycle.cycle_id,
            "phase": cycle.phase,
            "theta": cycle.phase.theta,
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

    def begin(self) -> Cycle:
        active = self.store.load_active_cycle()
        if active is not None and active.phase != Phase.COMPLETED:
            msg = f"Cycle {active.cycle_id} is already in progress (phase: {active.phase})."
            raise StateTransitionError(msg)

        # 1. Verify baseline suite is 100% GREEN before starting
        test_result = run_tests(self.root)
        if not test_result.passed:
            msg = (
                f"Cannot begin TDD cycle: baseline suite has failing tests! "
                f"Failed: {test_result.failed_tests}. The baseline must be completely green."
            )
            raise StateTransitionError(msg)

        head = get_head_commit(self.root)
        cycle_id = f"cycle-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"

        suite_sig = hashlib.sha256("\n".join(sorted(test_result.passed_tests)).encode()).hexdigest()
        baseline_wit = BaselineWitness(
            baseline_commit=head,
            tests_passed=test_result.passed_tests,
            suite_fingerprint=suite_sig,
        )

        cycle = Cycle(
            cycle_id=cycle_id,
            phase=Phase.BASELINE,
            baseline_commit=head,
            baseline_witness=baseline_wit,
            transitions=[Transition(from_phase=Phase.IDLE, to_phase=Phase.BASELINE)],
        )

        # Write OKF Evidence for Baseline
        try:
            ev_path, _ = write_phase_evidence(
                root=self.root,
                cycle_id=cycle_id,
                phase=Phase.BASELINE,
                repository_ref=head,
                payload=baseline_wit.model_dump(),
            )
            cycle.evidence_chain.append(str(ev_path))
        except Exception:
            pass

        self.store.save_active_cycle(cycle)
        return cycle

    def mark_red(self) -> RedWitness:
        cycle = self.store.load_active_cycle()
        if cycle is None:
            msg = "No active cycle found. Run sinustdd begin first."
            raise StateTransitionError(msg)
        if cycle.phase not in (Phase.BASELINE, Phase.RED):
            msg = f"Cannot transition to RED from phase '{cycle.phase}'."
            raise StateTransitionError(msg)

        # Check Diff Invariants
        diff = classify_diff(self.root, cycle.baseline_commit)
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
        test_result = run_tests(self.root)

        if test_result.passed or not test_result.failed_tests:
            msg = (
                "Tautological test detected! The new test PASSED against baseline production code. "
                "A valid RED phase requires at least one failing test demonstrating "
                "the missing capability."
            )
            raise StateTransitionError(msg)

        # Ensure the failure is explicitly tied to the modified/added test files
        relevant_failures = [
            f for f in test_result.failed_tests if any(t_file in f for t_file in test_files)
        ]
        if not relevant_failures:
            msg = (
                "Disconnected failure detected! The failing tests "
                f"({test_result.failed_tests}) do not originate from the tests "
                f"introduced in this phase ({test_files})."
            )
            raise StateTransitionError(msg)

        # Freeze and hash the test files at the exact moment of RED witness
        test_hashes = compute_test_files_hashes(self.root, test_files)

        witness = RedWitness(
            test_files=test_files,
            test_files_hashes=test_hashes,
            failed_tests=relevant_failures,
            failure_fingerprint=test_result.failure_fingerprint,
            baseline_commit=cycle.baseline_commit,
        )

        cycle.phase = Phase.RED
        cycle.red_witness = witness
        cycle.transitions.append(Transition(from_phase=cycle.phase, to_phase=Phase.RED))

        try:
            ev_path, _ = write_phase_evidence(
                root=self.root,
                cycle_id=cycle.cycle_id,
                phase=Phase.RED,
                repository_ref=get_head_commit(self.root),
                payload=witness.model_dump(),
            )
            cycle.evidence_chain.append(str(ev_path))
        except Exception:
            pass

        self.store.save_active_cycle(cycle)
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

        # 1. VERIFY FROZEN TESTS: Test files recorded during RED cannot have been modified
        current_test_hashes = compute_test_files_hashes(self.root, cycle.red_witness.test_files)
        for t_file, original_hash in cycle.red_witness.test_files_hashes.items():
            current_hash = current_test_hashes.get(t_file, "")
            if current_hash != original_hash:
                msg = (
                    f"Test assertion tampering detected! Test file '{t_file}' was modified "
                    "after RedWitness was recorded. Goalposts cannot be moved during GREEN phase."
                )
                raise StateTransitionError(msg)

        # 2. Verify Production Code Was Implemented
        diff = classify_diff(self.root, cycle.baseline_commit)
        if not diff.has_production_changes:
            msg = (
                "Invariant violation in GREEN phase: no production code changes detected! "
                "You must implement the feature in src/ to resolve the red witness."
            )
            raise StateTransitionError(msg)

        # 3. Verify Entire Suite (Baseline + New Test) is Green
        test_result = run_tests(self.root)
        if not test_result.passed:
            msg = (
                f"Tests are still failing! Failed: {test_result.failed_tests}. "
                "GREEN phase requires all tests to pass."
            )
            raise StateTransitionError(msg)

        witness = GreenWitness(
            production_files_modified=diff.production_files_added + diff.production_files_modified,
            test_files_hashes_verified=current_test_hashes,
            tests_passed=test_result.passed_tests,
        )

        cycle.phase = Phase.GREEN
        cycle.green_witness = witness
        cycle.transitions.append(Transition(from_phase=cycle.phase, to_phase=Phase.GREEN))

        try:
            ev_path, _ = write_phase_evidence(
                root=self.root,
                cycle_id=cycle.cycle_id,
                phase=Phase.GREEN,
                repository_ref=get_head_commit(self.root),
                payload=witness.model_dump(),
            )
            cycle.evidence_chain.append(str(ev_path))
        except Exception:
            pass

        self.store.save_active_cycle(cycle)
        return witness

    def mark_refactor(self) -> RefactorWitness:
        cycle = self.store.load_active_cycle()
        if cycle is None or cycle.green_witness is None:
            msg = "Cannot transition to REFACTOR before achieving GREEN phase."
            raise StateTransitionError(msg)

        test_result = run_tests(self.root)
        if not test_result.passed:
            msg = f"Refactoring broke the test suite! Failed: {test_result.failed_tests}."
            raise StateTransitionError(msg)

        refactor_wit = RefactorWitness(tests_passed=test_result.passed_tests)
        cycle.phase = Phase.REFACTOR
        cycle.refactor_witness = refactor_wit
        cycle.transitions.append(Transition(from_phase=cycle.phase, to_phase=Phase.REFACTOR))

        try:
            ev_path, _ = write_phase_evidence(
                root=self.root,
                cycle_id=cycle.cycle_id,
                phase=Phase.REFACTOR,
                repository_ref=get_head_commit(self.root),
                payload=refactor_wit.model_dump(),
            )
            cycle.evidence_chain.append(str(ev_path))
        except Exception:
            pass

        self.store.save_active_cycle(cycle)
        return refactor_wit

    def complete(self) -> Cycle:
        cycle = self.store.load_active_cycle()
        if cycle is None:
            msg = "No active cycle to complete."
            raise StateTransitionError(msg)
        if cycle.phase not in (Phase.GREEN, Phase.REFACTOR):
            msg = f"Cannot complete cycle in phase '{cycle.phase}'. Must be GREEN or REFACTOR."
            raise StateTransitionError(msg)

        test_result = run_tests(self.root)
        if not test_result.passed:
            msg = "Cannot complete cycle: tests are currently failing."
            raise StateTransitionError(msg)

        cycle.phase = Phase.COMPLETED
        cycle.completed_at = datetime.now(UTC)
        cycle.transitions.append(Transition(from_phase=cycle.phase, to_phase=Phase.COMPLETED))
        self.store.archive_cycle(cycle)
        return cycle
