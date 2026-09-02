"""Versioned OKF evidence ledger and strict sequential verification for sinustdd cycles."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from okf_parser import validate_path

from sinustdd.models import Phase

EVIDENCE_ROOT = Path(".sinustdd/evidence")
_PHASE_ORDER = [Phase.BASELINE, Phase.RED, Phase.GREEN, Phase.REFACTOR]


def _digest(document: dict[str, Any]) -> str:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _quote(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _timestamp_prefix(now: datetime | None = None) -> str:
    instant = now or datetime.now(UTC)
    return instant.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def get_phase_evidence_path(root: Path, cycle_id: str, phase: Phase) -> Path:
    """Return the legacy phase path kept for backwards compatibility."""
    return root / EVIDENCE_ROOT / cycle_id / f"{phase.value}.md"


def _phase_candidates(root: Path, cycle_id: str, phase: Phase) -> list[Path]:
    cycle_dir = root / EVIDENCE_ROOT / cycle_id
    if not cycle_dir.is_dir():
        return []
    legacy = cycle_dir / f"{phase.value}.md"
    candidates = list(cycle_dir.glob(f"*-{phase.value}.md"))
    if legacy.is_file():
        candidates.append(legacy)
    return sorted(set(candidates), key=lambda p: p.name)


def find_phase_evidence_path(root: Path, cycle_id: str, phase: Phase) -> Path | None:
    """Resolve one phase witness across timestamped and historical filenames.

    More than one witness for the same phase is ambiguous and therefore invalid.
    """
    candidates = _phase_candidates(root, cycle_id, phase)
    if len(candidates) == 1:
        return candidates[0]
    return None


def get_latest_evidence_hash(root: Path, cycle_id: str) -> str | None:
    """Find the SHA-256 of the most recent valid phase evidence in the cycle."""
    for ph in reversed(_PHASE_ORDER):
        p = find_phase_evidence_path(root, cycle_id, ph)
        if p is not None:
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
    """Write one immutable phase witness as timestamp-prefixed authored OKF Markdown."""
    repo_root = root or Path.cwd()
    evidence_dir = repo_root / EVIDENCE_ROOT
    cycle_dir = evidence_dir / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)

    if _phase_candidates(repo_root, cycle_id, phase):
        msg = f"Phase evidence already exists for {cycle_id}/{phase.value}"
        raise FileExistsError(msg)

    path = cycle_dir / f"{_timestamp_prefix()}-{phase.value}.md"
    previous_sha256 = get_latest_evidence_hash(repo_root, cycle_id)

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
    """Verify integrity, hash chaining, unique phases, and contiguous phase sequence."""
    previous_hash: str | None = None
    seen_phases: list[Phase] = []

    for ph in _PHASE_ORDER:
        candidates = _phase_candidates(root, cycle_id, ph)
        if len(candidates) > 1:
            return False
        if not candidates:
            continue

        p = candidates[0]
        seen_phases.append(ph)
        text = p.read_text(encoding="utf-8")
        m_sha = re.search(r'sha256:\s*["\']?([^"\'\n]+)["\']?', text)
        m_prev = re.search(r'previous_evidence_sha256:\s*["\']?([^"\'\n]+)["\']?', text)
        m_ref = re.search(r'repository_ref:\s*["\']?([^"\'\n]+)["\']?', text)
        m_json = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
        if not m_sha or not m_ref or not m_json:
            return False

        try:
            payload = json.loads(m_json.group(1))
        except (TypeError, ValueError, json.JSONDecodeError):
            return False

        cur_sha = m_sha.group(1).strip()
        cur_prev = m_prev.group(1).strip() if m_prev else None
        repo_ref = m_ref.group(1).strip()
        expected_digest = _digest(
            {
                "cycle_id": cycle_id,
                "phase": ph.value,
                "repository_ref": repo_ref,
                "payload": payload,
                "previous_evidence_sha256": cur_prev,
            }
        )
        if cur_sha != expected_digest or cur_prev != previous_hash:
            return False
        previous_hash = cur_sha

    if seen_phases and seen_phases != _PHASE_ORDER[: len(seen_phases)]:
        return False
    return True
