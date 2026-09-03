from __future__ import annotations

from pathlib import Path

import cyclopts
from rich.console import Console

from sinustdd import __version__
from sinustdd.adapters import get_adapter
from sinustdd.engine import SinusTDDEngine, StateTransitionError
from sinustdd.workspace_guard import WorkspaceGuard, get_workspace_guard

console = Console()
app = cyclopts.App(
    name="sinustdd",
    help="Sinusoidal TDD Harmonic State Machine for Autonomous Coding Agents.",
    version=__version__,
)


guard_app = cyclopts.App(name="guard", help="Inspect the filesystem capabilities Sinos enforces.")
app.command(guard_app)


def _engine() -> SinusTDDEngine:
    root = Path.cwd()
    adapter = get_adapter(root)
    guard = get_workspace_guard(root, adapter)
    return SinusTDDEngine(root, adapter=adapter, workspace_guard=guard)


def _guard() -> WorkspaceGuard | None:
    root = Path.cwd()
    return get_workspace_guard(root, get_adapter(root))


@guard_app.command(name="status")
def guard_status() -> None:
    """Show which workspace capabilities the guard is currently materializing."""
    guard = _guard()
    if guard is None:
        console.print("[yellow]No workspace guard backend is available on this platform.[/yellow]")
        return
    state = guard.describe()
    console.print(f"[bold cyan]Guard backend:[/bold cyan] {state['backend']}")
    if not state["enforcing"]:
        console.print("[yellow]Guard is idle: no phase is being enforced.[/yellow]")
        return
    console.print(f"[bold green]Enforcing phase:[/bold green] {state['phase']}")
    for path in state["guarded_paths"]:
        console.print(f"  [dim]read-only[/dim] {path}")


@guard_app.command(name="recover")
def guard_recover() -> None:
    """Re-materialize the workspace capabilities implied by the active cycle."""
    report = _engine().recover_workspace()
    action = report["action"]
    if action == "unavailable":
        console.print("[yellow]No workspace guard backend is available on this platform.[/yellow]")
        return
    if report.get("recovered_from_corrupt_state"):
        console.print("[yellow]Discarded unreadable guard state before recovering.[/yellow]")
    console.print(f"[bold cyan]Workspace guard {action}[/bold cyan] (phase: {report['phase']})")


@guard_app.command(name="explain")
def guard_explain(path: Path) -> None:
    """Explain why a specific path is read-only under the current phase."""
    guard = _guard()
    if guard is None:
        console.print("[yellow]No workspace guard backend is available on this platform.[/yellow]")
        return
    console.print(guard.explain(path))


@app.command
def info() -> None:
    """Show sinustdd runtime version and harmonic state info."""
    console.print(f"[bold cyan]sinustdd v{__version__}[/bold cyan] - Harmonic Causal TDD Engine")


@app.command
def status() -> None:
    """Show current cycle, phase angle (theta), and active witnesses."""
    st = _engine().status()
    if not st["active"]:
        console.print("[yellow]No active cycle. Run sinustdd begin to start a new cycle.[/yellow]")
        return
    console.print(f"[bold cyan]Active Cycle:[/bold cyan] {st['cycle_id']}")
    console.print(f"[bold green]Phase:[/bold green] {st['phase']} (θ = {st['theta']:.2f} rad)")
    base = st["baseline_commit"][:8] if st["baseline_commit"] else "none"
    console.print(f"[bold]Baseline Commit:[/bold] {base}")
    if st["red_witness"]:
        console.print(
            "[bold red]✓ RedWitness locked:[/bold red]", st["red_witness"]["failed_tests"]
        )
    if st["green_witness"]:
        console.print(
            "[bold green]✓ GreenWitness locked:[/bold green]",
            st["green_witness"]["production_files_modified"],
        )


@app.command
def begin() -> None:
    """Snapshot baseline repository state and initialize cycle (theta = 0)."""
    try:
        cycle = _engine().begin()
        base = cycle.baseline_commit[:8]
        msg = f"[bold green]✓ Begun new cycle:[/bold green] {cycle.cycle_id} at baseline {base}"
        console.print(msg)
    except StateTransitionError as err:
        console.print(f"[bold red]✗ Failed to begin cycle:[/bold red] {err}")


@app.command
def red() -> None:
    """Verify test failure on baseline production and lock RedWitness (theta = pi)."""
    try:
        witness = _engine().mark_red()
        count = len(witness.failed_tests)
        console.print(f"[bold red]✓ RedWitness locked (θ = π):[/bold red] {count} test(s) failed.")
    except StateTransitionError as err:
        console.print(f"[bold red]✗ Red phase invariant violation:[/bold red] {err}")


@app.command
def green() -> None:
    """Verify production changes satisfy red witness with frozen test assertions."""
    try:
        _engine().mark_green()
        console.print(
            "[bold green]✓ GreenWitness locked (θ = 1.5π):[/bold green] all tests passed."
        )
    except StateTransitionError as err:
        console.print(f"[bold red]✗ Green phase invariant violation:[/bold red] {err}")


@app.command
def refactor() -> None:
    """Enter refactor phase allowing structural cleanup (theta = 2 pi)."""
    try:
        _engine().mark_refactor()
        console.print(
            "[bold blue]✓ Entered REFACTOR phase (θ = 2π):[/bold blue] suite is 100% green."
        )
    except StateTransitionError as err:
        console.print(f"[bold red]✗ Refactor phase violation:[/bold red] {err}")


@app.command
def complete() -> None:
    """Finalize cycle and seal proof record into .sinustdd/cycles/."""
    try:
        cycle = _engine().complete()
        console.print(f"[bold green]✓ Cycle {cycle.cycle_id} completed and sealed.[/bold green]")
    except StateTransitionError as err:
        console.print(f"[bold red]✗ Failed to complete cycle:[/bold red] {err}")


@app.command
def serve() -> None:
    """Start FastMCP server over stdio for AI agent orchestration."""
    from sinustdd.mcp import mcp

    mcp.run()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
