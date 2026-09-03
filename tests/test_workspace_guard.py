from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from sinustdd.adapters import PytestAdapter
from sinustdd.workspace_guard import PosixPermissionGuard


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


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


def test_guard_does_not_touch_gitignored_environment_files(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    production = tmp_path / "src" / "feature.py"
    environment = tmp_path / ".venv" / "lib" / "site.py"
    production.parent.mkdir(parents=True)
    environment.parent.mkdir(parents=True)
    production.write_text("VALUE = 1\n", encoding="utf-8")
    environment.write_text("DEPENDENCY = 1\n", encoding="utf-8")
    production.chmod(0o664)
    environment.chmod(0o664)
    _git(tmp_path, "add", ".gitignore", "src/feature.py")

    guarded = PosixPermissionGuard(tmp_path, PytestAdapter()).enforce_red()

    assert production in guarded
    assert environment not in guarded
    assert _mode(environment) == 0o664


def test_guard_freezes_witnessed_red_contract_during_green(tmp_path: Path) -> None:
    production = tmp_path / "src" / "feature.py"
    verification = tmp_path / "tests" / "test_feature.py"
    production.parent.mkdir(parents=True)
    verification.parent.mkdir(parents=True)
    production.write_text("VALUE = 1\n", encoding="utf-8")
    verification.write_text("def test_value(): assert False\n", encoding="utf-8")
    production.chmod(0o664)
    verification.chmod(0o664)

    guard = PosixPermissionGuard(tmp_path, PytestAdapter())
    guarded = guard.enforce_green(["tests/test_feature.py"])

    assert verification in guarded
    assert production not in guarded
    assert _mode(verification) & 0o222 == 0
    assert _mode(production) & 0o200
    assert "GREEN" in guard.explain(verification)

    restored = guard.restore()

    assert verification in restored
    assert _mode(verification) == 0o664


def test_restore_is_idempotent_when_no_guard_state_exists(tmp_path: Path) -> None:
    guard = PosixPermissionGuard(tmp_path, PytestAdapter())

    assert guard.restore() == []
