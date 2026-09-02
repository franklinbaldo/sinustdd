from __future__ import annotations

import pytest

from sinustdd import __version__
from sinustdd.cli import info


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_info(capsys: pytest.CaptureFixture[str]) -> None:
    info()
    captured = capsys.readouterr()
    assert "sinustdd v0.1.0" in captured.out
