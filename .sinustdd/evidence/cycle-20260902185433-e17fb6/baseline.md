---
type: SinusTddEvidence
title: "cycle-20260902185433-e17fb6 baseline witness"
description: "Causal TDD evidence for baseline phase"
cycle_id: "cycle-20260902185433-e17fb6"
phase: "baseline"
repository_ref: "3688c388dd4165122906f475b08fbfb66f789dc8"
sha256: "a444a2490f5d4ec7b941f8a22477386a96444ed72c410138f9277b219f79817b"
---

# Baseline witness

This document is repository evidence emitted by sinustdd.

```json
{
  "baseline_commit": "3688c388dd4165122906f475b08fbfb66f789dc8",
  "recorded_at": "2026-09-02 18:54:33.674109+00:00",
  "suite_fingerprint": "01a6627f16d188c8e39f8cf0462d059965ecf2f1616185fdc78b902007e1ecae",
  "tests_passed": [
    "tests/test_adapters.py::test_pytest_adapter_detection",
    "tests/test_adapters.py::test_vitest_adapter_detection",
    "tests/test_adapters.py::test_pytest_adapter_run_tests_parsing",
    "tests/test_adapters.py::test_vitest_adapter_run_tests_parsing",
    "tests/test_adversarial_gates.py::test_adversarial_baseline_already_failing",
    "tests/test_adversarial_gates.py::test_adversarial_red_with_production_code",
    "tests/test_adversarial_gates.py::test_adversarial_red_disconnected_failure",
    "tests/test_adversarial_gates.py::test_adversarial_green_tampering_test_assertions",
    "tests/test_basic.py::test_version",
    "tests/test_basic.py::test_cli_info",
    "tests/test_diff_and_runner.py::test_diff_and_git_helpers",
    "tests/test_diff_and_runner.py::test_runner_helpers",
    "tests/test_engine.py::test_engine_lifecycle",
    "tests/test_mcp_and_cli.py::test_cli_commands_coverage",
    "tests/test_mcp_and_cli.py::test_mcp_tools_and_execution",
    "tests/test_observer_and_evidence.py::test_observer_subscription_and_notification",
    "tests/test_observer_and_evidence.py::test_write_phase_evidence_and_ledger_verification",
    "tests/test_observer_and_evidence.py::test_observer_observe_once_flows"
  ]
}
```
