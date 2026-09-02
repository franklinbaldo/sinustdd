"""Test runner integration and failure fingerprint extraction."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from pydantic import BaseModel


class TestExecutionResult(BaseModel):
    passed: bool
    returncode: int
    output: str
    failed_tests: list[str] = []
    passed_tests: list[str] = []
    failure_fingerprint: str = ""


def run_tests(cwd: Path) -> TestExecutionResult:
    """Run pytest in project root and parse outcome and failure fingerprint."""
    proc = subprocess.run(
        ["pytest", "-v", "--no-header"],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    output = (proc.stdout + "\n" + proc.stderr).strip()
    failed_tests: list[str] = []
    passed_tests: list[str] = []

    for line in output.splitlines():
        if " FAILED " in line or line.endswith(" FAILED"):
            test_name = line.split()[0] if line.split() else line
            failed_tests.append(test_name)
        elif " PASSED " in line or line.endswith(" PASSED"):
            test_name = line.split()[0] if line.split() else line
            passed_tests.append(test_name)

    fingerprint = ""
    if failed_tests:
        raw_sig = "\n".join(sorted(failed_tests)) + "\n" + output
        fingerprint = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()[:16]

    return TestExecutionResult(
        passed=proc.returncode == 0,
        returncode=proc.returncode,
        output=output,
        failed_tests=failed_tests,
        passed_tests=passed_tests,
        failure_fingerprint=fingerprint,
    )
