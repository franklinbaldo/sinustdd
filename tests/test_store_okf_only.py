from __future__ import annotations

from pathlib import Path

from sinustdd.models import Cycle, Phase
from sinustdd.store import SessionStore


def test_archiving_a_completed_cycle_leaves_okf_as_the_only_durable_history(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    cycle = Cycle(cycle_id="cycle-okf-only", phase=Phase.COMPLETED, baseline_commit="baseline")

    store.save_active_cycle(cycle)
    assert store.session_file.is_file()

    store.archive_cycle(cycle)

    assert not store.session_file.exists()
    assert not (tmp_path / ".sinustdd" / "cycles").exists()
    assert list((tmp_path / ".sinustdd").glob("**/*.json")) == []
