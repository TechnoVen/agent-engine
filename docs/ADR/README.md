# Architecture Decision Records (ADR)

This directory records all architectural conflict resolutions and structural decisions for Agent Engine.

| ADR | Title | Status | Resolved Conflict |
|---|---|---|---|
| ADR-001 | Hybrid Shell: Tauri (Rust) + Python Sidecar | Accepted | C1 |
| ADR-002 | Streamlit (MVP) + Tauri React (Production Shell) | Accepted | C2 |
| ADR-003 | Repository Pattern: SQLite (Local) & PostgreSQL (Cloud) | Accepted | C3 |
| ADR-004 | Multi-Model Router with Fallback Chain | Accepted | C4 |
| ADR-005 | Agent Adapter Pattern | Accepted | C5 |
| ADR-006 | Staged Patches by Default with Human-in-the-Loop | Accepted | C6 |
| ADR-007 | Feature Flag Architecture for Tenant Isolation | Accepted | C7 |
| ADR-008 | Zero-Trust Local Encryption Before Cloud Sync | Accepted | C8 |
| ADR-009 | Dual Protocol MCP & ACP Servers | Accepted | C9 |
| ADR-010 | Unified Shell: Chat Primary + Dashboard Tab | Accepted | C10 |
| ADR-011 | Channel Adapter Pattern for Messaging | Accepted | C11 |
| ADR-012 | Layered Workflows: DSPy Modules + Graph Engine | Accepted | C12 |
| ADR-013 | Native Team Collaboration (No Switch Dependency) | Accepted | C13 |
| ADR-014 | Collaborative Rooms as Project Overlay | Accepted | C14 |
| ADR-015 | 90/9/1 Cost Optimization Discipline & Execution Routing | Accepted | C15 |

---

### ADR-013: Native Team Collaboration (No Switch Dependency)
- **Context:** Team collaboration channels (Slack, Microsoft Teams, Discord, Mattermost) are critical for enterprise multi-agent workflows. Switch provides collaboration bridges but is governed by Apache-2.0 + Commons Clause (source-available, commercial restrictions).
- **Decision:** Agent Engine **will not use or depend on Switch**. Instead, Agent Engine builds native, in-tree Python channel adapters (`core/adapters/slack.py`, `teams.py`, `discord.py`, `mattermost.py`) under Phase 5C. Personal omnichannel messaging (WhatsApp, Telegram) is handled via OpenClaw.
- **Consequences:** 100% license freedom (Apache/MIT), zero external binary/service runtime dependencies, complete control over security, rate limits, and audit logs.

---

### ADR-014: Collaborative Rooms as Project Overlay
- **Context:** Multi-agent collaboration requires persistent spaces where humans and multiple agents share context, channel-scoped roles, and task queues.
- **Decision:** Rooms are implemented natively within Agent Engine as a collaborative overlay on projects (`core/rooms/`). One project can possess multiple collaborative rooms (e.g. `#incident-response`, `#feature-engineering`).
- **Consequences:** Avoids duplicating folder/git project structures; enables fine-grained role-based access control and seamless human-in-the-loop task routing.

---

### ADR-003: Repository Pattern: SQLite (Local) & PostgreSQL (Cloud)
- **Context:** Agent Engine must operate as a frictionless, local-first single-user desktop application without requiring users to run database servers, while also scaling to enterprise cloud multi-tenant deployments.
- **Decision:** Storage is decoupled from concrete database engines via the `StorageBackend` abstract repository interface (`core/storage/base.py`). 
  - For local desktop and single-user workflows, `SQLiteBackend` (`core/storage/sqlite.py`) is used by default with zero setup, WAL journal mode, transaction safety, and thread safety.
  - For cloud and multi-tenant deployments, `PostgresBackend` (`core/storage/postgres.py`) provides pooled connections and tenant isolation (`tenant_id`).
  - Schema migrations are managed uniformly via Alembic (`alembic/`).
- **Consequences:** Single codebase runs seamlessly on local developer laptops and enterprise cloud clusters. Switches via `STORAGE_BACKEND=sqlite|postgres` environment variable. Zero database migration friction.

---

### ADR-007: Feature Flag Architecture for Tenant Isolation
- **Context:** Individual users need a lightweight, unencumbered local desktop application without unnecessary multi-user overhead or enterprise complexity. Conversely, enterprise teams require tenant data isolation, role-based access control, and centralized cloud synchronization.
- **Decision:** All enterprise features are gated behind the `core/config/flags.py` feature flag subsystem:
  - `TENANT_MODE`: Defaults to `single` (all resources map to default tenant; no tenant headers required). Enterprise deployments set `multi` to enforce tenant scoping.
  - `ENABLE_MULTI_USER`: Defaults to `false` for local personal installs.
  - `ENABLE_REGISTRY`: Defaults to `true` to enable skill/bundle search; when `false`, registry endpoints are gated with HTTP 404.
  - `ENABLE_CLOUD_SYNC`: Defaults to `false` ensuring zero-trust local-first privacy.
  - `ENABLE_ACP`: Defaults to `false` gating Agent Communication Protocol listeners until configured.
  - `ENABLE_AUTO_PATCH_APPLY`: Defaults to `false` enforcing human-in-the-loop patch reviews by default (ADR-006 / Conflict C6).
  - Flags can be queried via `GET /v1/flags` and dynamically overridden at runtime via `POST /v1/flags/{name}` for debugging and test suites.
- **Consequences:** Personal builds remain lean, snappy, and zero-setup, while enterprise builds enable complete isolation and access governance from the exact same codebase.

---

### ADR-015: 90/9/1 Cost Optimization Discipline & Execution Routing
- **Context:** Unconstrained LLM API usage and calling frontier models for simple tasks creates compounding, unsustainable operating costs.
- **Decision:** All pipelines and skills must obey the 90/9/1 rule (90% deterministic code/caching/small local models, 9% mid-tier, 1% frontier). All step invocations must be profiled via `StepProfile` and dispatched through `ExecutionRouter`. Context must be filtered via `ContextSpec` (< 8k target, 32k hard ceiling). Caching and distillation are mandatory at scale.
- **Consequences:** Target 90% reduction in AI operating spend, faster response latencies, and predictable unit economics. See [`docs/COST_OPTIMIZATION_GUIDE.md`](../COST_OPTIMIZATION_GUIDE.md).


