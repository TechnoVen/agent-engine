# ADR-016: Single Execution Kernel Invariant

> **Status:** Accepted  
> **Date:** 2026-09-18  
> **Author:** Architecture Working Group / Antigravity  
> **Deciders:** Nadir (Product Owner), CTO  
> **Task Reference:** `R0.5`, `R1.3`, `R4.1`  
> **Supersedes:** Legacy fragmented execution paths; amends ADR-012 and ADR-015

---

## 1. Context & Problem Statement

During the legacy implementation phases (Phases 0 through 7), multiple divergent execution paths emerged across the codebase:
1. **Chat & DSPy Execution:** Handled via direct calls to DSPy modules and local adapters.
2. **Phase 7 Workflow Execution:** Implemented in `WorkflowRuntime.execute_node()` using an in-memory synchronous loop that simulated node execution with mock strings and fabricated cost telemetry (`$0.001`, `$0.0005`, `$0.002`).
3. **Swarm Coordinator:** Ran detached async sleep loops with simulated multi-agent handoffs.
4. **Tool & MCP Execution:** Handled via standalone FastMCP or direct Python functions without universal budget or policy checks.

This divergence violated core system guarantees:
- Security policies and approval gates could be bypassed by invoking alternative execution runtimes.
- Telemetry was inconsistent, with some paths recording real metrics and others fabricating numbers.
- Cancellation ("Stop") in the UI halted some components while leaving background workers running.
- Interrupted executions could not be uniformly recovered after application restarts.

---

## 2. Decision Drivers

- **Single Point of Governance:** All model and tool invocations must enforce identical security policies, approval gates, budget ceilings, and telemetry logging.
- **Truthful Telemetry Invariant:** The system must never claim work succeeded or fabricate token/cost telemetry when real execution did not occur.
- **Durable Lifecycle & Cancellation:** Workflows, jobs, and sessions must share a single, verifiable state machine with cooperative cancellation tokens and restart durability.
- **Asset Preservation (KEEP → INTEGRATE):** Preserve the valuable Phase 7 visual authoring assets (SVG canvas, drag-and-drop, Kahn's algorithm cycle detection, YAML serialization) while eliminating the simulated execution runner.

---

## 3. Considered Options

1. **Option 1: Multi-Kernel Architecture (Legacy Status Quo)**
   - Keep a separate runtime for chat, a separate runtime for DAG workflows, and a separate runtime for multi-agent swarms.
   - *Rejected:* Causes logic duplication, inconsistent safety enforcement, untracked costs, and untruthful telemetry.
2. **Option 2: Complete Rewrite of Workflow and Swarm Systems**
   - Discard Phase 7 and start fresh.
   - *Rejected:* Violates CTO directives and wastes substantial working frontend, parser, and persistence assets.
3. **Option 3: Single Execution Kernel with Layered Adapters (Chosen)**
   - Establish `ExecutionCoordinator` as the sole authoritative execution engine.
   - Retain the Phase 7 UI canvas and DAG parser as the **authoring surface**.
   - Map workflow nodes, DSPy calls, and agent tasks into canonical `ExecutionRequest` payloads processed through the single 10-step execution pipeline.

---

## 4. Decision Outcome

Chosen option: **Option 3 (Single Execution Kernel with Layered Adapters)**.

### 4.1 Invariant Rules
1. **Universal Invocation Funnel:** No production code may directly invoke an LLM provider, external tool, or shell command without submitting an `ExecutionRequest` to `ExecutionCoordinator`.
2. **Canonical 10-Step Pipeline:** Every execution unconditionally undergoes:
   `Context Assembly` → `Policy Verification` → `Budget Authorization` → `Model Routing` → `Approval Gate (if consequential)` → `Dispatch` → `Event Streaming` → `Output Verification` → `Telemetry Ledger Write` → `Terminal State Resolution`.
3. **Decoupled Workflow Semantics:** Visual positioning (`position: {x, y}`) is relegated to non-semantic layout metadata (`layout: {position: {x, y}}`). Workflow execution semantics depend strictly on DAG edges and node dependencies.
4. **Disambiguation of Gates and Parallelism:**
   - **Branching Decision Gate (`ApprovalTask`):** Represents a workflow user choice (e.g. "Select Option A or Option B").
   - **Security Authorization Gate (`ApprovalService`):** Requires cryptographic SHA-256 argument hashing and replay-protected approval tokens before executing protected tools.
   - **Workflow Parallelism (`WorkflowNodeType.PARALLEL`):** Represents concurrent branches within a single DAG, joined by a `MERGE` node and executed as durable background jobs.
   - **Team Parallelism (`SwarmCoordinator`):** Represents autonomous child specialist executions orchestrated by `ExecutionCoordinator`.

---

## 5. Consequences & Trade-offs

### Positive
- **Guaranteed Security:** No execution can bypass the security policy or approval boundary.
- **Truthful Telemetry:** 100% of token usage and costs are either upstream-reported or explicitly flagged as estimates.
- **Universal Cancellation:** A single cancellation token reliably terminates parent workflows, child jobs, and in-flight HTTP/socket connections.
- **Clean Separation of Concerns:** UI authors focus on canvas ergonomics; runtime engineers focus on kernel durability.

### Negative / Mitigations
- **Migration Effort in Stage R4:** Phase 7 `WorkflowRuntime.execute_node()` must be refactored to dispatch through `ExecutionCoordinator`.
- **Mitigation:** The Phase 7 DAG parser, topological sorting, and YAML serializers remain untouched; only the leaf node dispatch function is rewired.

---

## 6. Compliance & Verification

- **Architecture Boundary Tests (`tests/architecture/test_kernel_invariants.py`):** Static analysis and pytest fixtures asserting that no module outside `core/execution/` imports or calls LLM provider SDKs or subshell execution directly.
- **Telemetry Audit Tests (`tests/behavior/execution/test_telemetry_truth.py`):** Assert that all completed execution records contain non-null telemetry with zero hardcoded mock values.
