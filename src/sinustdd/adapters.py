"""Pluggable, multi-ecosystem test adapter protocol and structured execution."""

from __future__ import annotations

import hashlib
import json
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TestFailure(BaseModel):
    """Structured test failure identifying the test and its source file."""

    __test__ = False
    test_id: str
    source_file: str
    message: str = ""


class TestRun(BaseModel):
    """Normalized test execution report understood by the causal core."""

    __test__ = False
    adapter_name: str
    passed: bool
    returncode: int
    output: str
    tests_discovered: list[str] = Field(default_factory=list)
    tests_passed: list[str] = Field(default_factory=list)
    tests_failed: list[str] = Field(default_factory=list)
    structured_failures: list[TestFailure] = Field(default_factory=list)
    tests_skipped: list[str] = Field(default_factory=list)
    failure_fingerprint: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AdapterDetection:
    adapter: TestAdapter
    confidence: float
    evidence: list[str] = field(default_factory=list)


class TestAdapter(ABC):
    """Abstract contract for language/framework test runners."""

    name: str

    @abstractmethod
    def detect(self, root: Path) -> float:
        """Return confidence score [0.0, 1.0] that this project uses this runner."""

    @abstractmethod
    def run_tests(self, root: Path, selection: list[str] | None = None) -> TestRun:
        """Execute the test runner and return a normalized TestRun."""


class PytestAdapter(TestAdapter):
    """Adapter for Python test suites using pytest."""

    name = "pytest"

    def detect(self, root: Path) -> float:
        confidence = 0.0
        if (root / "pytest.ini").is_file() or (root / "pyproject.toml").is_file():
            confidence += 0.5
        if (root / "tests").is_dir() or any(root.glob("test_*.py")):
            confidence += 0.4
        return min(1.0, confidence)

    def run_tests(self, root: Path, selection: list[str] | None = None) -> TestRun:
        cmd = ["pytest", "-v", "--no-header"]
        if selection:
            cmd.extend(selection)

        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        failed: list[str] = []
        passed: list[str] = []
        struct_failures: list[TestFailure] = []

        for line in output.splitlines():
            if " FAILED " in line or line.endswith(" FAILED"):
                test_name = line.split()[0] if line.split() else line
                failed.append(test_name)
                src = test_name.split("::")[0].replace("\\", "/")
                struct_failures.append(TestFailure(test_id=test_name, source_file=src))
            elif " ERROR " in line or line.startswith("ERROR "):
                test_name = line.split()[-1] if line.split() else line
                failed.append(test_name)
                src = test_name.split("::")[0].replace("\\", "/")
                struct_failures.append(TestFailure(test_id=test_name, source_file=src))
            elif " PASSED " in line or line.endswith(" PASSED"):
                test_name = line.split()[0] if line.split() else line
                passed.append(test_name)

        fingerprint = ""
        if failed:
            raw_sig = "\n".join(sorted(failed)) + "\n" + output
            fingerprint = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()[:16]

        return TestRun(
            adapter_name=self.name,
            passed=proc.returncode == 0,
            returncode=proc.returncode,
            output=output,
            tests_passed=passed,
            tests_failed=failed,
            structured_failures=struct_failures,
            failure_fingerprint=fingerprint,
        )


class VitestAdapter(TestAdapter):
    """Adapter for TypeScript/JavaScript test suites using Vitest."""

    name = "vitest"

    def detect(self, root: Path) -> float:
        pkg = root / "package.json"
        if not pkg.is_file():
            return 0.0
        confidence = 0.3
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            dev_deps = data.get("devDependencies", {})
            deps = data.get("dependencies", {})
            scripts = data.get("scripts", {})

            if "vitest" in dev_deps or "vitest" in deps:
                confidence += 0.5
            if any("vitest" in s for s in scripts.values()):
                confidence += 0.2
        except Exception:
            pass

        if (root / "vitest.config.ts").is_file() or (root / "vitest.config.js").is_file():
            confidence += 0.3
        return min(1.0, confidence)

    def run_tests(self, root: Path, selection: list[str] | None = None) -> TestRun:
        cmd = ["npx", "vitest", "run"]
        if selection:
            cmd.extend(selection)

        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        failed: list[str] = []
        passed: list[str] = []
        struct_failures: list[TestFailure] = []

        for line in output.splitlines():
            if "✕" in line or "FAIL" in line:
                failed.append(line.strip())
                struct_failures.append(TestFailure(test_id=line.strip(), source_file="tests"))
            elif "✓" in line or "PASS" in line:
                passed.append(line.strip())

        fingerprint = ""
        if failed:
            raw_sig = "\n".join(sorted(failed)) + "\n" + output
            fingerprint = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()[:16]

        return TestRun(
            adapter_name=self.name,
            passed=proc.returncode == 0,
            returncode=proc.returncode,
            output=output,
            tests_passed=passed,
            tests_failed=failed,
            structured_failures=struct_failures,
            failure_fingerprint=fingerprint,
        )


class CargoAdapter(TestAdapter):
    """Adapter for Rust projects using cargo test."""

    name = "cargo"

    def detect(self, root: Path) -> float:
        if (root / "Cargo.toml").is_file():
            return 0.9
        return 0.0

    def run_tests(self, root: Path, selection: list[str] | None = None) -> TestRun:
        cmd = ["cargo", "test"]
        if selection:
            cmd.extend(selection)

        proc = subprocess.run(
            cmd,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        failed: list[str] = []
        passed: list[str] = []
        struct_failures: list[TestFailure] = []

        for line in output.splitlines():
            if "test " in line and " ... FAILED" in line:
                test_name = line.replace("test ", "").replace(" ... FAILED", "").strip()
                failed.append(test_name)
                struct_failures.append(TestFailure(test_id=test_name, source_file="tests"))
            elif "test " in line and " ... ok" in line:
                test_name = line.replace("test ", "").replace(" ... ok", "").strip()
                passed.append(test_name)

        fingerprint = ""
        if failed:
            raw_sig = "\n".join(sorted(failed)) + "\n" + output
            fingerprint = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()[:16]

        return TestRun(
            adapter_name=self.name,
            passed=proc.returncode == 0,
            returncode=proc.returncode,
            output=output,
            tests_passed=passed,
            tests_failed=failed,
            structured_failures=struct_failures,
            failure_fingerprint=fingerprint,
        )


REGISTRY: list[TestAdapter] = [PytestAdapter(), VitestAdapter(), CargoAdapter()]


def get_adapter(root: Path, explicit_adapter: str | None = None) -> TestAdapter:
    """Discover the highest confidence adapter for the workspace."""
    if explicit_adapter:
        for ad in REGISTRY:
            if ad.name == explicit_adapter:
                return ad
        raise ValueError(f"Unknown test adapter: {explicit_adapter}")

    best_adapter: TestAdapter | None = None
    best_score = 0.0

    for ad in REGISTRY:
        score = ad.detect(root)
        if score > best_score:
            best_score = score
            best_adapter = ad

    if best_adapter is None:
        raise ValueError(f"No compatible test adapter detected for {root}")

    return best_adapter
