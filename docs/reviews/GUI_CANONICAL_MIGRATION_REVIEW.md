# Agent Engine — Canonical GUI Migration Review & Strategy

> **Review Type:** Architectural & Interface Audit  
> **Target Release:** `0.5 Nadir Edition`  
> **Author:** Architecture & Frontend Systems Lead  
> **Status:** Review Draft for Product Owner & CTO Review  
> **Governing Specifications:** [`docs/GUI.md`](../GUI.md), [`docs/ROADMAP.md`](../ROADMAP.md)  
> **Supersedes:** Legacy Kimi-inspired design notes in [`docs/archive/GUI_LEGACY.md`](../archive/GUI_LEGACY.md)

---

## 1. Current Routes and Screens

The existing desktop application uses client-side hash routing (`window.location.hash`) in [`apps/desktop/src/renderer/App.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/App.tsx). The active route table comprises 21 distinct hash targets:

| Route Hash | Screen Component | Current User-Facing Title | Primary Responsibility |
|---|---|---|---|
| `#home` | [`Home.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Home.tsx) | `Chat` | Universal prompt input, session chat history, drag-drop RAG ingestion, and featured inspiration cards. |
| `#agent` | [`Agent.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Agent.tsx) | `Nadir's Agent` | Agent identity, 365-day interaction heatmap, Closeness network visualizer, growth proficiencies, and observational memory. |
| `#tasks` | [`Tasks.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Tasks.tsx) | `Scheduled Tasks` | Cron schedule creation, off-peak execution rules (02:00–06:00), channel alerts, and background task management. |
| `#swarm` | [`Swarm.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Swarm.tsx) | `Swarm Studio` | Multi-agent team execution (Architect, Coder, Tester, Deployer), parallel synthesis, and simulated progress bars. |
| `#workflows` | [`Workflows.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Workflows.tsx) | `Workflow Builder` | Interactive SVG canvas, Kahn's DAG compiler, drag-and-drop node palette, inspector panel, dry-run simulation, and YAML editor. |
| `#projects` | [`Projects.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Projects.tsx) & [`ProjectDetail.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/ProjectDetail.tsx) | `Projects & Workspaces` | Project list, creation modal, scoped security policies, monthly spend tracking, file manager, and session threads. |
| `#cost` | [`Cost.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Cost.tsx) | `Cost Dashboard` | Spend metrics, budget ceilings, 90/9/1 tier donut chart, token bar charts, CSV/JSON export, and distillation triggers. |
| `#policies` | [`Policies.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Policies.tsx) | `Policies & Approval Queue` | Approval queue (`queue`), active rule inspection (`policies`), YAML policy editor (`editor`), AST regex playground (`playground`), and audit ledger (`audit`). |
| `#skills` | [`Skills.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Skills.tsx) | `Skills & Adapters` | Installed skill catalog, YAML frontmatter editor, live schema validation, collections manager, and remote discovery modal. |
| `#settings` | [`Settings.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Settings.tsx) | `Settings` | 10-tab system settings (API keys, hardware telemetry, providers, general preferences, theme, sound, and notifications). |
| `#code` | [`CodeMode.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Modes/CodeMode.tsx) | `Kimi Code Mode` | Chat wrapper with pre-curated code prompts (AST refactoring, Pytest generation, security audit). |
| `#deep-research` | [`ResearchMode.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Modes/ResearchMode.tsx) | `Deep Research` | Chat wrapper with pre-curated research prompts (architecture comparison, benchmarks, consensus mechanisms). |
| `#docs` | [`DocsMode.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Modes/DocsMode.tsx) | `Document Writer` | Chat wrapper with technical documentation templates (RFCs, specs, chapter authoring). |
| `#sheets` | [`SheetsMode.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Modes/SheetsMode.tsx) | `Sheets & Analysis` | Chat wrapper with spreadsheet and financial analysis templates. |
| `#slides` | [`SlidesMode.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Modes/SlidesMode.tsx) | `Presentation Slides` | Chat wrapper with slide deck outline and presentation templates. |
| `#websites` | [`WebsitesMode.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Modes/WebsitesMode.tsx) | `Website Builder` | Chat wrapper with landing page and web design prompts. |
| `#design` | [`DesignMode.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Modes/DesignMode.tsx) | `Design Studio` | Chat wrapper with visual styling and component design prompts. |
| `#diagrams` | [`DiagramsMode.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Modes/DiagramsMode.tsx) | `Architecture Diagrams` | Chat wrapper with Mermaid diagram and system topology prompts. |
| `#channels` | Fallback in `App.tsx` | `Channels Bridge` | Navigation placeholder for native messaging adapters (Slack, Teams, Discord, Mattermost). |
| `#marketplace` | Fallback in `App.tsx` | `Agent Marketplace` | Navigation placeholder for skill/agent package discovery (ADR-007 gated). |
| `#benchmarks` | Fallback in `App.tsx` | `Model Eval & Benchmarks` | Navigation placeholder for DSPy evaluation and routing benchmarks. |

---

## 2. Current Navigation Hierarchy

The existing navigation is split between two primary surfaces:

### 2.1 Sidebar Hierarchy (`Sidebar.tsx`)
Currently divided into four unstructured vertical zones containing 18 top-level items:
1. **Zone A (Global Actions):** `AE` logo, collapse toggle (`PanelLeftClose`), `+ New Chat [Ctrl K]`, and debounced session search.
2. **Zone B (Primary Modes):** `My Agent` (Sparkles), `Scheduled Tasks` (Clock), `Swarm` (Zap), `Workflows` (GitBranch).
3. **Zone C (Capability Modes):** `Code`, `Deep Research`, `Docs`, `Sheets`, `Slides`, `Websites`, `Design`, `Diagrams`.
4. **Zone D (Platform & Operations):** `Channels`, `Skills & Adapters`, `Marketplace`, `Cost`, `Policies & Approvals`, `Benchmarks`.
5. **Bottom Area:** Projects list (`Organiser Workspace`, `Client Website`), Recent chats list, and Settings gear icon.

### 2.2 Top Bar Hierarchy (`TopBar.tsx`)
1. **Left:** Mode title (e.g. `Kimi Code Mode`, `Nadir's Agent`).
2. **Right:**
   - **Hardware Telemetry Bar (Always Visible):** Monospace readouts for GPU model, VRAM used/total with percentage, RAM used/total, and CPU percentage. Includes a pulsing red badge (`VRAM 95% CRITICAL`) on saturation.
   - **Model Tier Selector:** Dropdown displaying `Instant High`, `K3 Swarm High`, and `K3 High` with hardcoded costs (`$0.0002 / 1k`, etc.).
   - **Sidecar Health Dot:** Green (`ready`), Amber (`degraded`), or Red (`offline`).

---

## 3. Screens that Already Fit the Canonical Design

Several core subsystems were built with clean architecture and require **zero structural rewrites**, serving as anchors for the new desktop design:

1. **Visual Workflow Builder Canvas ([`Workflows.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Workflows.tsx)):**
   - **Why it fits:** The interactive SVG bezier canvas, pan/zoom controls, draggable node positioning, input/output connection ports, inspector parameter editing, dry-run simulation, and lossless YAML round-trip provide exactly the visual workflow workbench envisioned by the canonical architecture.
   - **Preservation Action:** `KEEP`. Execution behavior is strictly preserved; changes are limited to aesthetic palette groupings and neutral node restyling.
2. **Projects & Workspace Manager ([`Projects.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Projects.tsx), [`ProjectDetail.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/ProjectDetail.tsx)):**
   - **Why it fits:** Already represents projects as first-class operational workspaces with custom instructions, file management, scoped security policies, thread associations, and spend monitoring.
   - **Preservation Action:** `KEEP` / `EXPAND`. Retain all data models; transition from SaaS card grids to split-pane desktop layout.
3. **Interactive Approval Card ([`ApprovalCard.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/components/ApprovalCard.tsx)):**
   - **Why it fits:** Supports structured unified diff inspection, argument inspection, risk severity badges, inline argument editing, and fast audit dispatch.
   - **Preservation Action:** `KEEP`. Remove decorative pulsing borders; retain core verification contracts.
4. **Universal Session Search ([`Sidebar.tsx:64-110`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/shell/Sidebar.tsx#L64-L110)):**
   - **Why it fits:** Debounced real-time query against `/v1/sessions/search` with keyboard ESC handling.
   - **Preservation Action:** `KEEP`. Preserve directly within the restructured sidebar.

---

## 4. Screens that Require Restyling Only

These screens have sound functional foundations but suffer from decorative "AI app" visual clichés:

1. **Workflow Builder Node Canvas ([`Workflows.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Workflows.tsx)):**
   - **Current Anti-Patterns:** Saturated purple, blue, and emerald glowing borders; heavy colored badges; animated execution pulses across entire node bodies.
   - **Restyling Required:** Restyle nodes to neutral dark desktop surfaces (`bg-bg-elevated`, `border-border-subtle`). Use color solely for execution state dots (green=completed, blue=running, amber=waiting, red=failed). Group palette into `LOGIC`, `WORK`, and `CONTROL`.
2. **Settings Screen ([`Settings.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Settings.tsx)):**
   - **Current Anti-Patterns:** Floating card clusters with glowing toggle switches, redundant pills, and scattered provider settings.
   - **Restyling Required:** Adopt dense, clean macOS/Linux preferences layout with split categories on the left and form fields in grouped neutral tables on the right.
3. **Task Schedule Inspector ([`Tasks.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Tasks.tsx)):**
   - **Current Anti-Patterns:** Oversized card layout for each scheduled task with decorative badges.
   - **Restyling Required:** Convert into a high-density tabular list: `Task`, `Schedule`, `Project`, `Last Run`, `Next Run`, and canonical `Status`.

---

## 5. Screens that Require Information-Architecture Changes

1. **Shell Navigation & Sidebar ([`Sidebar.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/shell/Sidebar.tsx)):**
   - **Problem:** Exposes 18 flat modes, mixing primary work (Home, Projects) with specialized tools (Docs, Sheets) and operational internals (Cost, Benchmarks).
   - **New Canonical IA:** Converge onto four clean functional sections:
     ```text
     WORK        → Home, Projects, Tasks, Automations
     TOOLS       → Research, Writing, Data, Developer
     LIBRARY     → Knowledge, Skills
     SYSTEM      → Activity, Approvals, Models
     Bottom      → Profile & Memory, Settings
     ```
2. **Top Bar & System Telemetry ([`TopBar.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/shell/TopBar.tsx)):**
   - **Problem:** Permanently displays hardware VRAM/CPU/RAM stats and hardcoded model tiers (`Instant High`), reinforcing the "AI playground" look.
   - **New Canonical IA:** Remove permanent hardware gauges. Display a single quiet status indicator: `Ready` / `Busy` / `Degraded` / `Offline`. Clicking opens a diagnostics popover.
3. **Home Canvas ([`Home.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Home.tsx)):**
   - **Problem:** Displays marketing-style greeting ("Collaborate with your local-first multi-agent engine"), persona pills, and an "Explore Inspiration" 3-column card grid.
   - **New Canonical IA:** Sober workbench start page:
     ```text
     Good morning, Nadir
     [ Universal command/task input ]
     Recent Work (compact list)
     Pinned Projects (compact rows)
     Quick Actions: Research | Write | Analyze data | Work on code
     ```
4. **Agent Screen ([`Agent.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Agent.tsx)):**
   - **Problem:** Gamified "Age: 271 days", "Level 14 Specialist", "12-day streak", animated memory dots, and "Closeness" network graph.
   - **New Canonical IA:** Rebuild as `Profile & Memory` with four clear functional sections: `Preferences`, `Memory`, `Instructions`, and `Privacy`.

---

## 6. Screens that Should Be Renamed or Moved

| Old Location / Name | New Canonical Location | User-Facing Name | Rationale |
|---|---|---|---|
| `My Agent` (`#agent`) | `Bottom Nav` / `LIBRARY` | `Profile & Memory` | Replaces gamified persona with personal settings and knowledge. |
| `Swarm` (`#swarm`) | `WORK` $\rightarrow$ `Automations` | `Teams` (Tab under Automations) | Eliminates AI jargon ("Swarm") in primary navigation. |
| `Workflows` (`#workflows`) | `WORK` $\rightarrow$ `Automations` | `Workflows` (Tab under Automations) | Groups workflows, schedules, and teams into one Automations hub. |
| `Scheduled Tasks` (`#tasks`) | `WORK` | `Tasks` | Standardizes terminology to direct user work. |
| `Cost` (`#cost`) | `SYSTEM` $\rightarrow$ `Activity` | `Usage` (Tab under Activity) | Consolidates execution history, token spend, and audit into Activity. |
| `Policies & Approvals` (`#policies`) | `SYSTEM` | `Approvals` | Separates daily operational approvals from developer security rules. |
| `Benchmarks` (`#benchmarks`) | `SYSTEM` $\rightarrow$ `Models` | `Diagnostics` (Tab under Models) | Moves technical evaluation out of primary navigation into Models hub. |
| `Marketplace` (`#marketplace`) | `LIBRARY` $\rightarrow$ `Skills` | `Browse` (Tab under Skills) | Eliminates consumer hype; treats skills as professional extensions. |
| `Channels` (`#channels`) | `Settings` | `Connections` (Tab under Settings) | Moves messaging adapters into configuration settings. |
| `Deep Research` (`#deep-research`) | `TOOLS` | `Research` | Standardizes tools under clean work-oriented verbs. |
| `Docs` (`#docs`) | `TOOLS` | `Writing` | Evolves from chat mode into document-first editor. |
| `Sheets` (`#sheets`) | `TOOLS` | `Data` | Evolves from chat mode into spreadsheet/tabular workbench. |
| `Code` (`#code`) | `TOOLS` | `Developer` | Evolves from chat mode into code/repo workbench. |

---

## 7. Screens & Features to Hide from Standard Mode

To maintain the **"Work first, AI second"** principle, technical and framework internals must be relegated to **Advanced Mode** or **Developer Mode**:

### Hidden Behind System Status Popover / Developer Mode:
- **Hardware Telemetry Readouts:** GPU model, VRAM %, RAM %, CPU load.
- **Hardware Saturation Warnings:** Critical VRAM saturation badges.
- **Tokens/Sec and Raw Latency:** Per-message generation speed indicators.

### Hidden Behind Developer Mode / Disclosures:
- **90/9/1 Donut Visualizer:** The three-color SVG donut chart and tier breakdown percentages.
- **DSPy Pipeline & Signature Declarations:** Internal prompt optimization indicators.
- **Raw Model Identifiers:** Concrete strings (`qwen2.5-coder:7b`, `claude-3-5-sonnet-20241022`). Standard Mode displays `Automatic`, `Local`, `Balanced`, `Best Quality`.
- **AST Safety Policy YAML Editor:** Raw regex pattern editor and dry-run rule syntax.
- **MCP / ACP Protocol Framing:** Raw JSON-RPC request/response event inspectors.
- **Distillation Trigger Buttons:** Manual fine-tuning and model distillation triggers.

---

## 8. Existing Components that Should Be Reused

The existing frontend codebase in `apps/desktop/src/renderer/` contains robust, tested assets that must be preserved:

| Component | File Path | Assets to Reuse | Refactoring Required |
|---|---|---|---|
| **Canvas & DAG Engine** | [`screens/Workflows.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Workflows.tsx) | SVG cubic bezier renderer, drag-and-drop mechanics, port hit-testing, zoom/pan handlers, YAML round-trip, inspector form. | Palette categorization (`LOGIC`, `WORK`, `CONTROL`), neutral node styles, subtle status dots. |
| **Chat & Command Input** | [`components/ChatInput.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/components/ChatInput.tsx) | Multiline auto-resizing, token estimator, attachment chips, slash-command popup (`/`), drag-drop file binding. | Default model to `Automatic`; remove decorative badges. |
| **Message Renderer** | [`components/Message.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/components/Message.tsx) | Markdown parser, syntax-highlighted code blocks, copy actions, streaming token animation. | Retain completely; ensure high-contrast accessibility. |
| **Approval Gate Card** | [`components/ApprovalCard.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/components/ApprovalCard.tsx) | Unified diff viewer, risk scoring, JSON argument editor, audit dispatch. | Replace pulsing colored borders with clean sober decision box. |
| **Sidecar API Client** | [`api/client.ts`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/api/client.ts) | Complete TypeScript client covering sessions, memory, tasks, workflows, skills, policies, and health checks. | Retain 100%; zero changes to API contracts needed. |
| **Session Search** | [`shell/Sidebar.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/shell/Sidebar.tsx#L64-L110) | Debounced search handler, query highlighting, keyboard escape clear. | Retain directly within new canonical sidebar. |
| **Cron Schedule Helpers** | [`screens/Tasks.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Tasks.tsx#L90-L150) | `cronToPlainEnglish` translator, schedule validation, off-peak calculator. | Reuse within new compact Tasks table. |
| **Skill Editor & Validator** | [`screens/Skills.tsx`](file:///home/nadir/code/agent_engine/apps/desktop/src/renderer/screens/Skills.tsx) | Frontmatter parser, validation diagnostic box, collection tagging, registry client. | Restyle into Installed / Browse / Updates layout. |

---

## 9. Routing & Backward-Compatibility Risks

### Identified Risks:
1. **Hash Bookmark Breakage:** Existing tests, developer bookmarks, or documentation links may reference legacy hashes like `#deep-research`, `#docs`, `#cost`, `#policies`, or `#agent`.
2. **Test Selector Deprecation:** Integration and unit tests expect specific DOM selectors (`data-testid="canvas-drag-overlay"`, `data-testid="agent-heatmap-grid"`, `data-testid="upload-progress-bar"`).
3. **State Desynchronization:** Switching modes must preserve active session IDs, in-flight inputs, and uncommitted edits.

### Mitigation Strategy:
- **Canonical Hash Aliasing:** In `App.tsx`, maintain a deterministic translation table that maps legacy hash routes to their canonical equivalents:
  ```typescript
  const HASH_ALIASES: Record<string, { mode: Mode; subtab?: string }> = {
    'deep-research': { mode: 'research' },
    'docs':          { mode: 'writing' },
    'sheets':        { mode: 'data' },
    'code':          { mode: 'developer' },
    'agent':         { mode: 'profile' },
    'cost':          { mode: 'activity', subtab: 'usage' },
    'policies':      { mode: 'approvals' },
    'swarm':         { mode: 'automations', subtab: 'teams' },
    'marketplace':   { mode: 'skills', subtab: 'browse' },
    'benchmarks':    { mode: 'models', subtab: 'diagnostics' },
  };
  ```
- **Preserve Critical Data Attributes:** Retain essential `data-testid` attributes on rebuilt components to ensure existing and future test suites pass without regression.

---

## 10. Proposed Implementation Order

To maintain product stability, avoid breaking existing tests, and preserve the desktop shell at every step, the redesign will proceed in 11 sequential, incremental phases:

```text
Step 1: Install Canonical GUI.md & Archive Legacy Spec (COMPLETED)
Step 2: Navigation & Information Architecture (Sidebar.tsx & App.tsx routing)
Step 3: Top Bar & System Status (TopBar.tsx quiet state indicator)
Step 4: Home Screen Workbench (Home.tsx sober start page)
Step 5: Profile & Memory (Agent.tsx -> Profile.tsx preferences & memory)
Step 6: Activity & Usage Consolidation (Cost.tsx + Audit -> Activity.tsx)
Step 7: Approvals Desk (Extract Approvals.tsx from Policies.tsx)
Step 8: Settings Consolidation (Settings.tsx canonical 9 categories)
Step 9: Skills & Extensions (Skills.tsx Installed/Browse/Updates)
Step 10: Workflow Visual Refinement (Workflows.tsx node palettes & states)
Step 11: Specialized Workspaces & Accessibility Polish (Research/Writing/Data/Developer & WCAG 2.2 AA)
```

Each step will follow the required verification protocol:
- State migration action (`KEEP` / `INTEGRATE` / `REFACTOR` / `EXPAND` / `SUPERSEDE`).
- Make smallest viable incremental change.
- Run `pnpm -r build` (zero TypeScript errors).
- Run `cargo check` in `apps/desktop/src-tauri` (zero Rust errors).
- Run `uv run pytest` (100% green test suite).

---

## 11. Screenshots of Current State & Anti-Pattern Analysis

The repository preserves visual evidence of the Phase 3 implementation in [`docs/screenshots/`](file:///home/nadir/code/agent_engine/docs/screenshots/). Below is an audit of each baseline screen and the specific anti-patterns to be phased out:

| Screenshot Asset | Captured Screen | Identified Anti-Patterns to Eliminate |
|---|---|---|
| `screen_task_3_4_home_model_switcher.png` | Home Model Dropdown | Exposed provider costs (`$0.0002/1k`), model tier hype (`Instant High`, `K3 Swarm High`), always-visible provider selection in standard mode. |
| `screen_task_3_5_sidebar_search.png` | Sidebar Navigation | 18 flat modes, purple/amber badges, neon icons, lack of clear grouping. |
| `screen_task_3_6_document_drop_rag.png` | Document Drop Overlay | Pulsing upload cards, "0-token caching" marketing text. |
| `screen_task_3_7_agent_screen.png` | My Agent Identity | "Age: 271 days", "Level 14 Specialist", "12-day streak", animated memory network dots, and growth radar charts. |
| `screen_task_3_8_scheduled_tasks.png` | Scheduled Tasks | Large floating cards with prominent AI icons rather than a high-density operations table. |
| `screen_task_3_9_universal_chat_input.png` | Universal Chat Input | Model tier badges permanently visible inside input box; sparkle icons. |
| `screen_task_3_10_mode_page_template.png` | Mode Landing Page | Chat-first interface with large hero card, category chips, and promotional inspiration cards. |
| `screen_task_3_11_featured_cases.png` | Featured Cases Grid | Consumer SaaS card grid ("Explore Inspiration") across all mode screens. |

---

## 12. Migration Classification for Every Screen

| Screen / Capability | Current Component | Canonical Destination | Action | Rationale |
|---|---|---|---|---|
| **Home Workbench** | `screens/Home.tsx` | `WORK` $\rightarrow$ `Home` | `REFACTOR` | Strip promotional cards and hero banner; implement compact workbench layout with command input, recent work, and pinned projects. |
| **Workflow Builder** | `screens/Workflows.tsx` | `WORK` $\rightarrow$ `Automations` $\rightarrow$ `Workflows` | `KEEP` / `REFACTOR` | Keep canvas, DAG compiler, inspector, and YAML engine (KEEP); restyle nodes to neutral palettes without neon glows (REFACTOR). |
| **Multi-Agent Teams** | `screens/Swarm.tsx` | `WORK` $\rightarrow$ `Automations` $\rightarrow$ `Teams` | `INTEGRATE` | Rebrand from "Swarm" to "Teams"; integrate into Automations hub; eliminate sleep loops in Stage R4. |
| **Tasks & Schedules** | `screens/Tasks.tsx` | `WORK` $\rightarrow$ `Tasks` | `REFACTOR` | Convert from card-heavy grid to compact operational table; standardize statuses to canonical vocabulary. |
| **Projects Manager** | `screens/Projects.tsx` | `WORK` $\rightarrow$ `Projects` | `KEEP` / `EXPAND` | Preserve models, instructions, and file state; convert card grid to desktop split-pane layout. |
| **Project Detail** | `screens/ProjectDetail.tsx` | `WORK` $\rightarrow$ `Projects` (Detail) | `KEEP` / `EXPAND` | Preserve workspace instructions, file attachments, and session threads; enhance split view. |
| **Research Workspace** | `screens/Modes/ResearchMode.tsx` | `TOOLS` $\rightarrow$ `Research` | `EXPAND` | Transition from generic chat wrapper (`ModePage.tsx`) to split multi-pane research workspace (Sources, Claims, Report). |
| **Writing Workspace** | `screens/Modes/DocsMode.tsx` | `TOOLS` $\rightarrow$ `Writing` | `EXPAND` | Transition from chat wrapper to document-first editor with outline and provenance sidebar. |
| **Data Workspace** | `screens/Modes/SheetsMode.tsx` | `TOOLS` $\rightarrow$ `Data` | `EXPAND` | Transition from chat wrapper to spreadsheet/table workbench with formula and anomaly tools. |
| **Developer Workspace** | `screens/Modes/CodeMode.tsx` | `TOOLS` $\rightarrow$ `Developer` | `EXPAND` | Transition from chat wrapper to code inspection, AST refactoring, and test execution workbench. |
| **Design / Slides / Websites** | `screens/Modes/*.tsx` | Sub-tools under `TOOLS` | `SUPERSEDE` | Replace individual standalone chat modes with modular capabilities in Developer and Writing tools. |
| **Profile & Memory** | `screens/Agent.tsx` | `LIBRARY` / Bottom Nav $\rightarrow$ `Profile & Memory` | `REFACTOR` | Strip gamified stats (level, streak, age) and neural network dots; rebuild as Preferences, Memory, Instructions, and Privacy. |
| **Skills & Extensions** | `screens/Skills.tsx` | `LIBRARY` $\rightarrow$ `Skills` | `REFACTOR` | Reorganize tabs to `Installed`, `Browse`, `Updates`; present skills as professional extensions with permissions. |
| **Approvals Desk** | `screens/Policies.tsx` (Queue) | `SYSTEM` $\rightarrow$ `Approvals` | `INTEGRATE` | Extract approval queue into dedicated sober decision desk; remove pulsing amber/red card visuals. |
| **Activity & Usage** | `screens/Cost.tsx` + Audit | `SYSTEM` $\rightarrow$ `Activity` | `INTEGRATE` | Merge cost metrics, execution history, and audit ledger into 4 tabs: `Executions`, `Usage`, `Audit`, `System`. |
| **Models Hub** | `Settings.tsx` (Providers) | `SYSTEM` $\rightarrow$ `Models` | `EXPAND` | Create dedicated view for Local models (ready/installed) and Cloud providers (connected/configured). |
| **Settings Console** | `screens/Settings.tsx` | Bottom Nav $\rightarrow$ `Settings` | `REFACTOR` | Restyle into canonical 9 categories; move policy rules to Security tab; remove clutter. |

---

## 13. Audit Conclusion & Next Steps

The current desktop shell has **high functional maturity (S3/S4)** across core capabilities:
- The SVG workflow canvas, drag-and-drop mechanics, and YAML serializers are robust.
- The project management, session persistence, and inline approval handling are fully functional.
- The Tauri v2 Rust shell and Python sidecar integration are stable and pass all checks.

The required transformation is **not a code rewrite**, but a **systematic visual and architectural de-gamification**:
1. Remove artificial AI tropes (streaks, levels, neural dots, pulsing neon cards).
2. Reorganize sidebar and top bar around **user work** rather than internal AI subsystems.
3. Evolve tool modes from plain chat prompts into real multi-pane productivity workbenches.

**Recommendation:** Present this review to the Product Owner & CTO for formal sign-off, then proceed sequentially with **Step 2 (Navigation Information Architecture & Sidebar)**.
