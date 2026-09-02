"""Automatic observation primitives for passive sinustdd integrations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sinustdd.models import Phase


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

    The first implementation deliberately exposes the notification boundary before
    repository polling/inference is wired in. Valid transitions must not generate
    callbacks; only demonstrated violations do.
    """

    def __init__(self) -> None:
        self._callbacks: list[ViolationCallback] = []

    def subscribe(self, callback: ViolationCallback) -> None:
        """Register a violation callback."""
        self._callbacks.append(callback)

    def notify_violation(self, event: ViolationEvent) -> None:
        """Deliver a demonstrated violation to all subscribers."""
        for callback in tuple(self._callbacks):
            callback(event)
