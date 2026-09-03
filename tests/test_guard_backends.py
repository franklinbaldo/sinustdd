from __future__ import annotations

from pathlib import Path

import pytest

from sinustdd.adapters import PytestAdapter
from sinustdd.workspace_guard import AdvisoryGuard, PosixPermissionGuard, get_workspace_guard


def _workspace(root: Path) -> tuple[Path, Path]:
    production = root / "src" / "feature.py"
    verification = root / "tests" / "test_feature.py"
    production.parent.mkdir(parents=True)
    verification.parent.mkdir(parents=True)
    production.write_text("VALUE = 1\n", encoding="utf-8")
    verification.write_text("def test_value(): assert True\n", encoding="utf-8")
    return production, verification


def test_advisory_guard_declares_capabilities_without_touching_permissions(
    tmp_path: Path,
) -> None:
    production, verification = _workspace(tmp_path)
    original = production.stat().st_mode

    guard = AdvisoryGuard(tmp_path, PytestAdapter())
    guarded = guard.enforce_red()

    assert production in guarded
    assert verification not in guarded
    assert production.stat().st_mode == original

    state = guard.describe()
    assert state["backend"] == "advisory"
    assert state["phase"] == "red"
    assert state["enforced"] is False
    assert "RED" in guard.explain(production)
    assert "advisory" in guard.explain(production).lower()


def test_advisory_guard_freezes_verification_paths_during_green(tmp_path: Path) -> None:
    _production, verification = _workspace(tmp_path)
    guard = AdvisoryGuard(tmp_path, PytestAdapter())
    guard.enforce_red()

    guarded = guard.enforce_green(["tests/test_feature.py"])

    assert guarded == [verification]
    assert guard.describe()["phase"] == "green"

    assert guard.restore() == [verification]
    assert guard.describe()["phase"] is None


def test_advisory_guard_never_reports_drift_so_recovery_stays_idempotent(tmp_path: Path) -> None:
    _workspace(tmp_path)
    guard = AdvisoryGuard(tmp_path, PytestAdapter())
    guard.enforce_red()

    assert guard.recover(expected_phase="red")["action"] == "consistent"
    assert guard.recover(expected_phase=None)["action"] == "restored"


def test_factory_falls_back_to_the_advisory_backend_off_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SINUSTDD_GUARD", raising=False)
    monkeypatch.setattr("sinustdd.workspace_guard.os.name", "nt")

    guard = get_workspace_guard(tmp_path, PytestAdapter())

    assert isinstance(guard, AdvisoryGuard)


def test_factory_honors_an_explicit_backend_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SINUSTDD_GUARD", "advisory")
    assert isinstance(get_workspace_guard(tmp_path, PytestAdapter()), AdvisoryGuard)

    monkeypatch.setenv("SINUSTDD_GUARD", "off")
    assert get_workspace_guard(tmp_path, PytestAdapter()) is None

    monkeypatch.setenv("SINUSTDD_GUARD", "unsupported-backend")
    with pytest.raises(ValueError, match="unsupported-backend"):
        get_workspace_guard(tmp_path, PytestAdapter())


@pytest.mark.skipif(
    not isinstance(get_workspace_guard(Path.cwd(), PytestAdapter()), PosixPermissionGuard),
    reason="POSIX default backend required",
)
def test_factory_defaults_to_posix_enforcement_where_it_is_available(tmp_path: Path) -> None:
    guard = get_workspace_guard(tmp_path, PytestAdapter())

    assert isinstance(guard, PosixPermissionGuard)
    assert guard.describe()["backend"] == "posix-permissions"
