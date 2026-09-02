"""Automatic observation and passive phase inference for sinustdd."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sinustdd.diff import classify_diff, compute_test_files_hashes
from sinustdd.engine import SinusTDDEngine, StateTransitionError
from sinustdd.evidence import verify_ledger
from sinustdd.models import Phase
from sinustdd.runner import run_tests


@dataclass(frozen=True, slots=True)
class ViolationEvent:
    """A demonstrated protocol violation observed from repository evidence."""

    code: str
    cycle_id: str
    inferred_phase: Phase
    expected_invariant: str
    observed_evidence: str
    evidence_path: str | None = None
    suggested_recovery: str | None = None


ViolationCallback = Callable[[ViolationEvent], None]


class Observer:
    """Passive phase observer with a silence-on-success notification contract.

    Observes working directory changes, infers harmonic phase transitions,
    records OKF evidence on valid transitions, and emits ViolationEvent ONLY on
    unambiguous protocol violations.
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.engine = SinusTDDEngine(self.root)
        self._callbacks: list[ViolationCallback] = []

    def subscribe(self, callback: ViolationCallback) -> None:
        """Register a violation callback."""
        self._callbacks.append(callback)

    def notify_violation(self, event: ViolationEvent) -> None:
        """Deliver a demonstrated violation to all subscribers."""
        for callback in tuple(self._callbacks):
            callback(event)

    def observe_once(self) -> dict[str, Any]:
        """Perform one pass of passive observation over the repository.

        Returns:
            dict with observation status:
            - transition_recorded (bool)
            - violation_detected (bool)
            - inferred_phase (Phase)
            - silent (bool)
        """
        st = self.engine.status()
        cycle_id = st.get("cycle_id", "none")
        current_phase = st.get("phase", Phase.IDLE)

        # 1. Check ledger integrity if cycle is active
        if st["active"] and not verify_ledger(self.root, cycle_id):
            evt = ViolationEvent(
                code="LEDGER_TAMPERED",
                cycle_id=cycle_id,
                inferred_phase=current_phase,
                expected_invariant="OKF evidence chain sha256 intact",
                observed_evidence="Evidence file was modified or reordered",
                suggested_recovery="Restore authentic .sinustdd/evidence/ chain",
            )
            self.notify_violation(evt)
            return {"violation_detected": True, "code": evt.code, "silent": False}

        # 2. Case: IDLE / No Active Cycle
        if not st["active"]:
            diff = classify_diff(self.root)
            # If repo is clean or starting work, try to begin
            if not diff.has_production_changes and not diff.has_test_changes:
                test_res = run_tests(self.root)
                if test_res.passed:
                    try:
                        self.engine.begin()
                        return {
                            "transition_recorded": True,
                            "inferred_phase": Phase.BASELINE,
                            "silent": True,
                        }
                    except StateTransitionError:
                        pass
            return {"silent": True, "inferred_phase": Phase.IDLE}

        # 3. Case: BASELINE -> Candidate RED
        if current_phase in (Phase.BASELINE, Phase.RED):
            diff = classify_diff(self.root, st["baseline_commit"])
            # Hard violation: production touched before Red Witness
            if diff.has_production_changes and current_phase == Phase.BASELINE:
                mod_files = diff.production_files_modified + diff.production_files_added
                evt = ViolationEvent(
                    code="PROD_BEFORE_RED",
                    cycle_id=cycle_id,
                    inferred_phase=Phase.BASELINE,
                    expected_invariant="production_diff == empty during RED",
                    observed_evidence=f"Modified: {mod_files}",
                    suggested_recovery="Revert production changes and write a failing test first",
                )
                self.notify_violation(evt)
                return {"violation_detected": True, "code": evt.code, "silent": False}

            # Valid RED transition check
            if (
                diff.has_test_changes
                and not diff.has_production_changes
                and current_phase == Phase.BASELINE
            ):
                test_res = run_tests(self.root)
                if not test_res.passed and test_res.failed_tests:
                    try:
                        self.engine.mark_red()
                        return {
                            "transition_recorded": True,
                            "inferred_phase": Phase.RED,
                            "silent": True,
                        }
                    except StateTransitionError:
                        pass

        # 4. Case: RED -> Candidate GREEN
        if current_phase in (Phase.RED, Phase.GREEN):
            cycle = self.engine.store.load_active_cycle()
            if cycle and cycle.red_witness:
                # Check for test tampering
                cur_hashes = compute_test_files_hashes(self.root, cycle.red_witness.test_files)
                for t_file, orig_hash in cycle.red_witness.test_files_hashes.items():
                    if cur_hashes.get(t_file) != orig_hash:
                        evt = ViolationEvent(
                            code="TEST_ASSERTION_TAMPERED",
                            cycle_id=cycle_id,
                            inferred_phase=Phase.GREEN,
                            expected_invariant="test_files_hashes == frozen",
                            observed_evidence=f"Test file '{t_file}' was altered after RedWitness",
                            suggested_recovery="Restore test assertions captured during RED phase",
                        )
                        self.notify_violation(evt)
                        return {"violation_detected": True, "code": evt.code, "silent": False}

                diff = classify_diff(self.root, cycle.baseline_commit)
                if diff.has_production_changes and current_phase == Phase.RED:
                    test_res = run_tests(self.root)
                    if test_res.passed:
                        try:
                            self.engine.mark_green()
                            return {
                                "transition_recorded": True,
                                "inferred_phase": Phase.GREEN,
                                "silent": True,
                            }
                        except StateTransitionError:
                            pass

        return {"silent": True, "inferred_phase": current_phase}
