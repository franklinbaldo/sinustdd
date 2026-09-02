"""Persistence for the active sinustdd cycle."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sinustdd.models import Cycle

STATE_DIR = Path(".sinustdd")
SESSION_FILE = STATE_DIR / "session.json"


def load_cycle() -> Cycle:
    return Cycle.model_validate_json(SESSION_FILE.read_text(encoding="utf-8"))


def save_cycle(cycle: Cycle) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SESSION_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(cycle.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, SESSION_FILE)


def clear_cycle() -> None:
    SESSION_FILE.unlink(missing_ok=True)
