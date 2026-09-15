# 🧠 Agent Engine — Engineering Memory & State Snapshot

*Last Updated: 2026-09-14 01:05 CEST*  
*Monorepo State: Phase 3 Complete (240/240 tests green, 100%)*

---

## 1. Active State & Progress

### Completed Milestones
- **Phase 0 — Monorepo Foundation & Tooling:** ✅ Complete
- **Phase 1 — Local Engine & Sidecar Core:** ✅ Complete (Milestone M1)
- **Phase 2 — Cross-Platform Shell:** ✅ Complete (Milestone M2)
- **Phase 3 — Desktop Shell & Interaction Surface (Tasks 3.1–3.11):** ✅ Complete (Milestone M2.5)
  - **Task 3.1:** Home Screen (Empty & Chat states, 60fps streaming, tokens/sec, cost estimation)
  - **Task 3.2:** Slash Commands & Skills Popup (`/skill`, `/agent`, `/workflow`, `/clear`, `/web-search`, `/memory`, `/sandbox`)
  - **Task 3.3:** Interactive Inline Approvals (`ApprovalCard.tsx`, risk tiers, diff viewer, JSON arg editor, 60s timeout)
  - **Task 3.4:** Model & Agent Persona Switcher (`PersonaPicker.tsx`, `Instant`/`Swarm`/`Reasoning` tiers, cost tracking)
  - **Task 3.5:** Session Sidebar & Search (3-zone layout, real-time keyword search `/v1/sessions/search`, icon strip collapse)
  - **Task 3.6:** Document Drop & RAG Ingestion (full-canvas drag-drop, ChromaDB indexing, attachment chips with preview)
  - **Task 3.7:** My Agent Screen (365-day contribution heatmap <200ms load, Closeness/Growth/Memory/Cost tabs, observational memory ledger)
  - **Task 3.8:** Scheduled Tasks Screen (plain-English cron builder, Law 7 off-peak window 02:00–06:00, 3 creation paths, 4 templates)
  - **Task 3.9:** Universal Chat Input Hardening (60fps on 10k+ chars, paste image & drag-drop, calibrated ±5% token estimator)
  - **Task 3.10:** Mode Landing Page Template (`ModePage.tsx`, `FeaturedGrid.tsx`, persistent chat history across mode switches)
  - **Task 3.11:** Featured Cases Content Curation (32 curated templates in `configs/cases/`, dedicated mode screens in `apps/desktop/src/renderer/screens/Modes/`, one-click prompt injection, `core/cases.py` loader & search, FastAPI `/v1/cases` endpoints)

### Current Test Count
- **Monorepo Tests:** `254 passed` (strictly increasing with every completed task).
- **Desktop Build:** `pnpm --filter @agent-engine/desktop build` passes with 0 TypeScript errors.
- **Cargo Check:** `cargo check` in `apps/desktop/src-tauri` passes cleanly.

---

## 2. Active Scope: Phase 4 — Control Dashboard (Milestone M3)

Aligned with `docs/PROJECT_REVIEW_2026-09-14.md` to remediate findings F01–F14:
1. **Task 4.0 — Foundation Hardening & Contract Alignment:** ✅ Complete (Remediated F01, F02, F04, F05, F09, F12; 247/247 tests green)
2. **Task 4.1 — Projects & Workspaces (Organiser):** ✅ Complete (`apps/desktop/src/renderer/screens/Projects.tsx`, `ProjectDetail.tsx`, Centered Create Project modal, context & file scoping; 248/248 tests green)
3. **Task 4.2 — Provider Setup Panel & Keychain Storage:** ✅ Complete (`apps/desktop/src/renderer/screens/Settings.tsx`, OpenAI/Anthropic/Gemini/Ollama/vLLM/Custom cards, 1-click test button, OS keychain integration; 249/249 tests green)
4. **Task 4.3 — End-to-End Real Execution Engine (F03):** ✅ Complete (Connected `Home.tsx` and `ModePage.tsx` to real streaming SSE, cancellation signal propagation, persisted session resumption, honest error reporting; 250/250 tests green)
5. **Task 4.4 — Mandatory Approval Queue & Safety Execution Boundary (F06):** ✅ Complete (Centralized queue in `screens/Policies.tsx`, fail-closed evaluation, single-use operation-bound execution tokens with 60s expiry; 251/251 tests green)
6. **Task 4.5 — Cost Dashboard (Merged 4.5 & 4.9; React in Desktop Shell):** ✅ Complete (`screens/Cost.tsx`, responsive SVG 90/9/1 donut, spend ledger, budget ceilings, Law 8 distillation pipeline, CSV/JSON export; 252/252 tests green)
7. **Task 4.6 — Policy Editor & Immutable Audit Log:** ✅ Complete (`screens/Policies.tsx`, YAML editor with validation & hot-reload, zero-footprint dry-run playground, paginated immutable audit log with filters & CSV/JSON export; 253/253 tests green)
8. **Task 4.7 — Hardware Telemetry Panel:** ✅ Complete (`core/telemetry/hardware.py`, `TopBar.tsx` status bar with 2s polling, `Settings.tsx` Hardware & Compute panel, GPU model detection, VRAM 95% warning threshold, tokens/sec throughput gauge; 254/254 tests green)
9. **Task 4.8 — Settings Screen & Diagnostics Export (⏳ NEXT)**
   - Tabbed configuration layout (Providers, Models, Local Runtime, Adapters, Channels, Storage, Security, Appearance, Diagnostics), encrypted local config, diagnostics bundle export (`.zip`).
10. **Task 4.9 — Streamlit Demotion to Developer Tool & Process Lifecycle (F07, F14)**
    - Demote Streamlit to `tools/dev_dashboard.py`, fix `start_studio.sh` traps.

---

## 3. Critical Rules & System Nuances

- **BypassSandbox Requirement:** Always use `BypassSandbox: true` for all `run_command` tool calls due to daemon socket resets on this system.
- **Python Environment:** Always use `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/ruff` or `make verify`.
- **Pre-commit Hooks:** Git commits run `ruff` and `ruff-format`. If `ruff-format` reformats on commit, re-stage with `git add .` and re-run commit.
- **Architectural Decision — Streamline to ONE:** Desktop Tauri shell is the **only user-facing dashboard**. Demote Streamlit to a hidden developer tool (`tools/dev_dashboard.py`, `make dev-dashboard`).
- **Governing Laws:**
  - **Law 1 (The 90/9/1 Rule):** 90% deterministic/cache/local, 9% mid-tier, 1% frontier (<8k token budget).
  - **Law 3 (Zero-Trust Security):** Inline approvals for dangerous operations with parameter editing and 60s timeout.
  - **Law 7 (Off-Peak Execution):** Default background runs to 02:00–06:00 window.
- **Design Tokens:** Strict dark-theme default (`--bg-base: #0a0a0a`, `--bg-elevated: #141414`, `--accent: #3b82f6`, `--border-subtle: #1f1f1f`).
- **Per-Task Workflow:**
  1. Mark task IN PROGRESS in `docs/ROADMAP.md`.
  2. Implement deliverables at exact file paths.
  3. Verify with `make verify`, `pnpm --filter @agent-engine/desktop build`, and `cargo check`.
  4. Ensure test count strictly increases.
  5. Capture headless screenshot with Firefox and document in `docs/GUI.md` (Part 9).
  6. Mark ✅ DONE in `docs/ROADMAP.md` and commit with conventional message (`feat(...)`).
- **Stop Checkpoints:**
  - (a) End of Phase 3 — reached & verified!
  - (b) After Wave-2 parallel agents merge.
  - (c) After Phase 5–14 plan-only pass.

---

## 4. Documentation Inventory
- `docs/USER_GUIDE.md`: Comprehensive user guide and operational manual.
- `docs/GUI.md`: Complete screen specifications, design system tokens, and Part 9 Visual Verification Screen Gallery.
- `docs/ROADMAP.md`: Master phase and task roadmap with acceptance criteria and status tracking.
- `docs/COST_OPTIMIZATION_GUIDE.md`: 90/9/1 token optimization guidelines.
- `README.md`: High-level repository overview and quickstart links.
