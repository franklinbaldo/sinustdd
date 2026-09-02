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

- `models.py` — phases, cycles, transitions and witness models;
- `evidence.py` — OKF evidence emission, hash chaining and validation;
- `store.py` — ephemeral active-session persistence;
- `diff.py` — repository diff classification;
- `runner.py` — test execution and failure fingerprint extraction;
- `engine.py` — transition validation;
- `cli.py` — `begin`, `red`, `green`, `refactor`, `complete`, and `status`.

## Installation

```bash
uv add sinustdd
```

```bash
sinustdd info
```

## License

MIT © Franklin Silveira Baldo
