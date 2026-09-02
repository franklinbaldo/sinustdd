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
    def restore(self) -> list[Path]:
        """Restore original filesystem permissions idempotently."""

    @abstractmethod
    def explain(self, path: Path) -> str:
        """Explain why a path is currently guarded, if applicable."""


class PosixPermissionGuard(WorkspaceGuard):
    """Remove write bits from project production artifacts during RED.

    Original modes are persisted under `.sinustdd/` before any chmod is applied so a
    fresh process can restore them after a crash or agent restart. The state file is an
    operational cursor, not causal evidence.
    """

    def __init__(self, root: Path, adapter: VerificationAdapter) -> None:
        if os.name != "posix":
            raise OSError("PosixPermissionGuard requires a POSIX filesystem")
        self.root = root.resolve()
        self.adapter = adapter
        self.state_path = self.root / _STATE_PATH

    def _load_state(self) -> dict[str, int]:
        if not self.state_path.is_file():
            return {}
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        modes = raw.get("original_modes", {})
        return {str(path): int(mode) for path, mode in modes.items()}

    def _write_state(self, modes: dict[str, int]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"phase": "red", "original_modes": dict(sorted(modes.items()))}
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

    def enforce_red(self) -> list[Path]:
        production = self._production_files()
        modes = self._load_state()
        current_modes: dict[Path, int] = {}

        for path in production:
            relative = path.relative_to(self.root).as_posix()
            current_mode = stat.S_IMODE(path.stat().st_mode)
            current_modes[path] = current_mode
            modes.setdefault(relative, current_mode)

        if modes:
            self._write_state(modes)

        for path, current_mode in current_modes.items():
            path.chmod(current_mode & ~_WRITE_MASK)

        return production

    def restore(self) -> list[Path]:
        modes = self._load_state()
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

        if relative in self._load_state():
            return (
                f"{relative} is read-only because Sinos is enforcing RED: "
                "production stays frozen until a valid RedWitness exists"
            )
        return f"{relative} is not currently guarded"
