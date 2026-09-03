"""Ephemeral session cursor for active sinustdd cycles."""

from __future__ import annotations

import json
from pathlib import Path

from sinustdd.models import Cycle


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.sinus_dir = self.root / ".sinustdd"
        self.session_file = self.sinus_dir / "session.json"

    def _ensure_dirs(self) -> None:
        self.sinus_dir.mkdir(parents=True, exist_ok=True)

    def load_active_cycle(self) -> Cycle | None:
        if not self.session_file.is_file():
            return None
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
            return Cycle.model_validate(data)
        except Exception:
            return None

    def save_active_cycle(self, cycle: Cycle) -> None:
        self._ensure_dirs()
        self.session_file.write_text(
            cycle.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def archive_cycle(self, cycle: Cycle) -> None:
        """Finish the operational session without creating a second durable ledger.

        Kept as a compatibility name for callers that complete a cycle. The completed
        cycle is already represented by its versioned OKF evidence; `session.json` is
        only an active-cycle cursor, so completion removes it.
        """
        del cycle
        self.session_file.unlink(missing_ok=True)


def load_cycle() -> Cycle | None:
    return SessionStore().load_active_cycle()


def save_cycle(cycle: Cycle) -> None:
    SessionStore().save_active_cycle(cycle)


def clear_cycle() -> None:
    store = SessionStore()
    if store.session_file.exists():
        store.session_file.unlink()
