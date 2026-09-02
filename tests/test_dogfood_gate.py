from __future__ import annotations

import subprocess
from pathlib import Path

from sinustdd.dogfood_gate import check_pr_ready
from sinustdd.evidence import write_phase_evidence
from sinustdd.models import Phase


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


def _git_output(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


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


def _write_complete_cycle(
    root: Path,
    cycle_id: str,
    baseline_ref: str,
    red_ref: str | None = None,
    green_ref: str | None = None,
) -> None:
    write_phase_evidence(
        root=root,
        cycle_id=cycle_id,
        phase=Phase.BASELINE,
        repository_ref=baseline_ref,
        payload={"baseline_commit": baseline_ref, "tests_passed": ["test_old"]},
    )
    write_phase_evidence(
        root=root,
        cycle_id=cycle_id,
        phase=Phase.RED,
        repository_ref=red_ref or baseline_ref,
        payload={"failed_tests": ["test_new"]},
    )
    write_phase_evidence(
        root=root,
        cycle_id=cycle_id,
        phase=Phase.GREEN,
        repository_ref=green_ref or red_ref or baseline_ref,
        payload={"tests_passed": ["test_old", "test_new"]},
    )


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
    baseline_ref = _git_output(tmp_path, "rev-parse", "main")
    source = tmp_path / "src" / "feature.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")

    cycle_id = "cycle-dogfood"
    _write_complete_cycle(tmp_path, cycle_id, baseline_ref)
    cycle_dir = tmp_path / ".sinustdd" / "evidence" / cycle_id
    phase_files = sorted(path.name for path in cycle_dir.glob("*.md"))
    _commit_all(tmp_path, "change with causal evidence")

    assert phase_files[0].endswith("-baseline.md")
    assert phase_files[1].endswith("-red.md")
    assert phase_files[2].endswith("-green.md")

    result = check_pr_ready(tmp_path, "main")

    assert result.passed
    assert result.checked_cycles == (cycle_id,)


def test_gate_rejects_complete_cycle_from_unrelated_history(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    source = tmp_path / "src" / "feature.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")

    cycle_id = "cycle-unrelated"
    _write_complete_cycle(tmp_path, cycle_id, "deadbeef")
    _commit_all(tmp_path, "change with unrelated causal evidence")

    result = check_pr_ready(tmp_path, "main")

    assert not result.passed
    assert "baseline ref" in result.message
    assert "not an ancestor" in result.message


def test_gate_rejects_invalid_red_or_green_refs(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    baseline_ref = _git_output(tmp_path, "rev-parse", "main")
    source = tmp_path / "src" / "feature.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")

    cycle_id = "cycle-invalid-red"
    _write_complete_cycle(
        tmp_path,
        cycle_id,
        baseline_ref,
        red_ref="deadbeef",
        green_ref=baseline_ref,
    )
    _commit_all(tmp_path, "change with invalid red ref")

    result = check_pr_ready(tmp_path, "main")

    assert not result.passed
    assert "red ref" in result.message


def test_gate_rejects_out_of_order_git_history(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    baseline_ref = _git_output(tmp_path, "rev-parse", "main")

    marker = tmp_path / "tests" / "test_marker.py"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("def test_marker(): assert True\n", encoding="utf-8")
    _commit_all(tmp_path, "red checkpoint")
    red_ref = _git_output(tmp_path, "rev-parse", "HEAD")

    source = tmp_path / "src" / "feature.py"
    source.write_text("VALUE = 2\n", encoding="utf-8")
    _commit_all(tmp_path, "green checkpoint")
    green_ref = _git_output(tmp_path, "rev-parse", "HEAD")

    cycle_id = "cycle-reversed"
    _write_complete_cycle(
        tmp_path,
        cycle_id,
        baseline_ref,
        red_ref=green_ref,
        green_ref=red_ref,
    )
    _commit_all(tmp_path, "evidence with reversed refs")

    result = check_pr_ready(tmp_path, "main")

    assert not result.passed
    assert "red ref" in result.message
    assert "not an ancestor of green ref" in result.message
