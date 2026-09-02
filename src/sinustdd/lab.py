"""Causal Reenactment Laboratory: isolated verification worktree and Git checkpoints."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sinustdd.adapters import TestAdapter, TestRun, get_adapter


class GuardMode(StrEnum):
    OBSERVE = "observe"  # Isolated worktree replay, read-only
    CHECKPOINT = "checkpoint"  # Creates internal Git refs (refs/sinustdd/...) + OKF
    ENFORCE = "enforce"  # Intercepts agent worktree and prevents mutations


@dataclass(frozen=True, slots=True)
class ReenactmentResult:
    valid: bool
    red_verified: bool
    green_verified: bool
    baseline_intact: bool
    details: str
    red_failure_fingerprint: str = ""


class CausalLab:
    """Isolated Git Worktree Lab for non-invasive causal reproduction."""

    def __init__(self, root: Path, mode: GuardMode = GuardMode.OBSERVE) -> None:
        self.root = root
        self.mode = mode
        self.lab_dir = root / ".sinustdd" / "lab"

    def _run_git(self, *args: str, cwd: Path | None = None) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def setup_worktree(self, base_commit: str) -> Path:
        """Create or reset an isolated verification worktree at base_commit."""
        if self.lab_dir.exists():
            self._run_git("worktree", "remove", "--force", str(self.lab_dir))
            shutil.rmtree(self.lab_dir, ignore_errors=True)

        self.lab_dir.parent.mkdir(parents=True, exist_ok=True)
        self._run_git("worktree", "add", "--detach", str(self.lab_dir), base_commit)
        return self.lab_dir

    def teardown(self) -> None:
        """Clean up the isolated lab worktree."""
        if self.lab_dir.exists():
            self._run_git("worktree", "remove", "--force", str(self.lab_dir))
            shutil.rmtree(self.lab_dir, ignore_errors=True)

    def create_checkpoint_ref(self, cycle_id: str, phase_name: str, commit: str) -> str:
        """Record an internal Git ref for causal custody: refs/sinustdd/cycles/<id>/<phase>."""
        ref = f"refs/sinustdd/cycles/{cycle_id}/{phase_name}"
        self._run_git("update-ref", ref, commit)
        return ref

    def reenact_cycle(
        self,
        *,
        baseline_commit: str,
        test_files: list[str],
        production_files: list[str],
        adapter: TestAdapter | None = None,
    ) -> ReenactmentResult:
        """Reenact the entire causal sequence in the isolated worktree without touching agent files.

        Sequence:
        1. Checkout pristine baseline commit.
        2. Verify baseline is 100% green.
        3. Inject ONLY the test files -> Verify failure against baseline (RED).
        4. Inject production files -> Verify test files PASS + baseline green (GREEN).
        """
        lab_path = self.setup_worktree(baseline_commit)
        test_runner = adapter or get_adapter(lab_path)

        try:
            # 1. Step 1: Verify baseline is clean
            baseline_run: TestRun = test_runner.run_tests(lab_path)
            if not baseline_run.passed:
                return ReenactmentResult(
                    valid=False,
                    red_verified=False,
                    green_verified=False,
                    baseline_intact=False,
                    details=f"Baseline reenactment failed! Broken: {baseline_run.tests_failed}",
                )

            # 2. Step 2: Inject ONLY the new test files
            for rel_file in test_files:
                src = self.root / rel_file
                dst = lab_path / rel_file
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)

            red_run: TestRun = test_runner.run_tests(lab_path)
            if red_run.passed or not red_run.tests_failed:
                return ReenactmentResult(
                    valid=False,
                    red_verified=False,
                    green_verified=False,
                    baseline_intact=True,
                    details="Reenactment detected tautological test: passed against baseline code!",
                )

            # 3. Step 3: Inject production files
            for rel_file in production_files:
                src = self.root / rel_file
                dst = lab_path / rel_file
                if src.is_file():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)

            green_run: TestRun = test_runner.run_tests(lab_path)
            if not green_run.passed:
                failed_msg = f"Green failed: still failing ({green_run.tests_failed})"
                return ReenactmentResult(
                    valid=False,
                    red_verified=True,
                    green_verified=False,
                    baseline_intact=True,
                    details=failed_msg,
                    red_failure_fingerprint=red_run.failure_fingerprint,
                )

            return ReenactmentResult(
                valid=True,
                red_verified=True,
                green_verified=True,
                baseline_intact=True,
                details="Causal sequence successfully reenacted in isolated worktree!",
                red_failure_fingerprint=red_run.failure_fingerprint,
            )

        finally:
            self.teardown()
