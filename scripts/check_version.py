# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "rich>=13.0",
#     "ruamel-yaml>=0.18",
# ]
# ///
"""Check version synchronization across the repository and changelog presence.

Rules enforced:
1. Canonical version is single-sourced in src/wikiskill/__init__.py.
2. The current version has at least one matching change card in changelog/changes/.
3. Every change card in changelog/changes/ has valid frontmatter (type: Changelog, version, date).
"""

import re
import subprocess
import sys
from pathlib import Path

from rich.console import Console

console = Console()
ROOT = Path(__file__).parent.parent


def _git(*args: str) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return res.stdout.strip() if res.returncode == 0 else ""


def parse_semver(ver: str) -> tuple[int, int, int]:
    parts = ver.split(".", 2)
    if len(parts) != 3:
        msg = f"Invalid SemVer: {ver}"
        raise ValueError(msg)
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def get_base_version(base_ref: str = "origin/main") -> str | None:
    content = _git("show", f"{base_ref}:src/sinustdd/__init__.py")
    if not content:
        return None
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
    return m.group(1) if m else None


def check_breaking_test_changes(base_ref: str = "origin/main") -> bool:
    """Check if existing tests were deleted or modified with removed assertions."""
    diff = _git("diff", "-U0", f"{base_ref}...HEAD", "--", "tests/")
    if not diff:
        diff = _git("diff", "-U0", base_ref, "--", "tests/")
    # If lines starting with -assert were deleted in tests, it suggests a modified expectation
    deleted_assertions = [
        line
        for line in diff.splitlines()
        if line.startswith("-") and not line.startswith("---") and "assert" in line
    ]
    return len(deleted_assertions) > 0


def get_canonical_version() -> str:
    content = (ROOT / "src/sinustdd/__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
    if not m:
        msg = "Cannot find __version__ in src/sinustdd/__init__.py"
        raise ValueError(msg)
    return m.group(1)


def parse_frontmatter(file_path: Path) -> dict[str, str]:
    text = file_path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    res: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            res[k.strip()] = v.strip()
    return res


def check_version_and_changelog() -> bool:
    console.print("[bold cyan]Checking single-source version & changelog...[/bold cyan]")
    version = get_canonical_version()
    console.print(f"[bold green]✓ Canonical version (__init__.py):[/bold green] {version}")

    errors: list[str] = []

    # Discover changelog files
    changelog_dir = ROOT / "changelog"
    changes_dir = changelog_dir / "changes"
    change_files = list(changes_dir.glob("*.md")) if changes_dir.is_dir() else []
    version_files = list(changelog_dir.glob(f"{version}.md"))

    matching_cards: list[Path] = []

    for card in change_files:
        fm = parse_frontmatter(card)
        c_type = fm.get("type", "")
        c_ver = fm.get("version", "")
        if c_type.lower() != "changelog":
            errors.append(f"{card.name}: frontmatter missing `type: Changelog`")
        if not c_ver:
            errors.append(f"{card.name}: frontmatter missing `version`")
        elif c_ver == version:
            matching_cards.append(card)

    if version_files:
        matching_cards.extend(version_files)

    if not matching_cards:
        errors.append(f"No changelog entry found for version {version} in changelog/changes/")
    else:
        console.print(
            f"[bold green]✓ Changelog confirmed:[/bold green] {len(matching_cards)} entry(ies)"
        )
        for card in matching_cards:
            console.print(f"   + {card.relative_to(ROOT)}")

    # Check SemVer transition against base branch if available
    base_version = get_base_version("origin/main")
    if base_version and base_version != version:
        try:
            curr_major, curr_minor, curr_patch = parse_semver(version)
            base_major, base_minor, base_patch = parse_semver(base_version)
            is_breaking = check_breaking_test_changes("origin/main")

            if is_breaking:
                # If breaking changes exist, bump must be at least MINOR (0.x) or MAJOR (1.x+)
                if curr_major == base_major and curr_minor == base_minor:
                    msg = (
                        f"Breaking test changes detected against {base_version}! "
                        f"Patch bump {version} is rejected — a minor or major bump is required."
                    )
                    errors.append(msg)
                else:
                    msg = f"! Non-patch bump ({base_version} -> {version}) accepted"
                    console.print(f"[bold yellow]{msg}[/bold yellow]")
        except Exception as exc:
            console.print(f"[yellow]Warning during semver diff comparison: {exc}[/yellow]")

    if errors:
        console.print("[bold red]Errors detected:[/bold red]")
        for err in errors:
            console.print(f"  ✗ {err}")
        return False

    return True


def main() -> int:
    if not check_version_and_changelog():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
