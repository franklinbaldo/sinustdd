"""Core models for Sinusoidal TDD Harmonic State Machine."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Phase(StrEnum):
    IDLE = "idle"
    BASELINE = "baseline"
    RED = "red"
    GREEN = "green"
    REFACTOR = "refactor"
    COMPLETED = "completed"

    @property
    def theta(self) -> float:
        """Harmonic phase angle in radians [0, 2pi]."""
        mapping = {
            Phase.IDLE: 0.0,
            Phase.BASELINE: 0.0,
            Phase.RED: 3.141592653589793,  # pi
            Phase.GREEN: 4.71238898038469,  # 1.5 pi
            Phase.REFACTOR: 6.283185307179586,  # 2 pi
            Phase.COMPLETED: 6.283185307179586,
        }
        return mapping[self]


class RedWitness(BaseModel):
    """Immutable proof that a test legitimately failed against baseline production."""

    test_files: list[str]
    failed_tests: list[str]
    failure_fingerprint: str
    baseline_commit: str
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GreenWitness(BaseModel):
    """Immutable proof that production changes resolved the red failure with frozen tests."""

    production_files_modified: list[str]
    tests_passed: list[str]
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Cycle(BaseModel):
    """Complete harmonic TDD cycle record."""

    cycle_id: str
    phase: Phase = Phase.IDLE
    baseline_commit: str
    red_witness: RedWitness | None = None
    green_witness: GreenWitness | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
