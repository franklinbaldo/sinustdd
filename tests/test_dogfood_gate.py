from __future__ import annotations

import subprocess
from pathlib import Path

from sinustdd.dogfood_gate import check_pr_ready
from sinustdd.evidence import write_phase_evidence
from sinustdd.models import Phase


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)


def _init_repo(root: Path) -> None:
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "sinustdd@example.invalid")
    _git(root, "config", "user.name", "SinusTDD Test")
    gate = root / "src" / "sinustdd" / "dogfood_gate.py"
    gate.parent.mkdir(parents=True)
    gate.write_text("# gate exists on base\n", encoding="utf-8")
    source = root / "src" / "feature.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(root, "baseline")
    _git(root, "switch", "-c", "feature")


def test_gate_blocks_product_change_without_complete_cycle(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    source = tmp_path / "src" / "feature.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(tmp_path, "change product code")

    result = check_pr_ready(tmp_path, "main")

    assert not result.passed
    assert "require a SinusTDD cycle" in result.message


def test_gate_accepts_timestamped_complete_cycle(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    source = tmp_path / "src" / "feature.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")

    cycle_id = "cycle-dogfood"
    baseline_path, _ = write_phase_evidence(
        root=tmp_path,
        cycle_id=cycle_id,
        phase=Phase.BASELINE,
        repository_ref="base",
        payload={"tests_passed": ["test_old"]},
    )
    red_path, _ = write_phase_evidence(
        root=tmp_path,
        cycle_id=cycle_id,
        phase=Phase.RED,
        repository_ref="red",
        payload={"failed_tests": ["test_new"]},
    )
    green_path, _ = write_phase_evidence(
        root=tmp_path,
        cycle_id=cycle_id,
        phase=Phase.GREEN,
        repository_ref="green",
        payload={"tests_passed": ["test_old", "test_new"]},
    )
    _commit_all(tmp_path, "change with causal evidence")

    assert baseline_path.name.endswith("-baseline.md")
    assert red_path.name.endswith("-red.md")
    assert green_path.name.endswith("-green.md")
    assert baseline_path.name < red_path.name < green_path.name

    result = check_pr_ready(tmp_path, "main")

    assert result.passed
    assert result.checked_cycles == (cycle_id,)
