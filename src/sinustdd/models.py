"""Core models for causal TDD cycles and their repository evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Phase(StrEnum):
    BASELINE = "baseline"
    RED = "red"
    GREEN = "green"
    REFACTOR = "refactor"
    COMPLETED = "completed"


class Transition(BaseModel):
    from_phase: Phase
    to_phase: Phase
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RedWitness(BaseModel):
    test_id: str
    failure_output: str
    failure_fingerprint: str
    baseline_ref: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GreenWitness(BaseModel):
    test_id: str
    passed: bool = True
    production_diff_stat: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Cycle(BaseModel):
    cycle_id: str
    phase: Phase = Phase.BASELINE
    baseline_ref: str
    baseline_tests_passed: bool
    red_witness: RedWitness | None = None
    green_witness: GreenWitness | None = None
    transitions: list[Transition] = Field(default_factory=list)


class PhaseEvidence(BaseModel):
    """Append-only evidence emitted whenever a cycle crosses a phase boundary."""

    schema_version: int = 1
    cycle_id: str
    phase: Phase
    repository_ref: str
    payload: dict[str, Any]
    previous_evidence_sha256: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sha256: str
