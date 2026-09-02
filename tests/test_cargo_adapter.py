from __future__ import annotations

from pathlib import Path

from sinustdd.adapters import CargoAdapter, get_adapter


def test_cargo_adapter_detection(tmp_path: Path) -> None:
    adapter = CargoAdapter()
    assert adapter.detect(tmp_path) == 0.0

    cargo_content = '[package]\nname = "my_crate"\nversion = "0.1.0"'
    (tmp_path / "Cargo.toml").write_text(cargo_content, encoding="utf-8")
    assert adapter.detect(tmp_path) >= 0.8

    selected = get_adapter(tmp_path)
    assert selected.name == "cargo"
