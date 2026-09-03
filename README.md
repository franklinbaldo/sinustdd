# sinustdd 🌊

> **sinustdd proves that the test became red before the code made it green.**

`sinustdd` is an opinionated verification and protocol state machine designed to enforce genuine Test-Driven Development (TDD) causal discipline on AI agents through verifiable phase transitions and silent automatic observation.

---

## 🌊 The Causal TDD Thesis

Traditional static test gates fail with AI agents because LLMs frequently:
1. **Write tests and code simultaneously**, bypassing red-phase verification.
2. **Weaken test assertions** when an implementation proves difficult ("moving the goalposts").
3. **Write tests that never failed**, providing zero causal proof that the test prevents regressions.

`sinustdd` models the TDD harmonic cycle $\theta \in [0, 2\pi]$ as a strict transition state machine with verifiable witnesses:

```text
               (θ = π)
           RED WITNESS
       [test fails against
        baseline production]
              /       \
 (θ = 0)     /         \     (θ = 2π ≡ 0)
 BASELINE ──            ── GREEN WITNESS ──── REFACTOR ──► CYCLE N+1
    (B)                     [tests frozen,
                             production G
                             makes all pass]
```

### 🔁 Invariant Phase Contracts

1. **🔴 Red Phase ($\theta = 0 \to \pi$):**
   - $\text{production\_diff}(B, R) = \emptyset$ (Source code is locked).
   - $\exists \text{ new\_test} : \text{fail}(\text{new\_test}, B)$ $\to$ Records **`RedWitness`** (failure fingerprint).
2. **🟢 Green Phase ($\theta = \pi \to 2\pi$):**
   - $\text{test\_assertion\_diff}(R, G) = \emptyset$ (Test assertions are frozen; goalposts cannot move).
   - $\text{production\_diff}(B, G) \neq \emptyset$ (Production code is implemented).
   - $\text{new\_tests} = \text{PASS} \land \text{previous\_tests} = \text{PASS}$ $\to$ Records **`GreenWitness`**.
3. **🔵 Refactor Phase ($\theta = 2\pi$):**
   - $\text{behavior\_before} == \text{behavior\_after}$ ($\text{Passing} = 100\%$).
   - Code structure improves without altering external contracts.

---

## 🛰️ Automatic Observer Mode

The preferred agent integration is passive. The agent simply writes code and tests naturally.

In **observer mode**, `sinustdd` continuously observes Git diffs, test hashes, and pytest results, following a strict **silence-on-success** contract:
- Valid phase transitions are recognized and recorded silently as **OKF evidence**.
- **Ambiguity is not a violation.** If the state is interim, `sinustdd` stays quiet.
- The agent is **only interrupted when a demonstrated invariant violation occurs** (e.g., modifying production before a Red witness exists, or weakening an assertion).

### 🔔 Notification Adapters

Violations are emitted as structured events (`ViolationEvent`):
- `code`, `cycle_id`, `inferred_phase`, `expected_invariant`, `observed_evidence`, `suggested_recovery`.
- Adapters can deliver violations via local callbacks, MCP notifications, pre-commit hooks, or CI annotations.

---

## 🚀 Interface: CLI (Cyclopts) & FastMCP

`sinustdd` exposes both a human/agent-friendly CLI powered by **Cyclopts** and an **MCP Server** powered by **FastMCP** for native integration into AI Agent harnesses.

### CLI
```bash
sinustdd begin           # Snapshot baseline B and start Cycle N
sinustdd red             # Verify test failures on B and record RedWitness
sinustdd green           # Verify production diff makes witness pass with frozen tests
sinustdd refactor        # Allow structural refactoring while preserving 100% green
sinustdd complete        # Seal Cycle N with complete audit trail
sinustdd status          # View current harmonic phase and witnesses
sinustdd serve           # Start FastMCP server over stdio

sinustdd guard status    # Show which paths the current phase freezes
sinustdd guard explain FILE   # Explain why a path is read-only right now
sinustdd guard recover   # Reconcile permissions with the active cycle after a crash
```

### FastMCP Tools
- `sinustdd_status()`: Get current phase ($\theta$), active cycle, and witness status (`readOnlyHint=True`).
- `sinustdd_begin()`: Open a new harmonic TDD cycle.
- `sinustdd_red()`: Validate and lock red witness.
- `sinustdd_green()`: Validate green transition.
- `sinustdd_refactor()`: Transition to refactor phase.
- `sinustdd_complete()`: Finalize cycle and seal proof.
- `sinustdd_guard_status()`: Report the enforced phase and guarded paths (`readOnlyHint=True`).
- `sinustdd_guard_explain(path)`: Explain why a path is read-only (`readOnlyHint=True`).
- `sinustdd_guard_recover()`: Re-materialize the capabilities of the active cycle phase.

### Workspace guard backends

The guard materializes phase capabilities in the working tree: production is read-only
during RED, and the witnessed RED contract is read-only during GREEN.

| Backend | Selected when | Enforcement |
| --- | --- | --- |
| `posix-permissions` | POSIX filesystem (default) | Clears write bits, restoring original modes on completion |
| `advisory` | Windows or sandboxed mounts | Declares and explains the freeze; the engine's diff invariants stay binding |

Set `SINUSTDD_GUARD` to `posix`, `advisory`, or `off` to override the default.
Enforcement state lives in `.sinustdd/workspace-guard-state.json` and is an operational
cursor, not causal evidence: `sinustdd guard recover` rebuilds it from the active cycle.

---

## License

MIT © Franklin Silveira Baldo
