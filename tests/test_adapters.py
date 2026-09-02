from __future__ import annotations

from pathlib import Path

import pytest

from sinustdd.adapters import PytestAdapter, VitestAdapter, get_adapter


def test_pytest_adapter_detection(tmp_path: Path) -> None:
    adapter = PytestAdapter()
    assert adapter.detect(tmp_path) == 0.0

    (tmp_path / "pyproject.toml").write_text("[tool.pytest]", encoding="utf-8")
    assert adapter.detect(tmp_path) >= 0.5


def test_vitest_adapter_detection(tmp_path: Path) -> None:
    adapter = VitestAdapter()
    assert adapter.detect(tmp_path) == 0.0

    pkg = tmp_path / "package.json"
    pkg.write_text(
        '{"devDependencies": {"vitest": "^1.0.0"}, "scripts": {"test": "vitest run"}}',
        encoding="utf-8",
    )
    assert adapter.detect(tmp_path) >= 0.7

    selected = get_adapter(tmp_path)
    assert selected.name == "vitest"

    with pytest.raises(ValueError, match="Unknown test adapter"):
        get_adapter(tmp_path, explicit_adapter="unknown_runner")

    explicit = get_adapter(tmp_path, explicit_adapter="pytest")
    assert explicit.name == "pytest"


def test_pytest_adapter_run_tests_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = PytestAdapter()

    class FakeProc:
        returncode = 1
        stdout = "tests/test_foo.py::test_fail FAILED\ntests/test_bar.py::test_pass PASSED\n"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeProc())

    run = adapter.run_tests(tmp_path, selection=["tests/test_foo.py"])
    assert not run.passed
    assert run.tests_failed == ["tests/test_foo.py::test_fail"]
    assert run.tests_passed == ["tests/test_bar.py::test_pass"]
    assert run.failure_fingerprint != ""


def test_vitest_adapter_run_tests_parsing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = VitestAdapter()

    class FakeProc:
        returncode = 0
        stdout = "✓ src/app.test.ts > renders\n"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: FakeProc())

    run = adapter.run_tests(tmp_path)
    assert run.passed
    assert len(run.tests_passed) == 1
