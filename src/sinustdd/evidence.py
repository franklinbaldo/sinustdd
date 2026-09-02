"""Versioned OKF evidence ledger and verification for sinustdd cycles."""

from __future__ import annotations

import hashlib
import json
import re
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


def get_phase_evidence_path(root: Path, cycle_id: str, phase: Phase) -> Path:
    return root / ".sinustdd" / "evidence" / cycle_id / f"{phase.value}.md"


def get_latest_evidence_hash(root: Path, cycle_id: str) -> str | None:
    """Find the SHA-256 of the most recent phase evidence in the cycle."""
    order = [Phase.BASELINE, Phase.RED, Phase.GREEN, Phase.REFACTOR]
    for ph in reversed(order):
        p = get_phase_evidence_path(root, cycle_id, ph)
        if p.is_file():
            text = p.read_text(encoding="utf-8")
            m = re.search(r'sha256:\s*["\']?([^"\'\n]+)["\']?', text)
            if m:
                return m.group(1).strip()
    return None


def write_phase_evidence(
    *,
    root: Path | None = None,
    cycle_id: str,
    phase: Phase,
    repository_ref: str,
    payload: dict[str, Any],
) -> tuple[Path, str]:
    """Write one immutable phase witness as an authored OKF Markdown concept."""
    evidence_dir = (root or Path.cwd()) / ".sinustdd" / "evidence"
    cycle_dir = evidence_dir / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)
    path = cycle_dir / f"{phase.value}.md"
    if path.exists():
        msg = f"Phase evidence already exists: {path}"
        raise FileExistsError(msg)

    # Derive previous evidence hash automatically from chain
    previous_sha256 = get_latest_evidence_hash(root or Path.cwd(), cycle_id)

    digest_input = {
        "cycle_id": cycle_id,
        "phase": phase.value,
        "repository_ref": repository_ref,
        "payload": payload,
        "previous_evidence_sha256": previous_sha256,
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
    if previous_sha256 is not None:
        frontmatter.append(f"previous_evidence_sha256: {_quote(previous_sha256)}")
    frontmatter.extend(["---", ""])

    body = [
        f"# {phase.value.title()} witness",
        "",
        "This document is repository evidence emitted by sinustdd.",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        "```",
        "",
    ]
    path.write_text("\n".join(frontmatter + body), encoding="utf-8")

    report = validate_path(evidence_dir)
    if not report.is_conformant:
        path.unlink(missing_ok=True)
        msg = "Generated sinustdd evidence is not OKF-conformant"
        raise ValueError(msg)

    return path, sha256


def verify_ledger(root: Path, cycle_id: str) -> bool:
    """Verify integrity and hash chaining of all recorded phase evidence in a cycle."""
    order = [Phase.BASELINE, Phase.RED, Phase.GREEN, Phase.REFACTOR]
    previous_hash: str | None = None

    for ph in order:
        p = get_phase_evidence_path(root, cycle_id, ph)
        if not p.is_file():
            continue

        text = p.read_text(encoding="utf-8")
        m_sha = re.search(r'sha256:\s*["\']?([^"\'\n]+)["\']?', text)
        m_prev = re.search(r'previous_evidence_sha256:\s*["\']?([^"\'\n]+)["\']?', text)
        m_ref = re.search(r'repository_ref:\s*["\']?([^"\'\n]+)["\']?', text)

        # Extract payload JSON block
        m_json = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
        if not m_sha or not m_ref or not m_json:
            return False

        try:
            payload = json.loads(m_json.group(1))
        except Exception:
            return False

        cur_sha = m_sha.group(1).strip()
        cur_prev = m_prev.group(1).strip() if m_prev else None
        repo_ref = m_ref.group(1).strip()

        # Re-compute digest from payload and metadata
        expected_digest = _digest(
            {
                "cycle_id": cycle_id,
                "phase": ph.value,
                "repository_ref": repo_ref,
                "payload": payload,
                "previous_evidence_sha256": cur_prev,
            }
        )

        if cur_sha != expected_digest:
            return False

        if cur_prev != previous_hash:
            return False

        previous_hash = cur_sha

    return True
