"""Core models for causal TDD cycles, witnesses, specification provenance, and violations."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SpecificationSource(StrEnum):
    """Provenance origin of the intention driving a TDD cycle."""

    ISSUE = "issue"
    RFC = "rfc"
    GHERKIN = "gherkin"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    BUG_REPORT = "bug_report"
    EXISTING_TEST = "existing_test"
    FREEFORM = "freeform"
    OTHER = "other"


class IntentRecord(BaseModel):
    """Freeform, lightweight intent registration before starting a TDD cycle."""

    source_reference: str = ""  # e.g., "RFC-0042", "Issue #123", "prompt"
    source_excerpt: str = ""  # Optional verbatim excerpt from source
    interpretation: str  # What the agent/human understood needs to happen
    intended_change: str = ""  # What code/architecture will be modified
    intended_proof: str = ""  # What test or proof will falsify/verify this


class OutcomeReflection(BaseModel):
    """Self-reflection recorded upon cycle completion (Socratic 'Know Thyself')."""

    diverged_from_intent: bool = False
    reflection_notes: str = ""
    discovered_insights: str = ""
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


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


class Transition(BaseModel):
    from_phase: Phase
    to_phase: Phase
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BaselineWitness(BaseModel):
    """Immutable proof that the baseline suite was completely green before changes."""

    baseline_commit: str
    tests_passed: list[str] = Field(default_factory=list)
    suite_fingerprint: str
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RedWitness(BaseModel):
    """Immutable proof that newly introduced/modified tests legitimately failed."""

    test_files: list[str] = Field(default_factory=list)
    test_files_hashes: dict[str, str] = Field(default_factory=dict)
    failed_tests: list[str] = Field(default_factory=list)
    failure_fingerprint: str
    baseline_commit: str
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GreenWitness(BaseModel):
    """Immutable proof that production changes resolved the red failure with frozen tests."""

    production_files_modified: list[str] = Field(default_factory=list)
    test_files_hashes_verified: dict[str, str] = Field(default_factory=dict)
    tests_passed: list[str] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RefactorWitness(BaseModel):
    """Immutable proof that structural cleanup preserved 100% test contract."""

    tests_passed: list[str] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Cycle(BaseModel):
    """Complete harmonic TDD cycle record."""

    cycle_id: str
    phase: Phase = Phase.IDLE
    baseline_commit: str
    specification_source: SpecificationSource = SpecificationSource.FREEFORM
    specification_reference: str = ""
    intent_record: IntentRecord | None = None
    outcome_reflection: OutcomeReflection | None = None
    test_spec_id: str | None = None
    baseline_witness: BaselineWitness | None = None
    red_witness: RedWitness | None = None
    green_witness: GreenWitness | None = None
    refactor_witness: RefactorWitness | None = None
    transitions: list[Transition] = Field(default_factory=list)
    evidence_chain: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PhaseEvidence(BaseModel):
    """Append-only OKF evidence emitted whenever a cycle crosses a phase boundary."""

    schema_version: int = 1
    cycle_id: str
    phase: Phase
    repository_ref: str
    payload: dict[str, Any]
    previous_evidence_sha256: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sha256: str
