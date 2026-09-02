from __future__ import annotations

from sinustdd.behavior import (
    BehaviorIntent,
    BehaviorScenario,
    compile_behavior_to_tdd,
    elicit_socratic_prompts,
)


def test_socratic_prompts_structure() -> None:
    prompts = elicit_socratic_prompts()
    assert len(prompts) == 6
    fields = [p["field"] for p in prompts]
    assert "expected_outcomes" in fields
    assert "context" in fields
    assert "forbidden_outcomes" in fields
    assert "counterexamples" in fields


def test_compile_behavior_to_tdd_gap_detection() -> None:
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
        forbidden_outcomes=["HTTP 200 OK", "HTTP 500 Error"],
        preserved_invariants=["Valid non-expired token is accepted"],
        counterexamples=["Token expired 1 second ago"],
    )

    # 1. Compilation without baseline tests (full gap)
    plan = compile_behavior_to_tdd(intent, [scenario], adapter_name="pytest")
    assert plan.feature == "Token Expiration"
    assert len(plan.primary_red_candidates) == 1
    assert plan.primary_red_candidates[0].test_id == "test_expired_token_is_rejected"
    assert plan.primary_red_candidates[0].suggested_file == "tests/test_auth.py"
    assert len(plan.regression_guards) == 1
    assert "test_preserves_valid_non_expired_token_is_accepted" in plan.regression_guards[0].test_id

    # 2. Compilation with baseline existing test (gap closed)
    plan_covered = compile_behavior_to_tdd(
        intent,
        [scenario],
        adapter_name="pytest",
        existing_tests=["test_expired_token_is_rejected"],
    )
    assert len(plan_covered.primary_red_candidates) == 0
    assert len(plan_covered.uncovered_scenarios) == 0
