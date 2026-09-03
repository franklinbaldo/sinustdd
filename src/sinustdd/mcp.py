"""FastMCP server for sinustdd protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from sinustdd.adapters import get_adapter
from sinustdd.engine import SinusTDDEngine
from sinustdd.workspace_guard import WorkspaceGuard, get_workspace_guard

mcp = FastMCP(name="sinustdd")


def _engine() -> SinusTDDEngine:
    root = Path.cwd()
    adapter = get_adapter(root)
    guard = get_workspace_guard(root, adapter)
    return SinusTDDEngine(root, adapter=adapter, workspace_guard=guard)


def _guard() -> WorkspaceGuard | None:
    root = Path.cwd()
    return get_workspace_guard(root, get_adapter(root))


_NO_BACKEND = "No workspace guard backend is available on this platform."


@mcp.tool(
    name="sinustdd_status",
    description="Get the current harmonic TDD phase (theta), active cycle, and witness status.",
    annotations={"readOnlyHint": True},
)
def sinustdd_status() -> dict[str, Any]:
    """Inspect current harmonic TDD cycle and recorded witnesses."""
    return _engine().status()


@mcp.tool(
    name="sinustdd_begin",
    description="Snapshot the baseline state and begin a new harmonic TDD cycle.",
)
def sinustdd_begin() -> dict[str, Any]:
    """Initialize a new TDD cycle at theta = 0 (Baseline)."""
    cycle = _engine().begin()
    return cycle.model_dump()


@mcp.tool(
    name="sinustdd_red",
    description=(
        "Validate that newly added tests fail legitimately against baseline production code, "
        "locking RedWitness."
    ),
)
def sinustdd_red() -> dict[str, Any]:
    """Verify red phase invariants and record RedWitness at theta = pi."""
    witness = _engine().mark_red()
    return witness.model_dump()


@mcp.tool(
    name="sinustdd_green",
    description=(
        "Validate that production changes satisfy the red witness with frozen test assertions."
    ),
)
def sinustdd_green() -> dict[str, Any]:
    """Verify green phase invariants and record GreenWitness at theta = 1.5 pi."""
    witness = _engine().mark_green()
    return witness.model_dump()


@mcp.tool(
    name="sinustdd_refactor",
    description="Enter refactor phase allowing code cleanup while preserving 100% green tests.",
)
def sinustdd_refactor() -> dict[str, Any]:
    """Transition to refactor phase at theta = 2 pi."""
    cycle = _engine().mark_refactor()
    return cycle.model_dump()


@mcp.tool(
    name="sinustdd_complete",
    description="Seal and archive the completed TDD cycle with full causal witness audit trail.",
)
def sinustdd_complete() -> dict[str, Any]:
    """Finalize cycle and persist record."""
    cycle = _engine().complete()
    return cycle.model_dump()


@mcp.tool(
    name="sinustdd_guard_status",
    description=(
        "Report which workspace capabilities the phase guard is currently materializing, "
        "including the enforced phase and the read-only paths."
    ),
    annotations={"readOnlyHint": True},
)
def sinustdd_guard_status() -> dict[str, Any]:
    """Inspect the workspace guard without changing any permission."""
    guard = _guard()
    if guard is None:
        return {"backend": None, "phase": None, "enforcing": False, "guarded_paths": []}
    return guard.describe()


@mcp.tool(
    name="sinustdd_guard_explain",
    description=(
        "Explain why a specific workspace path is currently read-only, so an agent can "
        "recover from a permission error instead of fighting the filesystem."
    ),
    annotations={"readOnlyHint": True},
)
def sinustdd_guard_explain(path: str) -> dict[str, Any]:
    """Explain the causal reason a path is guarded."""
    guard = _guard()
    explanation = _NO_BACKEND if guard is None else guard.explain(Path(path))
    return {"path": path, "explanation": explanation}


@mcp.tool(
    name="sinustdd_guard_recover",
    description=(
        "Reconcile workspace permissions with the active cycle after a crash, a restart, "
        "or an external tool that changed file modes."
    ),
)
def sinustdd_guard_recover() -> dict[str, Any]:
    """Re-materialize the capabilities of the active cycle phase."""
    return _engine().recover_workspace()
