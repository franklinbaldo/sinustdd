# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "rich>=13.0",
# ]
# ///
"""Validate that all standalone scripts in scripts/ have valid PEP 723 inline metadata."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from rich.console import Console

console = Console()
PEP723_REGEX = re.compile(
    r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(?:^#(| .*)$\s)+)^# ///$",
)


def parse_pep723(content: str) -> dict[str, object] | None:
    match = PEP723_REGEX.search(content)
    if not match:
        return None
    script_type = match.group("type")
    if script_type != "script":
        return None
    raw_lines = match.group("content").splitlines()
    uncommented = "\n".join(
        line[2:] if line.startswith("# ") else line[1:] if line.startswith("#") else line
        for line in raw_lines
    )
    try:
        return tomllib.loads(uncommented)
    except Exception as exc:
        console.print(f"[red]Invalid TOML in script block:[/red] {exc}")
        return None


def validate_scripts(scripts_dir: Path) -> bool:
    console.print(f"[bold cyan]Validating PEP 723 metadata in:[/bold cyan] {scripts_dir}")
    all_valid = True
    py_files = sorted(scripts_dir.glob("*.py"))
    if not py_files:
        console.print("[yellow]No python scripts found in scripts/[/yellow]")
        return True

    for file_path in py_files:
        content = file_path.read_text(encoding="utf-8")
        meta = parse_pep723(content)
        if meta is None:
            console.print(
                f"[bold red]✗ Missing or invalid PEP 723 block:[/bold red] {file_path.name}"
            )
            all_valid = False
            continue

        requires_python = meta.get("requires-python")
        deps = meta.get("dependencies")
        if not requires_python:
            console.print(f"[bold red]✗ {file_path.name}:[/bold red] missing 'requires-python'")
            all_valid = False
        elif not isinstance(deps, list):
            console.print(f"[bold red]✗ {file_path.name}:[/bold red] missing 'dependencies' list")
            all_valid = False
        else:
            msg = f"valid PEP 723 script ({requires_python}, {len(deps)} deps)"
            console.print(f"[bold green]✓ {file_path.name}:[/bold green] {msg}")

    return all_valid


def main() -> int:
    scripts_dir = Path(__file__).parent.parent / "scripts"
    if not validate_scripts(scripts_dir):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
