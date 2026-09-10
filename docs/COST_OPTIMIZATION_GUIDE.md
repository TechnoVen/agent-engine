# Agent Engine — Cost Optimization Guide for Gemini

> **Purpose:** This guide must be followed by Gemini (or any AI coding assistant) at **every** implementation decision point in the Agent Engine project. It encodes the cost-cutting strategies from the two source articles (Code Coup's "90% Token Costs" and Prosus's "90% AI Costs") into concrete, enforceable rules. Every task in the Master Implementation Plan must respect this guide. If a task conflicts with this guide, **this guide wins** unless an ADR (Architecture Decision Record) explicitly overrides it.

---

## Part 1 — Core Cost Principles (Non-Negotiable)

These are the laws. Gemini must never violate them without an explicit ADR.

### Law 1 — The 90/9/1 Rule

At every workflow, every pipeline, and every task:

- **90%** of steps must be handled by **deterministic code, caching, or a small local model**.
- **9%** may use a **mid-tier model** (near-frontier, cheap cloud, or medium local).
- **1%** may use a **frontier model** (GPT-4-class, Claude Sonnet-class, Gemini Pro-class).

If a new feature proposes sending more than 10% of steps to frontier models, it must be rejected or redesigned.

### Law 2 — Cost per Completed Task, Not Cost per Token

Never compare models by price-per-million-tokens. Always compare by **cost to successfully complete a real task from your own eval suite**.

Example:
- Model A: $2/M tokens, succeeds 60% of the time, uses 5k tokens → $0.01 per success.
- Model B: $10/M tokens, succeeds 95% of the time, uses 3k tokens → $0.003 per success.

Model B is **cheaper** despite higher token price. The router must always use success-adjusted cost.

### Law 3 — Context Is a Cost Center

Every prompt must include **only what the model needs for this specific step**. No exceptions.

- Average request context target: **< 8,000 tokens** for agent steps.
- Absolute ceiling per request: **configurable, default 32,000 tokens**.
- Anything above triggers a warning and a context-reduction pass.

### Law 4 — Cache Before You Call

If the answer can be produced from a previous result, a deterministic rule, or a lookup table — **do that first**. The model is the last resort, not the first.

### Law 5 — Deterministic by Default

If a step can be expressed as an `if` statement, a regex, a schema lookup, or a database query — it must be code, not a model call.

### Law 6 — Measure Everything

Every model call must log: task type, model used, tokens in, tokens out, cost, latency, success/failure, cache hit/miss. No exceptions.

### Law 7 — Load Balance

Background work (evaluations, batch processing, scheduled agents, report generation) must be scheduled **outside peak hours**. Never let machine work compete with interactive users.

### Law 8 — Distill Repetition

Any task that repeats more than 10,000 times per month is a candidate for distillation into a small specialist model. Distillation is not optional at scale.

---

## Part 2 — The Decision Framework

Every step in every pipeline, workflow, or skill must pass through this decision tree **before** any model is chosen.

```
┌─────────────────────────────────────────────────────────────┐
│              STEP CLASSIFICATION DECISION TREE              │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │ Is the answer knowable  │
              │ from a rule, schema,    │
              │ or deterministic logic? │
              └─────────────────────────┘
                     │            │
                    YES           NO
                     │            │
                     ▼            ▼
         ┌──────────────┐   ┌─────────────────────────┐
         │ RUN AS CODE  │   │ Has this exact input    │
         │ (0 tokens)   │   │ been seen before?       │
         └──────────────┘   └─────────────────────────┘
                                │            │
                               YES           NO
                                │            │
                                ▼            ▼
                        ┌──────────────┐   ┌─────────────────────────┐
                        │ RETURN FROM  │   │ Does the step require   │
                        │ CACHE        │   │ judgment/reasoning?     │
                        │ (0 tokens)   │   └─────────────────────────┘
                        └──────────────┘       │            │
                                              NO            YES
                                               │            │
                                               ▼            ▼
                                       ┌──────────────┐  ┌─────────────────────────┐
                                       │ RUN AS CODE  │  │ Simple classification,  │
                                       │ (0 tokens)   │  │ extraction, or rewrite? │
                                       └──────────────┘  └─────────────────────────┘
                                                              │            │
                                                             YES           NO
                                                              │            │
                                                              ▼            ▼
                                                    ┌──────────────┐  ┌─────────────────────────┐
                                                    │ SMALL LOCAL  │  │ Complex reasoning or    │
                                                    │ MODEL        │  │ ambiguous context?      │
                                                    │ (Gemma/Qwen) │  └─────────────────────────┘
                                                    └──────────────┘       │            │
                                                                          YES           NO
                                                                           │            │
                                                                           ▼            ▼
                                                                  ┌──────────────┐  ┌──────────────┐
                                                                  │ MID-TIER     │  │ FRONTIER     │
                                                                  │ MODEL        │  │ MODEL        │
                                                                  └──────────────┘  └──────────────┘
                                                                                          │
                                                                                          ▼
                                                                                  ┌──────────────┐
                                                                                  │ HUMAN REVIEW │
                                                                                  │ (if critical)│
                                                                                  └──────────────┘
```

### Task-type → Model tier mapping (defaults)

| Task type | Default execution | Rationale |
|---|---|---|
| Check file exists / attachment present | Code | Deterministic |
| Extract email address / phone / IBAN | Regex + parser | Deterministic patterns |
| Validate schema / JSON shape | Pydantic / JSON Schema | Deterministic |
| Compare numbers / thresholds | Code | Deterministic |
| Currency conversion | Code + rate API | Deterministic |
| Route to department by keyword | Code (rules) or small model | Simple classification |
| Classify intent (5–10 classes) | Small local model | Simple reasoning |
| Summarize short document | Small local model | Simple rewrite |
| Rewrite text tone | Small local model | Simple rewrite |
| Extract structured fields from a document | Mid-tier model | Requires context understanding |
| Answer question over provided context (RAG) | Mid-tier model | Requires grounding |
| Multi-step planning / tool selection | Mid-tier or frontier | Complex reasoning |
| Analyze 40-page contract for legal conflicts | Frontier model + human review | High-stakes reasoning |
| Novel architecture design | Frontier model | Complex reasoning |
| Safety-critical policy decision | Code + frontier + human | Layered |

---

## Part 3 — Implementation Patterns

Gemini must use these patterns. Do not invent alternatives.

### Pattern 3.1 — The Execution Router

Every step goes through the router. No pipeline calls a model directly.

```python
# core/router/execution_router.py

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


class ExecutionTier(Enum):
    CODE = "code"
    CACHE = "cache"
    SMALL_MODEL = "small_model"
    MID_MODEL = "mid_model"
    FRONTIER_MODEL = "frontier_model"
    HUMAN = "human"


@dataclass
class StepProfile:
    step_name: str
    is_deterministic: bool = False
    is_cacheable: bool = False
    requires_judgment: bool = False
    complexity: str = "low"  # low | medium | high
    is_high_stakes: bool = False
    fallback_tier: ExecutionTier = ExecutionTier.MID_MODEL
```

### Pattern 3.2 — Deterministic-First Pipelines

Every pipeline must document its 90/9/1 split in a docstring. If the split is violated, the PR is rejected.

### Pattern 3.3 — The Semantic Cache

Chroma-backed semantic cache with similarity threshold 0.95 and TTL per type. Classifications, common Q&A, and extracted metadata are cached.

### Pattern 3.4 — Context Minimization

Every model call must pass through a context builder that:
1. Starts with the step's **minimum required fields**.
2. Adds retrieved context only if the step declares it needs RAG.
3. Truncates to the step's declared token budget (`< 8,000` tokens target, ceiling `32,000`).
4. Logs the final token count.

### Pattern 3.5 — Model Distillation Pipeline

Any task that runs > 10,000 times/month is a distillation candidate into a specialist model.

### Pattern 3.6 — GPU Load Balancer

Interactive tasks run immediately. Background tasks (evals, batch processing, scheduled agents) run off-peak.

---

## Part 4 — Architecture Requirements

| Component | Purpose | Task ID |
|---|---|---|
| **Execution Router** | Classifies every step into CODE/CACHE/SMALL/MID/FRONTIER | 1.1 / 1.10 |
| **Semantic Cache** | Returns cached answers for repeated tasks | 1.7 |
| **Context Builder** | Enforces context budgets per step | 1.8 |
| **Cost Tracker** | Logs cost per completed task, not per token | 1.5 |
| **Model Eval Suite** | Measures success rate and cost-per-success per model per task | 1.9 |
| **Distillation Pipeline** | Converts high-frequency tasks to specialists | 9.3 |
| **Load Balancer** | Schedules background work off-peak | 9.4 |
| **Cost Attribution Dashboard** | Visualizes 90/9/1 breakdown per project | 9.5 |

---

## Part 5 — Enforcement Rules for Gemini

When implementing any task from the Master Plan, Gemini must:

1. **Declare the 90/9/1 split** in the task's docstring. If a task sends > 10% of steps to frontier models, stop and propose a redesign.
2. **Classify every step** with a `StepProfile`. No exceptions.
3. **Use the Execution Router.** Never call `dspy.LM(...)` directly in a pipeline.
4. **Use the Context Builder.** Never pass raw objects to a model.
5. **Use the Semantic Cache.** Before any classification, extraction, or Q&A step, check the cache.
6. **Log cost-per-success**, not just tokens.
7. **Respect peak hours.** Background tasks go off-peak.
8. **Flag distillation candidates.** Any task > 10k/month gets marked.
9. **Reject anti-patterns.** If existing code violates the guide, refactor it in the same PR.
10. **Update the eval suite.** Every new task type must be added to the golden set.

### Anti-patterns to reject on sight

| Anti-pattern | Why it's wrong | Correct approach |
|---|---|---|
| `if model.ask("is this an invoice?")` | Deterministic question sent to a model | `if doc.type == "invoice":` |
| Passing `customer.history` to every prompt | Bloats context 10× | Pass only required fields via ContextSpec |
| Using GPT-4 for intent classification | 50× more expensive than needed | Use small local model |
| No cache on repeated Q&A | Paying for the same answer 1,000 times | Semantic cache |
| Running evals during business hours | Competes with users | Off-peak scheduler |
| Comparing models by token price | Wrong metric | Cost-per-success from eval suite |
| One giant agent for the whole workflow | Reason every step | Decompose into judgment steps |

---

## Part 6 — Metrics Tracked

| Metric | Target | Hard Ceiling |
|---|---|---|
| Average context per request | < 8,000 tokens | 32,000 tokens |
| Cache hit rate | ≥ 30% | — |
| Frontier model share of steps | ≤ 1% | 5% |
| Mid-tier model share | ≤ 9% | 15% |
| Deterministic + cache + small model share | ≥ 90% | 80% |
| Cost per completed task (per task type) | Decreasing trend | No regression > 10% |
| Off-peak background utilization | ≥ 60% | 40% |
| Distillation candidates flagged | 100% | 100% |

---

## Part 7 — Three Questions Asked at Every Task

1. **Are we using a more powerful model than this task requires?**
   → If yes, downgrade the tier or replace with code.
2. **Are we giving it more information than it needs?**
   → If yes, reduce the context via ContextSpec.
3. **Are we buying more computing power than the workload actually uses?**
   → If yes, reschedule, cache, or distill.
