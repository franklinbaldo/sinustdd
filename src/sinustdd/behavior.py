"""Behavioral Intent, BDD Scenario modeling, TestSpec contracts, and Adapter Planners."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field


class BehaviorMode(StrEnum):
    """Configuration for Behavioral/BDD specification requirement."""

    OFF = "off"  # Default: Pure TDD direct flow without BDD requirement
    ASSIST = "assist"  # Socratic questionnaire & TestSpec compiler available as advisory
    REQUIRED = "required"  # Enforces a valid TestSpec before starting TDD cycle


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


class TestSpec(BaseModel):
    """Language-agnostic falsifiable test specification (No code, pure contract)."""

    spec_id: str
    scenario_ref: str
    target_unit: str
    given: list[str]
    when: str
    then: list[str]
    then_not: list[str] = Field(default_factory=list)
    counterexample: str = ""
    is_regression_guard: bool = False


class MaterializedTest(BaseModel):
    """A concrete, idiomatically rendered test file and symbol for an ecosystem."""

    __test__ = False
    spec_ref: str
    test_id: str
    target_file: str
    code_template: str
    kind: str = "primary_red"  # primary_red | regression_guard


class TestPlan(BaseModel):
    """Compilation output mapping TestSpecs to materialized tests across adapters."""

    __test__ = False
    feature: str
    adapter_name: str
    specs: list[TestSpec] = Field(default_factory=list)
    materialized_tests: list[MaterializedTest] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text).lower().strip()
    return re.sub(r"[-\s]+", "_", cleaned)


# ---------------------------------------------------------------------------
# Ecosystem Test Planners (pytest, vitest, cargo)
# ---------------------------------------------------------------------------


class AdapterPlanner(Protocol):
    def plan_test(self, spec: TestSpec) -> MaterializedTest: ...


class PytestPlanner:
    def plan_test(self, spec: TestSpec) -> MaterializedTest:
        fn_name = f"test_{_slugify(spec.spec_id)}"
        target_file = f"tests/test_{_slugify(spec.target_unit)}.py"

        assertions = "\n".join(
            f"    # Expect: {outcome}\n    # assert <actual> == {outcome}" for outcome in spec.then
        )
        forbidden = "\n".join(
            f"    # Forbidden: {bad}\n    # assert <actual> != {bad}" for bad in spec.then_not
        )

        template = (
            f"def {fn_name}() -> None:\n"
            f'    """Scenario: {spec.scenario_ref}\n'
            f"    Given: {', '.join(spec.given)}\n"
            f"    When: {spec.when}\n"
            f'    """\n'
            f"{assertions}\n"
        )
        if forbidden:
            template += f"{forbidden}\n"

        return MaterializedTest(
            spec_ref=spec.spec_id,
            test_id=fn_name,
            target_file=target_file,
            code_template=template,
            kind="regression_guard" if spec.is_regression_guard else "primary_red",
        )


class VitestPlanner:
    def plan_test(self, spec: TestSpec) -> MaterializedTest:
        suite_name = spec.target_unit or "feature"
        target_file = f"tests/{_slugify(suite_name)}.test.ts"
        test_title = spec.scenario_ref

        assertions = "\n".join(
            f"    // Expect: {outcome}\n    // expect(actual).toBe({outcome});"
            for outcome in spec.then
        )

        template = (
            f"test('{test_title}', () => {{\n"
            f"  // Given: {', '.join(spec.given)}\n"
            f"  // When: {spec.when}\n"
            f"{assertions}\n"
            f"}});\n"
        )

        return MaterializedTest(
            spec_ref=spec.spec_id,
            test_id=test_title,
            target_file=target_file,
            code_template=template,
            kind="regression_guard" if spec.is_regression_guard else "primary_red",
        )


class CargoPlanner:
    def plan_test(self, spec: TestSpec) -> MaterializedTest:
        mod_name = _slugify(spec.target_unit or "feature")
        fn_name = f"test_{_slugify(spec.spec_id)}"
        target_file = f"tests/{mod_name}_test.rs"

        assertions = "\n".join(
            f"    // Expect: {outcome}\n    // assert_eq!(actual, {outcome});"
            for outcome in spec.then
        )

        template = (
            f"#[test]\n"
            f"fn {fn_name}() {{\n"
            f"    // Given: {', '.join(spec.given)}\n"
            f"    // When: {spec.when}\n"
            f"{assertions}\n"
            f"}}\n"
        )

        return MaterializedTest(
            spec_ref=spec.spec_id,
            test_id=fn_name,
            target_file=target_file,
            code_template=template,
            kind="regression_guard" if spec.is_regression_guard else "primary_red",
        )


_PLANNERS: dict[str, type] = {
    "pytest": PytestPlanner,
    "vitest": VitestPlanner,
    "cargo": CargoPlanner,
}


def get_planner(adapter_name: str) -> AdapterPlanner:
    planner_cls = _PLANNERS.get(adapter_name.lower(), PytestPlanner)
    return planner_cls()


# ---------------------------------------------------------------------------
# Socratic Questionnaire
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SocraticQuestion:
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


# ---------------------------------------------------------------------------
# Behavior -> TestSpec -> TestPlan Compiler
# ---------------------------------------------------------------------------


def compile_behavior_to_test_specs(
    intent: BehaviorIntent,
    scenarios: list[BehaviorScenario],
) -> list[TestSpec]:
    """Compile behavioral scenarios into declarative, language-agnostic TestSpecs."""
    specs: list[TestSpec] = []
    target_mod = intent.target_module or intent.feature

    for sc in scenarios:
        # Primary Spec
        primary_spec = TestSpec(
            spec_id=f"spec_{_slugify(sc.name)}",
            scenario_ref=sc.name,
            target_unit=target_mod,
            given=sc.context,
            when=sc.action,
            then=sc.expected_outcomes,
            then_not=sc.forbidden_outcomes,
            counterexample=sc.counterexamples[0] if sc.counterexamples else "",
            is_regression_guard=False,
        )
        specs.append(primary_spec)

        # Invariant Regression Guard Specs
        for inv in sc.preserved_invariants:
            guard_spec = TestSpec(
                spec_id=f"guard_{_slugify(inv)}",
                scenario_ref=sc.name,
                target_unit=target_mod,
                given=[f"Preserved invariant: {inv}"],
                when="Standard operation",
                then=[inv],
                is_regression_guard=True,
            )
            specs.append(guard_spec)

    return specs


def compile_behavior_to_tdd(
    intent: BehaviorIntent,
    scenarios: list[BehaviorScenario],
    adapter_name: str = "pytest",
) -> TestPlan:
    """Compile abstract BDD behavior scenarios into ecosystem-idiomatic MaterializedTests."""
    specs = compile_behavior_to_test_specs(intent, scenarios)
    planner = get_planner(adapter_name)
    materialized = [planner.plan_test(sp) for sp in specs]

    return TestPlan(
        feature=intent.feature,
        adapter_name=adapter_name,
        specs=specs,
        materialized_tests=materialized,
        metadata={"total_scenarios": len(scenarios), "total_specs": len(specs)},
    )
