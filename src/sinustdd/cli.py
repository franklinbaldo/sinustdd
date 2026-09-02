"""CLI interface for sinustdd using Cyclopts."""

from __future__ import annotations

import cyclopts

from sinustdd import __version__

app = cyclopts.App(
    name="sinustdd",
    help="Sinusoidal TDD Harmonic State Machine for Autonomous Coding Agents.",
    version=__version__,
)


@app.command
def info() -> None:
    """Show sinustdd runtime version and harmonic state info."""
    print(f"sinustdd v{__version__} - Harmonic TDD State Machine")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
