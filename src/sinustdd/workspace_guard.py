"""Filesystem enforcement backends for causal workspace capabilities."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

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

    def _load_state(self) -> tuple[str | None, dict[str, int]]:
        if not self.state_path.is_file():
            return None, {}
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        phase = raw.get("phase")
        modes = raw.get("original_modes", {})
        normalized = {str(path): int(mode) for path, mode in modes.items()}
        return (str(phase) if phase is not None else None), normalized

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

    def explain(self, path: Path) -> str:
        try:
            relative = path.resolve().relative_to(self.root).as_posix()
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
