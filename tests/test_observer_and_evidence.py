from __future__ import annotations

from pathlib import Path

import pytest

from sinustdd.evidence import write_phase_evidence
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


def test_write_phase_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sinustdd.evidence.EVIDENCE_ROOT", tmp_path / "evidence")

    path = write_phase_evidence(
        cycle_id="test-cycle",
        phase=Phase.RED,
        repository_ref="HEAD",
        payload={"failed_tests": ["tests/test_x.py::test_1"]},
    )
    assert path.is_file()
    assert "SinusTddEvidence" in path.read_text(encoding="utf-8")

    # Cannot overwrite existing evidence in same phase
    with pytest.raises(FileExistsError):
        write_phase_evidence(
            cycle_id="test-cycle",
            phase=Phase.RED,
            repository_ref="HEAD",
            payload={"failed_tests": ["tests/test_x.py::test_1"]},
        )
