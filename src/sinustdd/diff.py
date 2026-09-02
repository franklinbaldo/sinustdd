"""Diff analysis and repository classification for TDD phase validation."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field


class DiffClassification(BaseModel):
    test_files_modified: list[str] = Field(default_factory=list)
    test_files_added: list[str] = Field(default_factory=list)
    production_files_modified: list[str] = Field(default_factory=list)
    production_files_added: list[str] = Field(default_factory=list)
    has_test_changes: bool = False
    has_production_changes: bool = False


def run_git(*args: str, cwd: Path) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return res.stdout.strip() if res.returncode == 0 else ""


def get_head_commit(cwd: Path) -> str:
    return run_git("rev-parse", "HEAD", cwd=cwd) or "initial"


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file's content normalized for line endings."""
    if not path.is_file():
        return ""
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def compute_test_files_hashes(cwd: Path, test_files: list[str]) -> dict[str, str]:
    """Compute mapping from test file path to SHA-256 digest."""
    hashes: dict[str, str] = {}
    for rel_path in test_files:
        full_path = cwd / rel_path
        if full_path.is_file():
            hashes[rel_path] = compute_file_hash(full_path)
    return hashes


def classify_diff(cwd: Path, base_ref: str | None = None) -> DiffClassification:
    """Classify modified and added files between working directory (or HEAD) and base_ref."""
    cmd = ["diff", "--name-status"]
    if base_ref:
        cmd.append(base_ref)

    raw = run_git(*cmd, cwd=cwd)
    classification = DiffClassification()

    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][0]
        filepath = parts[-1].replace("\\", "/")

        is_test = filepath.startswith("tests/") or "test_" in filepath or "_test.py" in filepath
        is_prod = filepath.startswith("src/") or (filepath.endswith(".py") and not is_test)

        if is_test:
            if status == "A":
                classification.test_files_added.append(filepath)
            else:
                classification.test_files_modified.append(filepath)
            classification.has_test_changes = True
        elif is_prod:
            if status == "A":
                classification.production_files_added.append(filepath)
            else:
                classification.production_files_modified.append(filepath)
            classification.has_production_changes = True

    return classification
