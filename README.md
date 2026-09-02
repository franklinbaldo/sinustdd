# sinustdd 🌊

> **Sinusoidal TDD Harmonic State Machine for Autonomous Coding Agents**

`sinustdd` is an opinionated verification and orchestration protocol for proving that a test became red before production code made it green.

## Causal TDD cycle

The sinusoid is a representation of a discrete causal state machine. The state machine is authoritative; the wave makes the cycle legible.

### BASELINE (θ = 0)

The cycle starts from a repository snapshot `B` with a green test suite. The baseline records the Git reference and the known passing behavior before the oscillation begins.

### RED (θ ∈ [0, π])

Two rigid invariants apply:

1. `production_diff(B, R) == ∅` — production code may not change.
2. At least one new test must demonstrably fail against production baseline `B`.

Crossing into Green requires a **Red Witness** containing the exact test identity, baseline reference, failure output and a stable failure fingerprint.

### GREEN (θ ∈ [π, 2π])

The Red tests become the frozen target. Production code may now change, but the behavioral target recorded by Red may not be weakened.

A **Green Witness** is emitted only when the Red witness passes and all tests that were passing at baseline continue to pass.

### REFACTOR (θ = 2π)

Refactor may change production structure and test/fixture organization while preserving the behavior demonstrated by the complete known test and witness set. `sinustdd` does not claim universal program equivalence; it proves preservation relative to the observable contract it has recorded.

After the Refactor witness is accepted, `2π ≡ 0` and the next cycle may begin.

## Automatic observer mode

The preferred agent integration is passive. An agent should not need to call `sinustdd red` or `sinustdd green` at every step.

In **observer mode**, `sinustdd` continuously derives the most likely harmonic phase from objective repository events:

- Git tree and working-tree changes;
- classification of test, fixture and production diffs;
- hashes of the test targets captured at Red;
- pytest collection and outcomes;
- the existing OKF evidence chain.

A typical trajectory is inferred as follows:

```text
all tests green + clean baseline
            │
            ▼
       BASELINE witness
            │
new/changed test + no production change
            │
            ▼
failing new test against B ─────► RED witness
            │
production changes + Red target frozen
            │
            ▼
Red target + baseline suite green ─► GREEN witness
            │
structure changes + behavior stays green
            │
            ▼
       REFACTOR witness
            │
            └──────────────► next cycle
```

The observer follows a **silence-on-success** contract: valid phase changes are recorded automatically as OKF evidence without interrupting the coding agent. The agent is notified only when `sinustdd` can demonstrate a protocol violation or when continued inference is impossible without an explicit decision.

Examples of hard violations include:

- production code changes before a Red witness exists;
- a Red test is changed or weakened after its witness was captured;
- a claimed Green state does not make the Red target pass;
- a previously passing baseline test regresses;
- an existing evidence artifact is rewritten and breaks the hash chain.

Ambiguity is not itself a violation. When several phases remain compatible with the observed events, the observer keeps collecting evidence rather than guessing intent.

### Notification adapters

Violations are emitted as structured events rather than coupled to one agent runtime:

```text
ViolationEvent
├── code
├── cycle_id
├── inferred_phase
├── expected_invariant
├── observed_evidence
├── evidence_path
└── suggested_recovery
```

The core exposes callbacks/subscribers for these events. Adapters may map them to a local callback, hook output, MCP notification, agent `send_message` facility, CI annotation, or another orchestration channel. The protocol core records evidence and detects violations; delivery remains an adapter concern.

This makes the normal experience intentionally quiet: **observe, prove, persist; interrupt only on violation.**

## Evidence is part of the repository

Every phase transition emits durable evidence. Evidence is not hidden in an agent session or an external database: by default it is authored as an **Open Knowledge Format (OKF)** Markdown concept and stored in the repository.

```text
.sinustdd/
├── session.json                 # ephemeral operational cursor; not evidence
└── evidence/
    └── <cycle-id>/
        ├── baseline.md
        ├── red.md
        ├── green.md
        └── refactor.md
```

The evidence bundle is validated with `okf-parser` at write time. Each evidence concept contains the repository ref, cycle/phase identity, witness payload, its SHA-256 digest, and the digest of the previous phase evidence. This gives each cycle an append-only, Git-versioned causal chain.

The JSON session file is only a resumable cursor for the currently active cycle. A cycle is auditable from the OKF evidence committed to the repository even after the agent session disappears.

## Runtime shape

The initial runtime is organized around:

- `models.py` — phases, cycles, transitions, witnesses and violation events;
- `evidence.py` — OKF evidence emission, hash chaining and validation;
- `store.py` — ephemeral active-session persistence;
- `diff.py` — repository diff classification;
- `runner.py` — test execution and failure fingerprint extraction;
- `engine.py` — explicit transition validation;
- `observer.py` — automatic phase inference and violation detection;
- `notifications.py` — callback/subscriber boundary for violation delivery;
- `cli.py` — explicit commands plus `watch`/observer entry points.

The explicit CLI remains useful for CI, debugging and deterministic orchestration, but autonomous agents should normally run under observer mode.

## Installation

```bash
uv add sinustdd
```

```bash
sinustdd info
```

## License

MIT © Franklin Silveira Baldo
