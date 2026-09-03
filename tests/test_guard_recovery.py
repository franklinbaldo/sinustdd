from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from sinustdd.adapters import PytestAdapter, TestRun
from sinustdd.engine import SinusTDDEngine
from sinustdd.workspace_guard import PosixPermissionGuard

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")

_STATE = Path(".sinustdd/workspace-guard-state.json")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _workspace(root: Path) -> tuple[Path, Path]:
    production = root / "src" / "feature.py"
    verification = root / "tests" / "test_feature.py"
    production.parent.mkdir(parents=True)
    verification.parent.mkdir(parents=True)
    production.write_text("VALUE = 1\n", encoding="utf-8")
    verification.write_text("def test_value(): assert True\n", encoding="utf-8")
    return production, verification


def test_recover_reenforces_expected_phase_after_a_lost_process(tmp_path: Path) -> None:
    production, _verification = _workspace(tmp_path)
    guard = PosixPermissionGuard(tmp_path, PytestAdapter())
    guard.enforce_red()

    # An agent restart or a crashed toolchain left the tree writable again.
    production.chmod(0o644 | stat.S_IWUSR)

    report = PosixPermissionGuard(tmp_path, PytestAdapter()).recover(expected_phase="red")

    assert report["action"] == "reenforced"
    assert report["phase"] == "red"
    assert _mode(production) & 0o222 == 0


def test_recover_is_a_no_op_when_state_already_matches_the_cycle(tmp_path: Path) -> None:
    production, _verification = _workspace(tmp_path)
    guard = PosixPermissionGuard(tmp_path, PytestAdapter())
    guard.enforce_red()

    report = guard.recover(expected_phase="red")

    assert report["action"] == "consistent"
    assert _mode(production) & 0o222 == 0
    assert (tmp_path / _STATE).is_file()


def test_recover_restores_permissions_when_no_phase_is_expected(tmp_path: Path) -> None:
    production, _verification = _workspace(tmp_path)
    production.chmod(0o664)
    PosixPermissionGuard(tmp_path, PytestAdapter()).enforce_red()

    report = PosixPermissionGuard(tmp_path, PytestAdapter()).recover(expected_phase=None)

    assert report["action"] == "restored"
    assert _mode(production) == 0o664
    assert not (tmp_path / _STATE).exists()


def test_recover_survives_a_truncated_state_file(tmp_path: Path) -> None:
    _workspace(tmp_path)
    state_path = tmp_path / _STATE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text('{"phase": "red", "original_mo', encoding="utf-8")

    guard = PosixPermissionGuard(tmp_path, PytestAdapter())

    assert guard.describe()["phase"] is None
    report = guard.recover(expected_phase="red")

    assert report["recovered_from_corrupt_state"] is True
    assert report["action"] == "reenforced"


def test_engine_recovers_the_phase_capabilities_of_the_active_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    production, verification = _workspace(tmp_path)
    adapter = PytestAdapter()

    def clean_run(root: Path, selection: list[str] | None = None) -> TestRun:
        return TestRun(
            adapter_name="pytest",
            passed=True,
            returncode=0,
            output="PASSED baseline",
            tests_passed=["tests/test_feature.py::test_value"],
        )

    monkeypatch.setattr(adapter, "run_tests", clean_run)
    guard = PosixPermissionGuard(tmp_path, adapter)
    engine = SinusTDDEngine(tmp_path, adapter=adapter, workspace_guard=guard)
    engine.begin(label="recovery")

    # Simulate a crashed session: state lost, permissions drifted back.
    (tmp_path / _STATE).unlink()
    production.chmod(0o644 | stat.S_IWUSR)

    report = engine.recover_workspace()

    assert report["action"] == "reenforced"
    assert report["phase"] == "red"
    assert _mode(production) & 0o222 == 0
    assert json.loads((tmp_path / _STATE).read_text(encoding="utf-8"))["phase"] == "red"
    assert verification.exists()


def test_cli_and_mcp_expose_workspace_recovery(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sinustdd.cli import guard_recover
    from sinustdd.mcp import sinustdd_guard_recover

    production, _verification = _workspace(tmp_path)
    adapter = PytestAdapter()
    guard = PosixPermissionGuard(tmp_path, adapter)
    engine = SinusTDDEngine(tmp_path, adapter=adapter, workspace_guard=guard)
    guard.enforce_red()
    production.chmod(0o644 | stat.S_IWUSR)

    monkeypatch.setattr("sinustdd.cli._engine", lambda: engine)
    monkeypatch.setattr("sinustdd.mcp._engine", lambda: engine)

    guard_recover()
    assert "restored" in capsys.readouterr().out.lower()

    guard.enforce_red()
    report = sinustdd_guard_recover()
    assert report["action"] in {"consistent", "restored", "reenforced"}
