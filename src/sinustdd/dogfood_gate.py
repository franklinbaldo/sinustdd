"""Pull-request gate for SinusTDD dogfooding evidence."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from sinustdd.evidence import find_phase_evidence_path, verify_ledger
from sinustdd.models import Phase

EVIDENCE_PREFIX = ".sinustdd/evidence/"


@dataclass(frozen=True, slots=True)
class GateResult:
    passed: bool
    message: str
    checked_cycles: tuple[str, ...] = ()


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if proc.returncode != 0:
        msg = proc.stderr.strip() or f"git {' '.join(args)} failed"
        raise RuntimeError(msg)
    return proc.stdout.strip()


def _base_has_gate(root: Path, base_ref: str) -> bool:
    proc = subprocess.run(
        ["git", "cat-file", "-e", f"{base_ref}:src/sinustdd/dogfood_gate.py"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return proc.returncode == 0


def _changed_paths(root: Path, base_ref: str) -> list[str]:
    raw = _git(root, "diff", "--name-only", f"{base_ref}...HEAD")
    return [line.strip().replace("\\", "/") for line in raw.splitlines() if line.strip()]


def _requires_causal_cycle(paths: list[str]) -> bool:
    return any(path.startswith(("src/", "tests/")) for path in paths)


def _changed_cycle_ids(paths: list[str]) -> set[str]:
    cycle_ids: set[str] = set()
    for path in paths:
        if not path.startswith(EVIDENCE_PREFIX):
            continue
        remainder = path[len(EVIDENCE_PREFIX) :]
        cycle_id, sep, _ = remainder.partition("/")
        if sep and cycle_id:
            cycle_ids.add(cycle_id)
    return cycle_ids


def check_pr_ready(root: Path, base_ref: str = "origin/main") -> GateResult:
    """Require a complete causal witness for product-code changes in this PR.

    Historical incomplete cycles are deliberately ignored. The gate considers only
    evidence directories changed by the current PR. A complete PR witness must contain
    BASELINE, RED, and GREEN; REFACTOR and terminal reflection remain optional.

    The very first PR introducing this gate bootstraps successfully when the base branch
    does not yet contain this module. Once merged, all subsequent product-code PRs are
    subject to the rule automatically.
    """
    if not _base_has_gate(root, base_ref):
        return GateResult(True, "bootstrap: base branch does not enforce the dogfood gate yet")

    paths = _changed_paths(root, base_ref)
    if not _requires_causal_cycle(paths):
        return GateResult(True, "no product code/test changes require a causal cycle")

    cycle_ids = sorted(_changed_cycle_ids(paths))
    if not cycle_ids:
        return GateResult(
            False,
            "product code/test changes require a SinusTDD cycle changed in this PR",
        )

    complete: list[str] = []
    failures: list[str] = []
    for cycle_id in cycle_ids:
        missing = [
            phase.value
            for phase in (Phase.BASELINE, Phase.RED, Phase.GREEN)
            if find_phase_evidence_path(root, cycle_id, phase) is None
        ]
        if missing:
            failures.append(f"{cycle_id}: missing {', '.join(missing)}")
            continue
        if not verify_ledger(root, cycle_id):
            failures.append(f"{cycle_id}: ledger integrity verification failed")
            continue
        complete.append(cycle_id)

    if not complete:
        return GateResult(False, "; ".join(failures), tuple(cycle_ids))

    if failures:
        return GateResult(
            False,
            "all evidence cycles touched by a product PR must be valid: " + "; ".join(failures),
            tuple(cycle_ids),
        )

    return GateResult(
        True,
        f"causal completion gate satisfied by {', '.join(complete)}",
        tuple(cycle_ids),
    )
