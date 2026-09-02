from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from sinustdd.adapters import PytestAdapter
from sinustdd.workspace_guard import PosixPermissionGuard


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_posix_guard_makes_production_read_only_and_leaves_tests_writable(tmp_path: Path) -> None:
    production = tmp_path / "src" / "feature.py"
    verification = tmp_path / "tests" / "test_feature.py"
    production.parent.mkdir(parents=True)
    verification.parent.mkdir(parents=True)
    production.write_text("VALUE = 1\n", encoding="utf-8")
    verification.write_text("def test_value(): assert True\n", encoding="utf-8")
    production.chmod(0o664)
    verification.chmod(0o664)

    guard = PosixPermissionGuard(tmp_path, PytestAdapter())
    guarded = guard.enforce_red()

    assert production in guarded
    assert verification not in guarded
    assert _mode(production) & 0o222 == 0
    assert _mode(verification) & 0o200
    assert "RED" in guard.explain(production)


def test_posix_guard_restores_original_permissions_from_persisted_state(tmp_path: Path) -> None:
    production = tmp_path / "src" / "feature.py"
    production.parent.mkdir(parents=True)
    production.write_text("VALUE = 1\n", encoding="utf-8")
    production.chmod(0o764)

    PosixPermissionGuard(tmp_path, PytestAdapter()).enforce_red()
    assert _mode(production) & 0o222 == 0

    restored = PosixPermissionGuard(tmp_path, PytestAdapter()).restore()

    assert production in restored
    assert _mode(production) == 0o764
    assert not (tmp_path / ".sinustdd" / "workspace-guard-state.json").exists()


def test_restore_is_idempotent_when_no_guard_state_exists(tmp_path: Path) -> None:
    guard = PosixPermissionGuard(tmp_path, PytestAdapter())

    assert guard.restore() == []
