"""Versioned OKF evidence ledger for sinustdd cycles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from okf_parser import validate_path

from sinustdd.models import Phase

EVIDENCE_ROOT = Path(".sinustdd/evidence")


def _digest(document: dict[str, Any]) -> str:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _quote(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def write_phase_evidence(
    *,
    cycle_id: str,
    phase: Phase,
    repository_ref: str,
    payload: dict[str, Any],
    previous_evidence_sha256: str | None = None,
) -> Path:
    """Write one immutable phase witness as an authored OKF Markdown concept."""
    cycle_dir = EVIDENCE_ROOT / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)
    path = cycle_dir / f"{phase.value}.md"
    if path.exists():
        raise FileExistsError(f"phase evidence already exists: {path}")

    digest_input = {
        "cycle_id": cycle_id,
        "phase": phase.value,
        "repository_ref": repository_ref,
        "payload": payload,
        "previous_evidence_sha256": previous_evidence_sha256,
    }
    sha256 = _digest(digest_input)

    frontmatter = [
        "---",
        "type: SinusTddEvidence",
        f"title: {_quote(f'{cycle_id} {phase.value} witness')}",
        f"description: {_quote(f'Causal TDD evidence for {phase.value} phase')}",
        f"cycle_id: {_quote(cycle_id)}",
        f"phase: {_quote(phase.value)}",
        f"repository_ref: {_quote(repository_ref)}",
        f"sha256: {_quote(sha256)}",
    ]
    if previous_evidence_sha256 is not None:
        frontmatter.append(f"previous_evidence_sha256: {_quote(previous_evidence_sha256)}")
    frontmatter.extend(["---", ""])

    body = [
        f"# {phase.value.title()} witness",
        "",
        "This document is repository evidence emitted by `sinustdd`.",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        "```",
        "",
    ]
    path.write_text("\n".join(frontmatter + body), encoding="utf-8")

    report = validate_path(EVIDENCE_ROOT)
    if not report.is_conformant:
        path.unlink(missing_ok=True)
        raise ValueError("generated sinustdd evidence is not OKF-conformant")

    return path
