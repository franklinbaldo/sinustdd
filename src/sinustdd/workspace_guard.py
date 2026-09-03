"""Filesystem enforcement backends for causal workspace capabilities."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from sinustdd.adapters import VerificationAdapter

_STATE_PATH = Path(".sinustdd/workspace-guard-state.json")
_WRITE_MASK = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
_FALLBACK_EXCLUDED_ROOTS = {
    ".git",
    ".sinustdd",
    ".venv",
    ".lake",
    "build",
    "dist",
    "env",
    "node_modules",
    "target",
    "venv",
}


class WorkspaceGuard(ABC):
    """Materialize causal phase capabilities in a working tree."""

    @abstractmethod
    def enforce_red(self) -> list[Path]:
        """Restrict production artifacts while RED verification is being established."""

    @abstractmethod
    def enforce_green(self, verification_paths: list[str]) -> list[Path]:
        """Freeze witnessed RED verification artifacts until the cycle completes."""

    @abstractmethod
    def restore(self) -> list[Path]:
        """Restore original filesystem permissions idempotently."""

    @abstractmethod
    def explain(self, path: Path) -> str:
        """Explain why a path is currently guarded, if applicable."""

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Report which capabilities the guard is currently materializing."""

    def recover(
        self,
        expected_phase: str | None,
        verification_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Reconcile persisted guard state with the phase the cycle expects.

        Enforcement state is an operational cursor: a crash, an agent restart, or an
        external tool can desynchronize it from the causal cycle. Recovery is
        idempotent and always ends with the workspace materializing `expected_phase`.
        """
        state = self.describe()
        corrupt = bool(state.get("corrupt_state"))
        current = state.get("phase")

        drifted = bool(state.get("drifted"))
        if not corrupt and not drifted and state.get("enforcing") and current == expected_phase:
            return {
                "action": "consistent",
                "phase": current,
                "recovered_from_corrupt_state": False,
                "paths": list(state.get("guarded_paths", [])),
            }

        self.restore()
        if expected_phase is None:
            return {
                "action": "restored",
                "phase": None,
                "recovered_from_corrupt_state": corrupt,
                "paths": [],
            }
        if expected_phase == "red":
            guarded = self.enforce_red()
        elif expected_phase == "green":
            guarded = self.enforce_green(list(verification_paths or []))
        else:
            raise ValueError(f"unknown enforcement phase: {expected_phase}")
        return {
            "action": "reenforced",
            "phase": expected_phase,
            "recovered_from_corrupt_state": corrupt,
            "paths": [path.as_posix() for path in guarded],
        }


class PosixPermissionGuard(WorkspaceGuard):
    """Materialize RED/GREEN capabilities using POSIX write bits.

    Original modes are persisted under `.sinustdd/` before chmod so a fresh
    process can restore them after a crash or agent restart. The state file is
    an operational cursor, not causal evidence.
    """

    def __init__(self, root: Path, adapter: VerificationAdapter) -> None:
        if os.name != "posix":
            raise OSError("PosixPermissionGuard requires a POSIX filesystem")
        self.root = root.resolve()
        self.adapter = adapter
        self.state_path = self.root / _STATE_PATH

    def _read_state(self) -> tuple[str | None, dict[str, int], bool]:
        """Read persisted state, reporting unreadable state instead of raising."""
        if not self.state_path.is_file():
            return None, {}, False
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            phase = raw.get("phase")
            modes = {str(path): int(mode) for path, mode in raw.get("original_modes", {}).items()}
        except (OSError, UnicodeError, ValueError, AttributeError, TypeError):
            return None, {}, True
        return (str(phase) if phase is not None else None), modes, False

    def _load_state(self) -> tuple[str | None, dict[str, int]]:
        phase, modes, _corrupt = self._read_state()
        return phase, modes

    def _write_state(self, phase: str, modes: dict[str, int]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"phase": phase, "original_modes": dict(sorted(modes.items()))}
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        self.state_path.write_text(text, encoding="utf-8")

    def _git_project_paths(self) -> list[Path] | None:
        proc = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=self.root,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            return None
        entries = [entry for entry in proc.stdout.split(b"\0") if entry]
        return [self.root / os.fsdecode(entry) for entry in entries]

    def _fallback_paths(self) -> list[Path]:
        paths: list[Path] = []
        for path in self.root.rglob("*"):
            relative = path.relative_to(self.root)
            if relative.parts and relative.parts[0] in _FALLBACK_EXCLUDED_ROOTS:
                continue
            paths.append(path)
        return paths

    def _production_files(self) -> list[Path]:
        candidates = self._git_project_paths()
        if candidates is None:
            candidates = self._fallback_paths()

        production: list[Path] = []
        for path in candidates:
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(self.root).as_posix()
            if self.adapter.is_production_artifact(relative):
                production.append(path)
        return sorted(set(production))

    def _guard_paths(self, phase: str, paths: list[Path]) -> list[Path]:
        modes: dict[str, int] = {}
        current_modes: dict[Path, int] = {}
        for path in paths:
            relative = path.relative_to(self.root).as_posix()
            current_mode = stat.S_IMODE(path.stat().st_mode)
            current_modes[path] = current_mode
            modes[relative] = current_mode

        if modes:
            self._write_state(phase, modes)

        for path, current_mode in current_modes.items():
            path.chmod(current_mode & ~_WRITE_MASK)
        return sorted(current_modes)

    def enforce_red(self) -> list[Path]:
        self.restore()
        return self._guard_paths("red", self._production_files())

    def enforce_green(self, verification_paths: list[str]) -> list[Path]:
        self.restore()
        verification: list[Path] = []
        for relative in verification_paths:
            normalized = Path(relative)
            path = (self.root / normalized).resolve()
            try:
                path.relative_to(self.root)
            except ValueError as exc:
                raise RuntimeError(f"verification path escapes workspace: {relative}") from exc
            if not path.is_file() or path.is_symlink():
                continue
            project_relative = path.relative_to(self.root).as_posix()
            if not self.adapter.is_verification_artifact(project_relative):
                continue
            verification.append(path)
        return self._guard_paths("green", verification)

    def restore(self) -> list[Path]:
        _phase, modes = self._load_state()
        if not modes:
            self.state_path.unlink(missing_ok=True)
            return []

        restored: list[Path] = []
        for relative, mode in modes.items():
            path = (self.root / relative).resolve()
            try:
                path.relative_to(self.root)
            except ValueError as exc:
                raise RuntimeError(f"guard state escapes workspace: {relative}") from exc
            if not path.exists() or path.is_symlink():
                continue
            path.chmod(mode)
            restored.append(path)

        self.state_path.unlink(missing_ok=True)
        return restored

    def describe(self) -> dict[str, Any]:
        phase, modes, corrupt = self._read_state()
        return {
            "backend": "posix-permissions",
            "phase": phase,
            "enforcing": bool(modes),
            "guarded_paths": sorted(modes),
            "corrupt_state": corrupt,
            "drifted": self._has_drifted(modes),
        }

    def _has_drifted(self, modes: dict[str, int]) -> bool:
        """Report whether any recorded path lost the read-only capability on disk."""
        for relative in modes:
            path = self.root / relative
            if not path.is_file():
                return True
            if stat.S_IMODE(path.stat().st_mode) & _WRITE_MASK:
                return True
        return False

    def explain(self, path: Path) -> str:
        candidate = path if path.is_absolute() else self.root / path
        try:
            relative = candidate.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return "path is outside the guarded workspace"

        phase, modes = self._load_state()
        if relative not in modes:
            return f"{relative} is not currently guarded"
        if phase == "green":
            return (
                f"{relative} is read-only because Sinos is enforcing GREEN: "
                "the witnessed RED contract is frozen while production changes"
            )
        return (
            f"{relative} is read-only because Sinos is enforcing RED: "
            "production stays frozen until a valid RedWitness exists"
        )


def get_workspace_guard(root: Path, adapter: VerificationAdapter) -> WorkspaceGuard | None:
    """Select the enforcement backend available for this workspace.

    Returns None where no backend can materialize capabilities, so callers stay
    honest about enforcement instead of pretending a no-op guard enforces.
    """
    if os.name == "posix":
        return PosixPermissionGuard(root, adapter)
    return None
