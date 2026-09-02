from __future__ import annotations

from pathlib import Path

from okf_parser.parser import parse_document

from sinustdd.evidence import verify_ledger, write_phase_evidence
from sinustdd.models import Phase


def test_v2_evidence_is_frontmatter_native_and_uses_okf_digest_chain(tmp_path: Path) -> None:
    baseline, baseline_digest = write_phase_evidence(
        root=tmp_path,
        cycle_id="cycle-v2",
        phase=Phase.BASELINE,
        repository_ref="commit-1",
        payload={"tests_passed": ["tests/test_old.py::test_ok"], "suite_fingerprint": "abc"},
    )
    baseline_doc = parse_document(baseline)

    assert baseline_digest == baseline_doc.parsed_digest
    assert baseline_doc.frontmatter["schema_version"] == "2"
    assert "sha256" not in baseline_doc.frontmatter
    assert "payload" not in baseline_doc.frontmatter
    assert baseline_doc.frontmatter["tests_passed"] == ["tests/test_old.py::test_ok"]
    assert "```json" not in baseline_doc.body

    red, red_digest = write_phase_evidence(
        root=tmp_path,
        cycle_id="cycle-v2",
        phase=Phase.RED,
        repository_ref="commit-2",
        payload={"failed_tests": ["tests/test_new.py::test_new"], "failure_fingerprint": "def"},
    )
    red_doc = parse_document(red)

    assert red_digest == red_doc.parsed_digest
    assert red_doc.frontmatter["previous_evidence_digest"] == baseline_doc.parsed_digest
    assert verify_ledger(tmp_path, "cycle-v2")


def test_first_v2_write_bootstraps_okf_spec_and_declared_schema(tmp_path: Path) -> None:
    write_phase_evidence(
        root=tmp_path,
        cycle_id="cycle-contract",
        phase=Phase.BASELINE,
        repository_ref="commit-1",
        payload={"tests_passed": ["test_old"]},
    )

    bundle_root = tmp_path / ".sinustdd" / "evidence"
    spec = bundle_root / "specs" / "sinustddevidence.md"
    declared = bundle_root / "specs" / "sinustddevidence.schema.sql"
    relational = bundle_root / "okf.schema.sql"

    assert spec.is_file()
    assert declared.is_file()
    assert relational.is_file()
    assert 'CREATE TABLE "SinusTddEvidence"' in declared.read_text(encoding="utf-8")
    assert "PRIMARY KEY (cycle_id, phase)" in relational.read_text(encoding="utf-8")


def test_v2_ledger_detects_gap_and_tampering_through_okf_digest_chain(tmp_path: Path) -> None:
    baseline, _ = write_phase_evidence(
        root=tmp_path,
        cycle_id="cycle-gap",
        phase=Phase.BASELINE,
        repository_ref="commit-1",
        payload={"tests_passed": ["test_old"]},
    )
    write_phase_evidence(
        root=tmp_path,
        cycle_id="cycle-gap",
        phase=Phase.GREEN,
        repository_ref="commit-3",
        payload={"tests_passed": ["test_old", "test_new"]},
    )

    assert not verify_ledger(tmp_path, "cycle-gap")

    baseline.write_text(
        baseline.read_text(encoding="utf-8").replace("commit-1", "commit-hacked"),
        encoding="utf-8",
    )
    assert not verify_ledger(tmp_path, "cycle-gap")
