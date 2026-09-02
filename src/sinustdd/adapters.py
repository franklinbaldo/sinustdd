"""Verification adapters: operational test runners and formal theorem provers (Lean)."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class FailureKind(StrEnum):
    ASSERTION_FAILED = "assertion_failed"
    UNSOLVED_GOALS = "unsolved_goals"
    PROOF_REJECTED = "proof_rejected"
    SYNTAX_ERROR = "syntax_error"
    TYPE_ERROR = "type_error"
    UNSOUND_ESCAPE = "unsound_escape"  # e.g., sorry, admit, cheat axioms


class TestFailure(BaseModel):
    """Structured failure identifying the test/theorem, source file, and reason."""

    __test__ = False
    test_id: str
    source_file: str
    message: str = ""
    kind: FailureKind = FailureKind.ASSERTION_FAILED


class TestRun(BaseModel):
    """Normalized verification report for operational test suites and formal proofs."""

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
    is_formal_proof: bool = False
    statement_hashes: dict[str, str] = Field(default_factory=dict)
    proof_hashes: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AdapterDetection:
    adapter: VerificationAdapter
    confidence: float
    evidence: list[str] = field(default_factory=list)


class VerificationAdapter(ABC):
    """Base abstract contract for operational testing and formal verification."""

    name: str
    is_formal: bool = False

    @abstractmethod
    def detect(self, root: Path) -> float:
        """Return confidence score [0.0, 1.0] that this project uses this adapter."""

    @abstractmethod
    def run_tests(self, root: Path, selection: list[str] | None = None) -> TestRun:
        """Execute the verification tool and return a normalized TestRun."""


# Backward compatibility alias
TestAdapter = VerificationAdapter


class PytestAdapter(VerificationAdapter):
    """Adapter for Python test suites using pytest."""

    name = "pytest"

    def detect(self, root: Path) -> float:
        confidence = 0.0
        if (root / "pytest.ini").is_file() or (root / "pyproject.toml").is_file():
            confidence += 0.5
        if (root / "tests").is_dir():
            confidence += 0.4
        return min(confidence, 1.0)

    def run_tests(self, root: Path, selection: list[str] | None = None) -> TestRun:
        cmd = ["pytest", "-v", "--tb=short"]
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
        output = proc.stdout + "\n" + proc.stderr
        passed: list[str] = []
        failed: list[str] = []
        struct_failures: list[TestFailure] = []

        for line in output.splitlines():
            line_clean = line.strip()
            if " PASSED" in line_clean or line_clean.startswith("PASSED "):
                parts = line_clean.split()
                test_id = parts[0] if not line_clean.startswith("PASSED ") else parts[1]
                passed.append(test_id)
            elif " FAILED" in line_clean or line_clean.startswith("FAILED "):
                parts = line_clean.split()
                test_id = parts[0] if not line_clean.startswith("FAILED ") else parts[1]
                failed.append(test_id)
                src_file = test_id.split("::")[0] if "::" in test_id else "tests"
                struct_failures.append(
                    TestFailure(
                        test_id=test_id,
                        source_file=src_file,
                        message=line_clean,
                        kind=FailureKind.ASSERTION_FAILED,
                    )
                )

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


class VitestAdapter(VerificationAdapter):
    """Adapter for TypeScript/JavaScript projects using Vitest or Jest."""

    name = "vitest"

    def detect(self, root: Path) -> float:
        if (root / "vitest.config.ts").is_file() or (root / "vitest.config.js").is_file():
            return 0.95
        if (root / "package.json").is_file():
            pkg = root / "package.json"
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                deps = {
                    **data.get("dependencies", {}),
                    **data.get("devDependencies", {}),
                }
                if "vitest" in deps:
                    return 0.9
                if "jest" in deps:
                    return 0.8
            except Exception:
                return 0.2
        return 0.0

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
        output = proc.stdout + "\n" + proc.stderr
        failed: list[str] = []
        passed: list[str] = []
        struct_failures: list[TestFailure] = []

        for line in output.splitlines():
            if "✕" in line or "FAIL" in line:
                cleaned = line.replace("✕", "").replace("FAIL", "").strip()
                if cleaned:
                    failed.append(cleaned)
                    struct_failures.append(
                        TestFailure(
                            test_id=cleaned,
                            source_file="tests",
                            message=line,
                            kind=FailureKind.ASSERTION_FAILED,
                        )
                    )
            elif "✓" in line or "PASS" in line:
                cleaned = line.replace("✓", "").replace("PASS", "").strip()
                if cleaned:
                    passed.append(cleaned)

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


class CargoAdapter(VerificationAdapter):
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
                struct_failures.append(
                    TestFailure(
                        test_id=test_name,
                        source_file="tests",
                        message=line,
                        kind=FailureKind.ASSERTION_FAILED,
                    )
                )
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


class LeanAdapter(VerificationAdapter):
    """Adapter for Lean 4 formal proof obligations and Lake test suites."""

    name = "lean"
    is_formal: bool = True

    def detect(self, root: Path) -> float:
        confidence = 0.0
        if (root / "lakefile.toml").is_file() or (root / "lakefile.lean").is_file():
            confidence += 0.8
        if (root / "lean-toolchain").is_file():
            confidence += 0.2
        if any(root.glob("*.lean")):
            confidence += 0.3
        return min(confidence, 1.0)

    def extract_theorems_and_hashes(
        self, root: Path
    ) -> tuple[dict[str, str], dict[str, str], list[str]]:
        """Extract theorem statement hashes, proof hashes, and detect unsound escapes (sorry)."""
        statement_hashes: dict[str, str] = {}
        proof_hashes: dict[str, str] = {}
        escapes: list[str] = []

        for lean_file in root.glob("**/*.lean"):
            if ".lake" in lean_file.parts or ".sinustdd" in lean_file.parts:
                continue
            text = lean_file.read_text(encoding="utf-8", errors="ignore")
            # Parse theorem/lemma declarations: theorem <name> ... := by <proof>
            matches = re.finditer(
                r"(?:theorem|lemma)\s+([A-Za-z0-9_'\.]+)\s*(.*?):=\s*(?:by\s+)?(.*?)(?=\n\s*(?:theorem|lemma|def|inductive|structure)|\Z)",
                text,
                re.DOTALL,
            )
            for m in matches:
                name = m.group(1).strip()
                statement = m.group(2).strip()
                proof = m.group(3).strip()

                statement_hashes[name] = hashlib.sha256(statement.encode()).hexdigest()
                proof_hashes[name] = hashlib.sha256(proof.encode()).hexdigest()

                # Soundness check: sorry or admit is an unsound escape hatch
                if re.search(r"\b(sorry|admit)\b", proof):
                    escapes.append(name)

        return statement_hashes, proof_hashes, escapes

    def run_tests(self, root: Path, selection: list[str] | None = None) -> TestRun:
        cmd = ["lake", "test"]
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

        stmt_hashes, proof_hashes, escapes = self.extract_theorems_and_hashes(root)
        failed: list[str] = []
        passed: list[str] = []
        struct_failures: list[TestFailure] = []

        # 1. Unsound escape hatches are strict proof failures (sorry is not green)
        for esc in escapes:
            failed.append(esc)
            struct_failures.append(
                TestFailure(
                    test_id=esc,
                    source_file="lean",
                    message="Theorem contains unsound escape hatch ('sorry' or 'admit')",
                    kind=FailureKind.UNSOUND_ESCAPE,
                )
            )

        # 2. Parse Lean elaboration and Lake test output
        for line in output.splitlines():
            line_clean = line.strip()
            if "unsolved goals" in line_clean:
                thm_match = re.search(r"in declaration '([^']+)'", line_clean)
                thm_name = thm_match.group(1) if thm_match else "unsolved_goal"
                if thm_name not in failed:
                    failed.append(thm_name)
                    struct_failures.append(
                        TestFailure(
                            test_id=thm_name,
                            source_file="lean",
                            message=line_clean,
                            kind=FailureKind.UNSOLVED_GOALS,
                        )
                    )

        for thm in stmt_hashes:
            if thm not in failed:
                passed.append(thm)

        fingerprint = ""
        if failed:
            raw_sig = "\n".join(sorted(failed)) + "\n" + output
            fingerprint = hashlib.sha256(raw_sig.encode("utf-8")).hexdigest()[:16]

        is_passed = proc.returncode == 0 and len(failed) == 0

        return TestRun(
            adapter_name=self.name,
            passed=is_passed,
            returncode=0 if is_passed else (proc.returncode or 1),
            output=output,
            tests_passed=passed,
            tests_failed=failed,
            structured_failures=struct_failures,
            failure_fingerprint=fingerprint,
            is_formal_proof=True,
            statement_hashes=stmt_hashes,
            proof_hashes=proof_hashes,
        )


REGISTRY: list[VerificationAdapter] = [
    PytestAdapter(),
    VitestAdapter(),
    CargoAdapter(),
    LeanAdapter(),
]


def get_adapter(root: Path, explicit_adapter: str | None = None) -> VerificationAdapter:
    """Discover the highest confidence adapter for the workspace."""
    if explicit_adapter:
        for ad in REGISTRY:
            if ad.name == explicit_adapter:
                return ad
        raise ValueError(f"Unknown test adapter: {explicit_adapter}")

    best_adapter: VerificationAdapter | None = None
    best_score = 0.0

    for ad in REGISTRY:
        score = ad.detect(root)
        if score > best_score:
            best_score = score
            best_adapter = ad

    if best_adapter is None:
        raise ValueError(f"No compatible test adapter detected for {root}")

    return best_adapter
