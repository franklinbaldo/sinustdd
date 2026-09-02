"""FastMCP server for sinustdd protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from sinustdd.engine import SinusTDDEngine

mcp = FastMCP(name="sinustdd")


def _engine() -> SinusTDDEngine:
    return SinusTDDEngine(Path.cwd())


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
