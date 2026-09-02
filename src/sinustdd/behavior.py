"""Behavioral Intent, BDD Scenario modeling, and BDD -> TDD Compiler."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field


class BehaviorIntent(BaseModel):
    """Raw high-level behavioral intention formulated by human or agent."""

    feature: str
    description: str
    target_module: str = ""
    rationale: str = ""


class BehaviorScenario(BaseModel):
    """Structured, language-agnostic BDD scenario with falsifiable contracts."""

    name: str
    context: list[str] = Field(default_factory=list)  # Given / Preconditions
    action: str  # When / Stimulus
    expected_outcomes: list[str] = Field(default_factory=list)  # Then / Observable changes
    forbidden_outcomes: list[str] = Field(default_factory=list)  # Negative boundaries
    preserved_invariants: list[str] = Field(default_factory=list)  # Regression guards
    counterexamples: list[str] = Field(default_factory=list)  # Smallest falsifying examples


class TestCandidate(BaseModel):
    """A generated or mapped test candidate fulfilling a behavioral requirement."""

    __test__ = False
    test_id: str
    suggested_file: str
    kind: str = "primary_red"  # primary_red | regression_guard | counterexample
    scenario_ref: str
    code_skeleton: str = ""


class TestPlan(BaseModel):
    """Compilation output: mapped test candidates ready for SinusTDD causal proof."""

    __test__ = False
    feature: str
    adapter_name: str
    primary_red_candidates: list[TestCandidate] = Field(default_factory=list)
    regression_guards: list[TestCandidate] = Field(default_factory=list)
    uncovered_scenarios: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SocraticQuestion:
    """Socratic inquiry guiding behavior specification without Gherkin jargon."""

    prompt: str
    target_field: str
    example: str


SOCRATIC_QUESTIONS: list[SocraticQuestion] = [
    SocraticQuestion(
        prompt="O que você quer que seja observavelmente diferente no sistema?",
        target_field="expected_outcomes",
        example="Quando o token expira, a chamada retorna HTTP 401 Unauthorized",
    ),
    SocraticQuestion(
        prompt="Em que situação ou pré-condição exata isso acontece?",
        target_field="context",
        example="Um token com assinatura JWT válida, mas com claim 'exp' no passado",
    ),
    SocraticQuestion(
        prompt="Qual estímulo ou ação dispara essa observação?",
        target_field="action",
        example="O cliente faz uma requisição passando esse token no header Authorization",
    ),
    SocraticQuestion(
        prompt="Qual resultado parecido NÃO deve acontecer de jeito nenhum?",
        target_field="forbidden_outcomes",
        example="Retornar HTTP 500 Internal Server Error ou aceitar o token silenciosamente",
    ),
    SocraticQuestion(
        prompt="Que comportamento existente deve continuar estritamente verdadeiro?",
        target_field="preserved_invariants",
        example="Tokens legítimos não expirados continuam sendo aceitos com HTTP 200",
    ),
    SocraticQuestion(
        prompt="Qual seria o menor contraexemplo que demonstraria que a solução está errada?",
        target_field="counterexamples",
        example="Um token expirado há 1 segundo ser aceito como válido",
    ),
]


def elicit_socratic_prompts() -> list[dict[str, str]]:
    """Return the interactive socratic questionnaire for agent/user elicitation."""
    return [
        {
            "prompt": q.prompt,
            "field": q.target_field,
            "example": q.example,
        }
        for q in SOCRATIC_QUESTIONS
    ]


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text).lower().strip()
    return re.sub(r"[-\s]+", "_", cleaned)


def compile_behavior_to_tdd(
    intent: BehaviorIntent,
    scenarios: list[BehaviorScenario],
    adapter_name: str = "pytest",
    existing_tests: list[str] | None = None,
) -> TestPlan:
    """Compile abstract BDD behavior scenarios into actionable, falsifiable TDD test candidates.

    Deduplicates against already covered baseline tests and targets the primary Red gap.
    """
    known_tests = set(existing_tests or [])
    primary_reds: list[TestCandidate] = []
    regression_guards: list[TestCandidate] = []
    uncovered: list[str] = []

    target_mod_slug = _slugify(intent.target_module or intent.feature)
    test_file = f"tests/test_{target_mod_slug}.py"

    for sc in scenarios:
        scenario_slug = _slugify(sc.name)
        primary_test_id = f"test_{scenario_slug}"

        # 1. Primary Red Candidate
        if primary_test_id not in known_tests:
            skeleton = (
                f"def {primary_test_id}():\n"
                f"    # Scenario: {sc.name}\n"
                f"    # Action: {sc.action}\n"
                f"    # Expected: {', '.join(sc.expected_outcomes)}\n"
                f"    raise NotImplementedError('Behavior Red Witness pending implementation')\n"
            )
            primary_reds.append(
                TestCandidate(
                    test_id=primary_test_id,
                    suggested_file=test_file,
                    kind="primary_red",
                    scenario_ref=sc.name,
                    code_skeleton=skeleton,
                )
            )
            uncovered.append(sc.name)

        # 2. Preserved Invariant Regression Guards
        for inv in sc.preserved_invariants:
            inv_slug = _slugify(inv)
            guard_id = f"test_preserves_{inv_slug}"
            if guard_id not in known_tests:
                guard_skeleton = f"def {guard_id}():\n    # Regression guard: {inv}\n    pass\n"
                regression_guards.append(
                    TestCandidate(
                        test_id=guard_id,
                        suggested_file=test_file,
                        kind="regression_guard",
                        scenario_ref=sc.name,
                        code_skeleton=guard_skeleton,
                    )
                )

    return TestPlan(
        feature=intent.feature,
        adapter_name=adapter_name,
        primary_red_candidates=primary_reds,
        regression_guards=regression_guards,
        uncovered_scenarios=uncovered,
        metadata={"total_scenarios": len(scenarios)},
    )
