# Phase 7 — Canonical Integration Review & Ground-Truth Audit

> **Status:** Approved Architectural Audit  
> **Author:** Senior Principal Architect / Maintainer  
> **Review Date:** September 18, 2026  
> **Baseline:** Legacy Phase 7 Completion Commit `05f967f`  
> **Authority:** In accordance with the canonical `docs/ROADMAP.md` (Release R0 / Task R0.8) and CTO Review.

---

## 1. Executive Summary

Legacy Phase 7 implemented an end-to-end visual workflow authoring experience comprising an interactive SVG canvas (`Workflows.tsx`), a multi-agent swarm dashboard (`Swarm.tsx`), Pydantic workflow definitions, SQLite persistence, lossless bidirectional YAML round-trip parsing, human-in-the-loop approval gate state management, and 25 unit/integration tests (`tests/test_workflows.py`).

**The primary conclusion of this audit is:**
> **The visual authoring UX, schema definition, DAG validation, YAML serialization, SQLite definition storage, and human approval pause/resume mechanics are high-value product assets that MUST BE PRESERVED and integrated.**  
> However, the current execution runtime (`execute_node()`, `engine.run()`, and `SwarmCoordinator.run_swarm()`) uses simulated mock string outputs and fabricated cost constants. It does not invoke actual LLMs, skills, or sandbox environments, nor does it possess durable background execution, restart recovery, cancellation, or unified security authorization.

In Stage R4 (Durable Jobs + Workflow Convergence), Phase 7 will be **absorbed into the canonical architecture**, moving from an in-memory execution loop to an authoring surface backed by the canonical `ExecutionCoordinator` and a durable job runtime.

---

## 2. Canonical Subsystem Classification

Each workflow component and capability delivered in Phase 7 is classified using the canonical migration codes:

| Component / File | Canonical Destination | Migration Action | Current Maturity | Target Maturity (R4/R5) |
|---|---|---|---|---|
| **Workflow Canvas UI** (`Workflows.tsx`) | Authoring Surface (Screen 5) | **KEEP & EXPAND** | `S2 — Integrated` | `S4 — Release Verified` |
| **Swarm Dashboard UI** (`Swarm.tsx`) | Multi-Agent Dispatch (Screen 4) | **KEEP & INTEGRATE** | `S2 — Integrated` | `S4 — Release Verified` |
| **Workflow Models** (`models.py`) | Domain Schema (`DATA_MODEL.md`) | **INTEGRATE** | `S2 — Integrated` | `S4 — Release Verified` |
| **Parser & Graph Validator** (`parser.py`) | DAG Compiler (`core/workflows/`) | **INTEGRATE** | `S3 — Behavior Verified` | `S4 — Release Verified` |
| **Workflow Definition Storage** (`storage.py`) | Workflow Repository | **INTEGRATE** | `S3 — Behavior Verified` | `S4 — Release Verified` |
| **Approval Gate State Machine** (`gates.py`) | Workflow `ApprovalTask` | **INTEGRATE** | `S3 — Behavior Verified` | `S4 — Release Verified` |
| **Workflow Engine Runtime** (`engine.py`) | `ExecutionCoordinator` + Durable Jobs | **REFACTOR** | `S1 — Implemented (Stub)` | `S4 — Release Verified` |
| **Swarm Dispatch Runtime** (`swarm.py`) | Multi-Agent Team Execution | **REFACTOR** | `S1 — Implemented (Stub)` | `S4 — Release Verified` |
| **Dry Run Mode** (`dry_run=True`) | Static Plan & Permission Analyzer | **EXPAND** | `S2 — Integrated` | `S4 — Release Verified` |

---

## 3. Detailed Ground-Truth Source Code Verification

### 3.1. What Is Real Runtime & Production-Ready

1. **Graph Topological Sorting & Cycle Detection (`parser.py`):**
   - Implements Kahn's algorithm (`get_topological_sort()`).
   - Recursively computes in-degrees, isolates entry nodes, and detects cycles and self-loops (`test_workflow_parser_cycle_detection`, `test_workflow_builder_complex_dag_validation`).
   - Validates node ID uniqueness, edge reference integrity (source/target exist), and non-empty metadata.
2. **Lossless Bidirectional Serialization (`parser.py`, `models.py`):**
   - Bidirectional lossless conversion: `YAML string` $\longleftrightarrow$ `WorkflowDefinition` $\longleftrightarrow$ `JSON dict`.
   - Verified round-trip preserving node attributes, edge conditions, mustache bindings, and custom configuration.
3. **SQLite Definition & Run Storage (`storage.py`):**
   - Real SQLite WAL database tables: `workflow_definitions` and `workflow_runs`.
   - Thread-safe repository pattern, JSON serialization of metadata, tag queries, cascade deletion of runs upon workflow deletion, and automatic seeding of default audit workflow (`wf_code_audit_and_fix`).
4. **Approval Gate State Machine (`gates.py`, `engine.py`):**
   - When a `GATE` node is encountered during execution, the DAG genuinely pauses.
   - Execution status transitions to `waiting_approval`.
   - Run metadata is persisted to SQLite with pending gate input arguments and timeouts.
   - `GET /v1/workflows/gates/pending` correctly queries and returns active pause nodes across all runs.
   - Resumption routes downstream based on operator decision:
     - `approve` $\rightarrow$ activates downstream edges with `condition="approved"`.
     - `reject` $\rightarrow$ activates downstream edges with `condition="false"` (rollback branch).
     - `redirect` $\rightarrow$ reroutes execution to an operator-specified target node with input overrides.
5. **Mustache Variable Binding Engine (`engine.py`):**
   - Regex-based evaluation of `{{step_id.output_field}}` and root variables `$workflow.input.<field>`.
   - Correctly transfers intermediate outputs across topological execution steps.
6. **Desktop Canvas & Interactive Wiring (`Workflows.tsx`):**
   - Draggable nodes with live canvas coordinate updates.
   - Cubic bezier curve SVG edge rendering with arrowhead markers.
   - Port-to-port click wiring from source output handle to target input handle.
   - Dynamic Inspector panel with live JSON input/config editing.
   - YAML import/export modal with copy-to-clipboard and apply-to-canvas functions.

---

### 3.2. What Is Simulated or Stubbed (Must Be Converged in R1–R4)

1. **Simulated Node Execution (`WorkflowEngine.execute_node`):**
   - **`AGENT` Nodes:** Generate canned text templates (`f"Agent response for: {str(prompt)[:60]}..."`) and assign hardcoded cost (`0.002` or `0.0002`). They do **not** invoke LLM providers, execution router, or real inference.
   - **`SKILL` Nodes:** Return mock strings (`f"Executed skill '{skill_id}'"`) and hardcoded cost (`0.0005`). They do **not** invoke `SkillManager` or execute real scripts/binaries.
   - **`PIPELINE` Nodes:** Attempt `self.pipeline_registry.run()`, but default to mock strings on failure with hardcoded cost (`0.001`).
2. **Fabricated Telemetry:**
   - Token usage is omitted.
   - Step costs are static hardcoded floats rather than actual provider tokens or `CostTracker` telemetry.
   - Latencies represent small millisecond delays rather than actual inference or tool execution times.
3. **In-Memory Sequential Execution vs. Parallel Execution:**
   - In `engine.py`, execution is an in-memory, synchronous Python `for node in topological_nodes:` loop.
   - While `WorkflowNodeType.PARALLEL` marks `{"parallel_dispatch": True}`, subsequent branch nodes execute sequentially in the loop, not concurrently.
   - In `swarm.py`, `asyncio.gather()` executes concurrently, but each agent only sleeps for `0.05s` and returns a mock string without real model inference.
4. **No Durable Job Runtime or Restart Recovery:**
   - Execution state exists primarily in memory.
   - If the sidecar process crashes during workflow execution, in-flight work is lost.
   - There is no persistent job queue, heartbeat monitor, or resumption ledger.
5. **No Cancellation Runtime:**
   - Once `engine.run()` is invoked, it cannot be safely cancelled mid-run.
6. **No Security Sandbox Enforcement:**
   - Workflow nodes bypass `SecurityGuardrails`, AST policy scanning, and tool capability checks.

---

## 4. Architectural Invariants & Decisions for Stage R4

### 4.1. The Single Authoritative Execution Path

In accordance with **ADR-016**, workflow nodes must not execute through an independent shadow execution loop. In Stage R4, the execution path will converge:

```text
User clicks Run DAG
       ↓
Create WorkflowRun record
       ↓
Compile & Validate DAG (Kahn's algorithm)
       ↓
Create root Execution under ExecutionCoordinator
       ↓
For each topological step:
       ↓
  Dispatch canonical Task (DSPyTask, SkillTask, AgentTask, ApprovalTask)
       ↓
  Pass Context → Policy → Budget → Routing → Real Execution → Verification
       ↓
  Record actual token usage & costs via CostTracker
       ↓
  Stream ExecutionEvents to Canvas UI
       ↓
Final persistent state in Durable Job Ledger
```

### 4.2. Decoupling Visual Layout from Execution Semantics

To prevent presentation concerns from leaking into canonical execution contracts:
* **Legacy Format:** `node.position: { x: float, y: float }` embedded directly in `WorkflowNode`.
* **Canonical Format:** The execution model defines pure semantic tasks and edges. Canvas layout coordinates are isolated into non-semantic layout metadata (`layout: { position: { x, y } }`).
* **Backward Compatibility Guarantee:** The parser and API will continue accepting legacy `position` fields during migration and provide deterministic conversion, ensuring zero breakage for existing saved workflows or exported YAML files.

### 4.3. Approval Gate UX vs. Security Authorization Boundary

A strict distinction is established between:
1. **Workflow Approval Gate (`ApprovalTask`):**
   A workflow orchestration construct where a human operator makes a business or operational decision (e.g., approve draft, select deployment target, or reject content).
2. **Canonical Security Approval Service (`core/security/`):**
   A cryptographically bound security boundary for sensitive or consequential operations (file deletion, database drops, network access, shell commands). Requires:
   - Authenticated operator identity.
   - Exact operation descriptor.
   - SHA-256 hash of immutable arguments.
   - Non-renewable expiration timestamp.
   - Single-use consumption token.

Workflow approval gate records alone **will not authorize consequential tool operations**. Consequential tools invoked downstream must pass through the canonical security approval boundary.

### 4.4. Disambiguation of Parallelism

1. **Workflow Parallel (`WorkflowNodeType.PARALLEL`):**
   Durable, concurrent execution branches within a single DAG, synchronized via `WorkflowNodeType.MERGE` (`Join`). Backed by durable job workers.
2. **Team / Swarm Parallelism (`SwarmCoordinator` / Team Mode):**
   Autonomous specialist child agents collaborating on a shared prompt or objective, each running as an independent child execution under `ExecutionCoordinator`.

---

## 5. Phase 7 Capabilities Matrix & Ground-Truth Status

| Capability | UI Implemented | Runtime Implemented | Integrated | Behavior Verified | Release Verified |
|---|---|---|---|---|---|
| **Canvas Node Palette** | ✅ Yes | N/A | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **Node Drag & Drop** | ✅ Yes | N/A | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **Bezier Edge Wiring** | ✅ Yes | N/A | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **Inspector Panel** | ✅ Yes | N/A | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **YAML Export / Import** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **DAG Cycle Detection** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **Topological Sort** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **SQLite Definition Storage** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **Approval Gate Pausing** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **Approval Resumption** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **Rejection Branching** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **Redirection Branching** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **Dry Run Path Simulation** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ⚪ Gate 0.5 |
| **Real LLM Node Invocation** | ❌ No | ❌ No (Stub) | ❌ No | ❌ No | ⚪ Gate 0.5 (R1/R4) |
| **Real Skill Node Invocation**| ❌ No | ❌ No (Stub) | ❌ No | ❌ No | ⚪ Gate 0.5 (R1/R4) |
| **Real Token / Spend Tracking**| ❌ No | ❌ No (Stub) | ❌ No | ❌ No | ⚪ Gate 0.5 (R1/R4) |
| **Durable Job Resumption** | ❌ No | ❌ No | ❌ No | ❌ No | ⚪ Gate 0.5 (R4) |
| **Workflow Cancellation** | ❌ No | ❌ No | ❌ No | ❌ No | ⚪ Gate 0.5 (R4) |
| **Workflow Retries** | ❌ No | ❌ No | ❌ No | ❌ No | ⚪ Gate 0.5 (R4) |
| **Security Policy Checks** | ❌ No | ❌ No | ❌ No | ❌ No | ⚪ Gate 0.5 (R2/R4) |

---

## 6. Conclusion & Transition to Stage R0

Phase 7 has successfully delivered a robust visual workflow authoring canvas, schema parser, and approval gate interaction model. With this audit formally established:

1. **All Phase 7 deliverables are preserved.**
2. **No code rewrites will take place on the workflow UI.**
3. **Stage R0 can proceed with full clarity regarding what is real vs. what will be integrated in Stage R4.**
