# Agent Engine — Canonical Architecture Specification

> **Status:** Canonical Architectural Authority  
> **Version:** 0.5.0-canonical  
> **Supersedes:** Legacy fragmented design documentation  
> **Governing ADR:** ADR-016 (Single Authoritative Execution Kernel Invariant)  

---

## 1. Architectural Principles & Invariants

The Agent Engine architecture is governed by seven core invariants:

1. **Single Authoritative Execution Kernel Invariant (ADR-016):**  
   Every model call, skill invocation, tool execution, workflow step, and swarm dispatch **must** execute through the canonical `ExecutionCoordinator`. No presentation surface or subsystem may maintain an independent shadow execution path.
2. **Local-First & Zero Non-Free Dependencies (ADR-013):**  
   The system runs on the user's local workstation, with local SQLite storage, local models where available, and in-tree Apache/MIT licensed components. Zero commercial restrictions, zero mandatory cloud sign-ups.
3. **Quality-Adjusted Cost per Successful Task:**  
   Replaces the legacy rigid 90/9/1 token formula. The engine dynamically routes each task to the cheapest model or execution tier (Code, Cache, Local Model, Mid-Tier, Frontier) capable of satisfying the quality and privacy constraints of the task.
4. **Decoupled Workflow Authoring & Execution:**  
   The visual DAG canvas (`Workflows.tsx`) is an **authoring and monitoring surface**, not an execution engine. Workflow definitions compile down to canonical `Execution` and `DurableJob` records. Visual coordinates (`position`) are treated as non-semantic layout metadata.
5. **Separation of Workflow Gates from Security Authorization:**  
   A workflow `ApprovalTask` represents an interactive user choice or branching decision. Consequential tool execution (filesystem write, shell execution, database modification) requires a signed token from the canonical **Approval Service** with immutable argument hashes and single-use consumption.
6. **Zero Fabricated Telemetry & Truthful States:**  
   All reported token counts, latencies, dollar expenditures, and execution statuses must reflect real provider data or be explicitly labeled as estimates.
7. **Durable Persistence Across System Restarts:**  
   Sessions, queued jobs, workflow executions, and approval gates are backed by persistent transactional storage (SQLite WAL) and survive desktop crashes and system reboots.

---

## 2. Layered Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                     LAYER 1: PRESENTATION SURFACES                     │
│   Desktop Shell (Tauri v2 + React 18)   │   CLI   │   MCP/ACP Protocols │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│                        LAYER 2: CONTROL PLANE                           │
│  Project Manager │ Unified Session Store │ Policy Engine │ Approval Svc │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│                    LAYER 3: CANONICAL EXECUTION KERNEL                  │
│                        ExecutionCoordinator                             │
│   Request → Context → Policy → Budget → Routing → Execute → Verify → Log│
└──────────────────┬───────────────────┬───────────────────┬──────────────┘
                   │                   │                   │
┌──────────────────▼────────┐ ┌────────▼─────────┐ ┌──────▼──────────────┐
│  LAYER 4: MODEL & RES HUB │ │ LAYER 5: TOOLS   │ │ LAYER 6: WORKFLOWS   │
│  Local Engine (Ollama)    │ │ SkillManager     │ │ DAG Compiler (Kahn)  │
│  Cloud Providers (OpenAI, │ │ AST Guardrails   │ │ Durable Job Scheduler│
│    Anthropic, Gemini)     │ │ MCP Client       │ │ HitL Approval Gates  │
│  Semantic Cache (L1/L2)   │ │ Native Channels  │ │ Mustache Templating  │
└──────────────────┬────────┘ └────────┬─────────┘ └──────┬───────────────┘
                   │                   │                  │
┌──────────────────▼───────────────────▼──────────────────▼───────────────┐
│                    LAYER 7: PERSISTENCE & STORAGE                       │
│    SQLite WAL Repository   │   AES-256 Vault   │   Artifact Storage     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Canonical Execution Flow

Every request entering the system follows one universal pipeline:

```text
1. ExecutionRequest
       ↓
2. Context Assembly
   (ContextBuilder: project files, bounded history, skill context)
       ↓
3. Policy & Security Pre-Flight
   (SecurityGuardrails: trust boundaries, AST scan, credential scope)
       ↓
4. Budget & Cost Allocation
   (CostTracker: check limits, rate caps, off-peak routing)
       ↓
5. Planning & Routing
   (ExecutionRouter: resolve tier, model, tool parameters)
       ↓
6. Consequential Authorization Check
   (ApprovalService: pause if action requires operator sign-off)
       ↓
7. Execution Dispatch
   (Model Gateway, Tool Runner, or Durable Job)
       ↓
8. Output Verification
   (Schema validation, safety check, assertion testing)
       ↓
9. Telemetry & Ledger Recording
   (Record actual tokens, latency, cost, and event stream)
       ↓
10. ExecutionResult
```

---

## 4. Legacy Subsystem Mapping Matrix

The legacy Phase 0–7 components map into the canonical architecture as follows:

| Legacy Module | Legacy Role | Canonical Subsystem | Canonical Destination | Migration Action |
|---|---|---|---|---|
| `core/router/` | 90/9/1 Step Profiler | Execution Kernel | `core/execution/router.py` | **INTEGRATE** |
| `core/cache/` | Semantic Cache | Model & Resource Hub | `core/resources/cache.py` | **KEEP** |
| `core/context/` | Context Builder | Execution Kernel | `core/execution/context.py` | **INTEGRATE** |
| `core/session/` | Unified Session Store | Control Plane | `core/session/store.py` | **KEEP** |
| `core/security/credentials.py` | Keyring & AES Vault | Security & Auth | `core/security/vault.py` | **KEEP** |
| `core/security/guardrails.py` | AST Safety Filters | Security & Auth | `core/security/policy.py` | **INTEGRATE** |
| `core/skills/` | Skill Discovery & Editor | Tools & Skills | `core/skills/` | **KEEP** |
| `core/rooms/` | Collaborative Overlays | Control Plane | `core/teams/rooms.py` | **INTEGRATE** |
| `core/adapters/` | Slack, Teams, Discord, MM | Tools & Channels | `core/channels/` | **KEEP** |
| `core/workflows/models.py` | Workflow Definition | Workflows & Jobs | `core/workflows/schema.py` | **INTEGRATE** |
| `core/workflows/parser.py` | Lossless YAML & Kahn DAG | Workflows & Jobs | `core/workflows/compiler.py` | **KEEP** |
| `core/workflows/storage.py` | SQLite Workflow DB | Persistence Layer | `core/storage/workflows.py` | **INTEGRATE** |
| `core/workflows/gates.py` | Approval Gate Manager | Workflows & Jobs | `core/workflows/gates.py` | **INTEGRATE** |
| `core/workflows/engine.py` | Workflow DAG Runner | Workflows & Jobs | Superseded by `ExecutionCoordinator` | **REFACTOR** |
| `core/workflows/swarm.py` | Parallel Swarm Teams | Workflows & Teams| Superseded by `ExecutionCoordinator` | **REFACTOR** |
| `apps/desktop/` | Tauri Desktop Shell | Presentation Layer | `apps/desktop/` | **KEEP & EXPAND** |

---

## 5. Domain Boundary Definitions

* **Project:** The isolated workspace boundary containing files, git state, instructions, and policies.
* **Session:** A conversation or interaction thread tied to a project, maintaining chronological messages and event history.
* **Execution:** A single, authoritative unit of work executed by the engine, tracked with immutable ID, status, inputs, outputs, and telemetry.
* **Job:** An asynchronous, durable unit of work scheduled or queued for background execution with retry policies.
* **Workflow:** A declarative, versioned DAG of tasks, conditions, approval gates, and edges.
* **Skill:** A deterministic tool, script, or capability executable with typed inputs and outputs.
* **Agent:** An autonomous actor combining instructions, model reasoning, and skill access.
* **Team:** A coordinated collection of specialist agents collaborating on a shared objective.
* **Artifact:** A persistent, immutable output file produced during execution (document, diff, diagram, report).
