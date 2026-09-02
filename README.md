# sinustdd 🌊

> **Sinusoidal TDD Harmonic State Machine for Autonomous Coding Agents**

`sinustdd` is an opinionated verification and orchestration protocol designed to enforce genuine Test-Driven Development (TDD) discipline on AI agents through harmonic phase transitions.

---

## 🌊 The Harmonic TDD Principle

Traditional static assertions (e.g., 100% passing tests continuously) fail with LLM agents because agents often:
1. Write tests and production code simultaneously.
2. Weaken test assertions when a test fails unexpectedly.
3. Skip verifying that a test actually failed before making it pass.

`sinustdd` models TDD as a continuous sinusoidal wave of phase $\theta \in [0, 2\pi]$:

- **🔴 Red Phase ($\theta \in [0, \pi)$):**
  - **Invariance:** $\frac{d(\text{Failures})}{dt} > 0$. New tests are introduced. Production code modifications are locked. Tests MUST fail.
- **🟢 Green Phase ($\theta \in [\pi, 2\pi)$):**
  - **Invariance:** $\frac{d(\text{Passing})}{dt} > 0$ and $\text{Failures} \to 0$. Production code is implemented. Existing test assertions are immutable.
- **🔵 Refactor Phase ($\theta = 2\pi$):**
  - **Invariance:** $\text{Passing} = 100\%$, $\text{Failures} = 0$, with structural and complexity metrics improving without external behavior alteration.

---

## 🚀 Installation & Usage

```bash
uv add sinustdd
```

### CLI
```bash
sinustdd info
```

---

## License

MIT © Franklin Silveira Baldo
