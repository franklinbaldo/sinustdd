from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from sinustdd.adapters import PytestAdapter
from sinustdd.workspace_guard import PosixPermissionGuard, get_workspace_guard

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics required")


def _workspace(root: Path) -> Path:
    production = root / "src" / "feature.py"
    verification = root / "tests" / "test_feature.py"
    production.parent.mkdir(parents=True)
    verification.parent.mkdir(parents=True)
    production.write_text("VALUE = 1\n", encoding="utf-8")
    verification.write_text("def test_value(): assert True\n", encoding="utf-8")
    return production


def test_guard_describes_idle_and_enforced_workspace_state(tmp_path: Path) -> None:
    production = _workspace(tmp_path)
    guard = PosixPermissionGuard(tmp_path, PytestAdapter())

    idle = guard.describe()
    assert idle["phase"] is None
    assert idle["guarded_paths"] == []
    assert idle["enforcing"] is False

    guard.enforce_red()
    enforced = guard.describe()

    assert enforced["backend"] == "posix-permissions"
    assert enforced["phase"] == "red"
    assert enforced["enforcing"] is True
    assert production.relative_to(tmp_path).as_posix() in enforced["guarded_paths"]


def test_factory_returns_posix_guard_on_posix_workspaces(tmp_path: Path) -> None:
    guard = get_workspace_guard(tmp_path, PytestAdapter())

    assert isinstance(guard, PosixPermissionGuard)
    assert guard.describe()["backend"] == "posix-permissions"


def test_cli_guard_status_and_explain_report_the_guarded_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from sinustdd.cli import guard_explain, guard_status

    production = _workspace(tmp_path)
    guard = PosixPermissionGuard(tmp_path, PytestAdapter())
    monkeypatch.setattr("sinustdd.cli._guard", lambda: guard)

    guard_status()
    assert "no phase" in capsys.readouterr().out.lower()

    guard.enforce_red()
    guard_status()
    assert "red" in capsys.readouterr().out.lower()

    guard_explain(production)
    assert "RED" in capsys.readouterr().out


def test_mcp_exposes_guard_status_and_explain_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sinustdd.mcp import mcp, sinustdd_guard_explain, sinustdd_guard_status

    production = _workspace(tmp_path)
    guard = PosixPermissionGuard(tmp_path, PytestAdapter())
    monkeypatch.setattr("sinustdd.mcp._guard", lambda: guard)
    guard.enforce_red()

    status = sinustdd_guard_status()
    assert status["phase"] == "red"

    explanation = sinustdd_guard_explain(production.relative_to(tmp_path).as_posix())
    assert "RED" in explanation["explanation"]

    async def _check() -> None:
        names = {tool.name for tool in await mcp.list_tools()}
        assert {"sinustdd_guard_status", "sinustdd_guard_explain"} <= names

    asyncio.run(_check())
