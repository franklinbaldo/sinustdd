"""Pull-request gate for SinusTDD dogfooding evidence."""

from __future__ import annotations

import argparse
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


def _repository_ref(evidence_path: Path) -> str | None:
    """Read repository_ref from an authored evidence frontmatter block."""
    for line in evidence_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("repository_ref:"):
            continue
        value = line.split(":", 1)[1].strip()
        return value.strip("\"'") or None
    return None


def _is_ancestor(root: Path, ancestor: str, descendant: str = "HEAD") -> bool:
    """Return whether a Git ref belongs to descendant ancestry; fail closed otherwise."""
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return proc.returncode == 0


def check_pr_ready(root: Path, base_ref: str = "origin/main") -> GateResult:
    """Require a complete causal witness that belongs to this PR's Git history.

    This is intentionally not semantic coverage. SinusTDD does not decide whether every
    changed file correctly implements an RFC or issue. It verifies the declared process:
    a product PR carries a new/touched causal cycle, its ledger is a contiguous
    BASELINE -> RED -> GREEN chain, and the declared baseline belongs to the ancestry of
    the PR HEAD. Interpretation remains the responsibility of coding/review agents.

    Historical incomplete cycles are ignored. REFACTOR and terminal reflection remain
    optional. The first PR that introduced this gate was allowed to bootstrap because its
    base branch did not yet contain this module.
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
        phase_paths = {
            phase: find_phase_evidence_path(root, cycle_id, phase)
            for phase in (Phase.BASELINE, Phase.RED, Phase.GREEN)
        }
        missing = [phase.value for phase, path in phase_paths.items() if path is None]
        if missing:
            failures.append(f"{cycle_id}: missing {', '.join(missing)}")
            continue
        if not verify_ledger(root, cycle_id):
            failures.append(f"{cycle_id}: ledger integrity verification failed")
            continue

        baseline_path = phase_paths[Phase.BASELINE]
        assert baseline_path is not None
        baseline_ref = _repository_ref(baseline_path)
        if baseline_ref is None or not _is_ancestor(root, baseline_ref):
            failures.append(
                f"{cycle_id}: baseline ref {baseline_ref or '<missing>'} "
                "is not an ancestor of PR HEAD"
            )
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether a PR is causally ready to merge")
    parser.add_argument("--base-ref", default="origin/main")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    result = check_pr_ready(args.root.resolve(), args.base_ref)
    marker = "✓" if result.passed else "✗"
    print(f"{marker} {result.message}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
