"""Harmonic state machine engine orchestrating causal TDD phase transitions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sinustdd.diff import classify_diff, get_head_commit
from sinustdd.models import Cycle, GreenWitness, Phase, RedWitness
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
            "red_witness": cycle.red_witness.model_dump() if cycle.red_witness else None,
            "green_witness": cycle.green_witness.model_dump() if cycle.green_witness else None,
        }

    def begin(self) -> Cycle:
        active = self.store.load_active_cycle()
        if active is not None and active.phase != Phase.COMPLETED:
            msg = f"Cycle {active.cycle_id} is already in progress (phase: {active.phase})."
            raise StateTransitionError(msg)

        head = get_head_commit(self.root)
        cycle_id = f"cycle-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        cycle = Cycle(
            cycle_id=cycle_id,
            phase=Phase.BASELINE,
            baseline_commit=head,
        )
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

        test_result = run_tests(self.root)
        if test_result.passed or not test_result.failed_tests:
            msg = (
                "Tautological test detected! The new test PASSED against baseline production code. "
                "A valid RED phase requires at least one failing test demonstrating "
                "the missing capability."
            )
            raise StateTransitionError(msg)

        witness = RedWitness(
            test_files=diff.test_files_added + diff.test_files_modified,
            failed_tests=test_result.failed_tests,
            failure_fingerprint=test_result.failure_fingerprint,
            baseline_commit=cycle.baseline_commit,
        )

        cycle.phase = Phase.RED
        cycle.red_witness = witness
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

        diff = classify_diff(self.root, cycle.baseline_commit)
        if not diff.has_production_changes:
            msg = (
                "Invariant violation in GREEN phase: no production code changes detected! "
                "You must implement the feature in src/ to resolve the red witness."
            )
            raise StateTransitionError(msg)

        test_result = run_tests(self.root)
        if not test_result.passed:
            msg = (
                f"Tests are still failing! Failed: {test_result.failed_tests}. "
                "GREEN phase requires all tests to pass."
            )
            raise StateTransitionError(msg)

        witness = GreenWitness(
            production_files_modified=diff.production_files_added + diff.production_files_modified,
            tests_passed=test_result.passed_tests,
        )

        cycle.phase = Phase.GREEN
        cycle.green_witness = witness
        self.store.save_active_cycle(cycle)
        return witness

    def mark_refactor(self) -> Cycle:
        cycle = self.store.load_active_cycle()
        if cycle is None or cycle.green_witness is None:
            msg = "Cannot transition to REFACTOR before achieving GREEN phase."
            raise StateTransitionError(msg)

        test_result = run_tests(self.root)
        if not test_result.passed:
            msg = f"Refactoring broke the test suite! Failed: {test_result.failed_tests}."
            raise StateTransitionError(msg)

        cycle.phase = Phase.REFACTOR
        self.store.save_active_cycle(cycle)
        return cycle

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
        self.store.archive_cycle(cycle)
        return cycle
