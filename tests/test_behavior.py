from __future__ import annotations

from sinustdd.behavior import (
    BehaviorIntent,
    BehaviorMode,
    BehaviorScenario,
    compile_behavior_to_tdd,
    compile_behavior_to_test_specs,
    elicit_socratic_prompts,
)


def test_behavior_mode_options() -> None:
    assert BehaviorMode.OFF == "off"
    assert BehaviorMode.ASSIST == "assist"
    assert BehaviorMode.REQUIRED == "required"


def test_socratic_prompts_structure() -> None:
    prompts = elicit_socratic_prompts()
    assert len(prompts) == 6
    fields = [p["field"] for p in prompts]
    assert "expected_outcomes" in fields
    assert "context" in fields
    assert "forbidden_outcomes" in fields
    assert "counterexamples" in fields


def test_compile_behavior_to_test_specs_agnostic() -> None:
    intent = BehaviorIntent(
        feature="Token Expiration",
        description="Reject expired tokens while preserving valid tokens",
        target_module="auth",
    )

    scenario = BehaviorScenario(
        name="Expired token is rejected",
        context=["A signed token with exp in the past"],
        action="Authentication attempt with expired token",
        expected_outcomes=["HTTP 401 Unauthorized"],
        forbidden_outcomes=["HTTP 200 OK"],
        preserved_invariants=["Valid non-expired token is accepted"],
        counterexamples=["Token expired 1 second ago"],
    )

    specs = compile_behavior_to_test_specs(intent, [scenario])
    assert len(specs) == 2
    primary = specs[0]
    assert primary.spec_id == "spec_expired_token_is_rejected"
    assert primary.target_unit == "auth"
    assert primary.then == ["HTTP 401 Unauthorized"]
    assert primary.then_not == ["HTTP 200 OK"]
    assert not primary.is_regression_guard

    guard = specs[1]
    assert guard.is_regression_guard
    assert "guard_valid_non_expired_token_is_accepted" in guard.spec_id


def test_adapter_planners_multi_ecosystem() -> None:
    intent = BehaviorIntent(
        feature="Token Expiration",
        description="Reject expired tokens",
        target_module="auth",
    )
    scenario = BehaviorScenario(
        name="Expired token is rejected",
        context=["Expired token"],
        action="Login attempt",
        expected_outcomes=["Error 401"],
        forbidden_outcomes=["Success 200"],
    )

    # 1. Pytest Planner
    plan_py = compile_behavior_to_tdd(intent, [scenario], adapter_name="pytest")
    assert plan_py.adapter_name == "pytest"
    assert len(plan_py.materialized_tests) == 1
    t_py = plan_py.materialized_tests[0]
    assert t_py.target_file == "tests/test_auth.py"
    assert "def test_spec_expired_token_is_rejected()" in t_py.code_template
    assert "NotImplementedError" not in t_py.code_template

    # 2. Vitest Planner
    plan_ts = compile_behavior_to_tdd(intent, [scenario], adapter_name="vitest")
    assert plan_ts.adapter_name == "vitest"
    t_ts = plan_ts.materialized_tests[0]
    assert t_ts.target_file == "tests/auth.test.ts"
    assert "test('Expired token is rejected', () => {" in t_ts.code_template

    # 3. Cargo Planner
    plan_rs = compile_behavior_to_tdd(intent, [scenario], adapter_name="cargo")
    assert plan_rs.adapter_name == "cargo"
    t_rs = plan_rs.materialized_tests[0]
    assert t_rs.target_file == "tests/auth_test.rs"
    assert "#[test]" in t_rs.code_template
    assert "fn test_spec_expired_token_is_rejected()" in t_rs.code_template
