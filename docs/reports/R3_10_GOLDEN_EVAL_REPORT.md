# Agent Engine R3.10 Golden Evaluation Report

> **Generated:** 2026-10-30T13:41:52.914102+00:00  
> **Evaluator Version:** `v1_golden_eval`  
> **Governing Task:** Milestone R3 Task R3.10 (Chain-Level Model Economics & Cost-Per-Success)  

---

## 1. Mathematical Thesis & Proven Proof

**Empirical Finding:** Cheap model ($0.005/call) has higher whole-chain cost per verified success ($0.030) than reliable model ($0.018/call -> $0.018) due to failure retries and expensive fallback.

| Route Profile | Initial Model | Attempt Cost | Whole-Chain Cost-Per-Success | Evidence Status |
|---|---|---|---|---|
| **Reliable Route** | `anthropic:claude-3-5-sonnet` | $0.0180 | **$0.0180** | `SUFFICIENT_EVIDENCE` |
| **Unreliable Cheap Route** | `cheap_cloud:mini-model` | $0.0050 | **$0.0300** | `SUFFICIENT_EVIDENCE` |

**Conclusion:** The cheap initial model incurs retries and expensive fallback, resulting in a **66.7% higher Cost-Per-Success ($0.030 vs $0.018)** than routing directly to the reliable model.

---

## 2. Comprehensive Cohort Economics Ledger

| Initial Model Cohort | Family | Tasks | Atts | Succ / Fail / Part / Unk | Total Spend | Mean Task | Observed CPS | Expected CPS | Status |
|---|---|---|---|---|---|---|---|---|---|
| `anthropic:claude-3-5-sonnet` | coding | 5 | 5 | 5s / 0f / 0p / 0u | $0.0900 | $0.0180 | $0.0180 | $0.0180 | `SUFFICIENT_EVIDENCE` |
| `broken_cloud:broken-model` | coding | 5 | 5 | 0s / 5f / 0p / 0u | $0.0500 | $0.0100 | None | None | `NO_SUCCESS_EVIDENCE` |
| `cheap_cloud:mini-model` | coding | 5 | 15 | 5s / 0f / 0p / 0u | $0.1500 | $0.0300 | $0.0300 | $0.0300 | `SUFFICIENT_EVIDENCE` |
| `experimental:new-model` | coding | 2 | 2 | 2s / 0f / 0p / 0u | $0.0240 | $0.0120 | $0.0120 | None | `INSUFFICIENT_EVIDENCE` |
| `human_test:hallucinating-model` | coding | 5 | 5 | 0s / 5f / 0p / 0u | $0.0750 | $0.0150 | None | None | `NO_SUCCESS_EVIDENCE` |
| `local:qwen2.5-coder-free` | coding | 5 | 5 | 5s / 0f / 0p / 0u | $0.0000 | $0.0000 | $0.0000 | $0.0000 | `SUFFICIENT_EVIDENCE` |
| `partial_cloud:truncated-model` | coding | 5 | 5 | 0s / 0f / 5p / 0u | $0.0400 | $0.0080 | None | None | `NO_SUCCESS_EVIDENCE` |
| `unverified_cloud:opaque-model` | coding | 5 | 5 | 0s / 0f / 0p / 5u | $0.0350 | $0.0070 | None | None | `NO_SUCCESS_EVIDENCE` |

---

## 3. Evaluated Scenario Invariants

1. **Reliable Expensive Route:** 5 tasks, 5 attempts, 5 successes, 0 retries. Total spend = $0.090. CPS = $0.018.
2. **Unreliable Cheap Route:** 5 tasks, 15 attempts (5 initial cheap + 5 retries cheap + 5 fallback expensive). Total spend = $0.150. CPS = $0.030.
3. **Cheap Reliable Route (Local):** 5 tasks, 5 attempts, 5 successes, 100% free ($0.000). CPS = $0.0000.
4. **Zero-Success Cohort:** 5 tasks, 5 failures ($0.050 spend). Observed CPS = None, Expected CPS = None (`NO_SUCCESS_EVIDENCE`). No division by zero/epsilon.
5. **Insufficient Evidence Cohort:** 2 tasks (< 5 threshold). Status = `INSUFFICIENT_EVIDENCE`. Falls back cleanly to catalog pricing.
6. **Partial Outcome Cohort:** 5 tasks with `PARTIAL` outcome (e.g. context/token truncation). Counted as partial, not success.
7. **Unknown Outcome Cohort:** 5 tasks with `UNKNOWN` outcome. Status = `NO_SUCCESS_EVIDENCE` / `INSUFFICIENT_EVIDENCE`. Never creates false success.
8. **Human Corrected Cohort:** Explicit human rejection (`USER_EXPLICIT_REJECT`) overrides initial completion to `FAILURE`. Recorded in `known_correction_count`.
