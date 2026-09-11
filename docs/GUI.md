# Agent Engine — Kimi-Inspired GUI Design & Gemini Instructions

## Part 1 — The Dashboard Decision (Answered First)

**Question:** Should we keep both dashboards (Streamlit + Tauri) or streamline?

**Answer: Streamline to ONE.** Ship the **Tauri shell as the only user-facing dashboard**. Demote Streamlit to a **hidden developer tool** (`make dev-dashboard`) that is never shipped to end users.

**Why:**

1. Kimi proves that a **single sidebar + main canvas** beats separate dashboards. Every screenshot shows the same shell — no separate "control panel" app.
2. Two dashboards = two codebases, two auth systems, two design languages, two bug surfaces. That is anti–Law 1 (90/9/1 discipline applied to engineering effort).
3. Streamlit was a Phase 4 shortcut. The Tauri shell in Phase 2 was always the long-term answer. Keep Streamlit only for internal debugging, benchmarking, and CI reports.
4. Enterprise buyers expect one product, not a "real app plus a Python dashboard."

**Action for Gemini:**
- Move Streamlit code from `server/dashboard.py` to `tools/dev_dashboard.py`.
- Remove all references to `http://localhost:8501` from user-facing docs.
- Update `start_studio.sh` to remove Streamlit from the default startup.
- Keep Streamlit only for `make dev` mode with a warning banner: "Developer tool — not for end users."

---

## Part 2 — Understanding the Kimi GUI (Complete Anatomy)

Kimi's GUI is not one page — it is a **unified shell with mode-based navigation**. Every screenshot shares the same skeleton. This is the pattern we adopt.

### 2.1 The Universal Shell (Present in Every Screenshot)

```
┌──────────────────────────────────────────────────────────────────────┐
│  LEFT SIDEBAR (280px)     │         MAIN CANVAS                     │
│                           │                                          │
│  [K Logo]    [<<]         │         (Mode-specific content)          │
│                           │                                          │
│  [+ New Chat]  Ctrl K     │                                          │
│                           │                                          │
│  ◯ My Kimi                │                                          │
│  ◯ Scheduled Tasks        │                                          │
│  ⚡ Swarm                 │                                          │
│  ▢ Slides                 │                                          │
│  🔍 Deep Research         │                                          │
│  🌐 Websites              │                                          │
│  📄 Docs                  │                                          │
│  📊 Sheets                │                                          │
│  🎨 Design                │                                          │
│  💼 Kimi Work             │                                          │
│  💻 Kimi Code             │                                          │
│  🦀 Kimi Claw             │                                          │
│  ─ OpenClaw-8Zw (agent)   │                                          │
│  ────────────────────     │                                          │
│  PROJECTS                 │                                          │
│  + New project            │                                          │
│  ▢ Organiser              │                                          │
│  ────────────────────     │                                          │
│  CHATS                    │                                          │
│  • Saturday Party...      │                                          │
│  • Oilist Project...      │                                          │
│  • Real Estate Est...     │                                          │
│                           │                                          │
│  ────────────────────     │                                          │
│  [Avatar] Ahmed...  ↑ ↓   │                                          │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 The Sidebar Anatomy (Three Zones)

**Zone A — Global Actions** (top)
- Logo + collapse toggle
- **New Chat** — the single most important action. Always visible. `Ctrl+K` shortcut.

**Zone B — Mode Navigation** (middle)
This is the key insight: Kimi treats each capability as a **mode**, not a menu item. Clicking `Slides` does not open a new app — it **swaps the main canvas** to a slides-focused workspace while keeping the sidebar, input box, project picker, and chat history intact.

Modes visible in the screenshots:
| Icon | Mode | Purpose |
|---|---|---|
| ◯ | My Kimi | Agent identity, memory, growth |
| ◯ | Scheduled Tasks | Cron-style recurring jobs |
| ⚡ | Swarm | Multi-agent parallel task execution |
| ▢ | Slides | Deck generation |
| 🔍 | Deep Research | Long-form investigative reports |
| 🌐 | Websites | Web builder |
| 📄 | Docs | Document writer |
| 📊 | Sheets | Spreadsheet/data work |
| 🎨 | Design | Visual/UI design |
| 💼 | Kimi Work | Work workflows |
| 💻 | Kimi Code | Coding agent |
| 🦀 | Kimi Claw | OpenClaw channel bridge (agent instance) |

**Zone C — Context** (bottom)
- **Projects** — persistent workspaces (folders of related chats + files + instructions)
- **Chats** — recent conversation history
- **User footer** — avatar, name, upgrade, download

### 2.3 The Universal Input Box (Present in Every Mode)

The most important reusable component. It appears identically in every mode, only the placeholder and mode-chip change.

```
┌────────────────────────────────────────────────────────────────┐
│  Type "/" to invoke plugins and skills                         │
│                                                                │
│  [+]                                    [Instant High ▾] [↑]  │
├────────────────────────────────────────────────────────────────┤
│  [📁 Select project ▾]   [icons]   [Plugins ▾]                │
└────────────────────────────────────────────────────────────────┘
```

Components:
- **Large textarea** with placeholder that adapts to mode
- **`+` button** — attach files, images, documents
- **Mode chip** (e.g., `Swarm`, `Slides`, `Deep Research`, `Sheets`) — click to switch mode without leaving chat
- **Model selector** (`Instant High`, `K3 Swarm High`, `K3 High`) — quick model tier switch
- **Send arrow** — disabled until text entered
- **Project selector row** — bind this chat to a project
- **Plugin icons row** — active plugins with quick toggles
- **Plugin dropdown** — full plugin/skill picker

### 2.4 The Mode Landing Pages (Empty States)

Each mode has a **rich empty state** with feature cards — this is a huge UX win:

| Mode | Empty State Content |
|---|---|
| **Home** | KIMI logo + input + quick action chips (Swarm, Slides, Deep Research, Websites, Docs, Sheets, Design) + "Explore inspiration" scroll bar |
| **Swarm** | "Assign a task to your AI team..." + Featured cases (Blackhole, 3D Typewriter, Market Dashboard) |
| **Slides** | "Turn your ideas into stunning slides in minutes" + category tabs (All, Custom, Work, Finance, Consulting, Promotion, Academic) + template grid |
| **Deep Research** | "Ask Kimi to get an in-depth research report" + Featured cases (42 Years of Silicon, Shipping: Not One Cycle, The Interactive Paper) |
| **Scheduled Tasks** | "Let Kimi run tasks on schedule..." + "Add manually or Create via chat" + Create dropdown |
| **Sheets** | "Upload a spreadsheet..." + featured templates |

**Design lesson:** Never show an empty chat. Always show **example prompts and featured cases**. This reduces first-use friction and teaches the feature without documentation.

### 2.5 The My Kimi Page (Identity & Memory)

This is the agent's "self" page — unique to Kimi and a powerful concept we must adopt:

- **Header:** "{User}'s Kimi" — the agent belongs to the user, is personalized
- **Stats strip:** "271 days, 39 chats, 1 day streak"
- **Tabs:** `Closeness` (interaction graph) / `Growth` (capability graph)
- **Contribution heatmap:** GitHub-style, shows engagement over 12 months
- **Self-growth toggle:** "Once enabled, Kimi keeps learning your preferences, habits, and ways of working, making every collaboration the start of the next one"
- **Neural visualization:** abstract dots representing the growing memory network

**Design lesson:** The agent is not a tool — it is a **relationship**. Users come back to see growth, streaks, and memory. This drives retention and creates emotional investment.

### 2.6 The Project Page

- **Project name** as page title
- **Thread list** below — each thread shows title, timestamp, and preview text
- **Right panel** with two cards:
  - **Instructions** — persistent system prompt for the project
  - **Files** — attached files referenced across all project chats
- **Bottom input** — chat scoped to the project

### 2.7 The Create Project Flow

- Centered modal-style page
- **"Keep one topic in one place"** — clear purpose statement
- **Folder icon carousel** — pick an icon visually
- **Name input** — single field
- No clutter — one decision per screen

---

## Part 3 — Mapping Kimi's GUI to Agent Engine Features

| Kimi Element | Agent Engine Equivalent | Notes |
|---|---|---|
| Sidebar `New Chat` | **New Chat** | Same (`Ctrl+K`) |
| Sidebar `My Kimi` | **My Agent** | Agent identity, memory, growth, cost summary (`/agent`) |
| Sidebar `Scheduled Tasks` | **Scheduled Tasks** | Same + workflow-based scheduling (`/tasks`) |
| Sidebar `Swarm` | **Swarm** | Multi-agent parallel execution (`/swarm`) |
| Sidebar `Slides` | **Slides** | Deck generation (skill) (`/modes/slides`) |
| Sidebar `Deep Research` | **Deep Research** | Long-form research (skill) (`/modes/deep-research`) |
| Sidebar `Websites` | **Websites** | Web builder (skill) (`/modes/websites`) |
| Sidebar `Docs` | **Docs** | Document writer (skill) (`/modes/docs`) |
| Sidebar `Sheets` | **Sheets** | Spreadsheet/data (skill) (`/modes/sheets`) |
| Sidebar `Design` | **Design** | Visual/UI design (skill) (`/modes/design`) |
| Sidebar `Kimi Work` | **Workflows** | Graph workflow builder + runner (`/workflows`) |
| Sidebar `Kimi Code` | **Code** | Code mode + IDE adapters (`/modes/code`) |
| Sidebar `Kimi Claw` | **Channels** | OpenClaw + Switch channel bridge (`/channels`) |
| (none) | **Skills** | Chops-style skill library (`/skills`) |
| (none) | **Marketplace** | Agent/skill registry (`/marketplace`) |
| (none) | **Cost** | Cost dashboard (`/cost`) |
| (none) | **Policies & Approvals** | Harden-style policy editor + approval queue (`/policies`) |
| (none) | **Adapters** | Claude Code, Codex, Cursor, Goose, Hermes |
| (none) | **Diagrams** | ArchitectGPT-style architecture diagrams (`/modes/diagrams`) |
| (none) | **Benchmarks** | Local model performance |
| (none) | **Rooms** | Switch-style team collaboration |
| (none) | **Settings** | Providers, keychain, models (`/settings`) |
| Projects | **Projects / Workspaces** | Same + git history + agent activity (`/projects`) |
| Chats | **Chats** | Same + search + agent tags |
| OpenClaw-8Zw item | **Agent instances** in sidebar | Multiple agent instances listed |

### Revised Sidebar for Agent Engine

```
┌─────────────────────────────────────┐
│  [AE]   [<<]                        │
│                                     │
│  [+ New Chat]         Ctrl K        │
│                                     │
│  ◯ My Agent                         │
│  ◯ Scheduled Tasks                  │
│  ⚡ Swarm                            │
│  🔀 Workflows                       │
│                                     │
│  ── MODES ──                        │
│  💻 Code                            │
│  🔍 Deep Research                   │
│  📄 Docs                            │
│  📊 Sheets                          │
│  ▢ Slides                           │
│  🌐 Websites                        │
│  🎨 Design                          │
│  📐 Diagrams                        │
│                                     │
│  ── AGENTS ──                       │
│  🦀 Channels (OpenClaw/Switch)      │
│  🧩 Adapters (Claude, Codex, Goose) │
│  🏢 Rooms (Team collaboration)      │
│                                     │
│  ── LIBRARY ──                      │
│  🛠 Skills                          │
│  🛒 Marketplace                     │
│                                     │
│  ── OPERATIONS ──                   │
│  💰 Cost                            │
│  🛡 Policies & Approvals            │
│  📊 Benchmarks                      │
│                                     │
│  ──────────────────                 │
│  PROJECTS                           │
│  + New project                      │
│  ▢ Organiser                        │
│  ▢ Client Website                   │
│                                     │
│  ──────────────────                 │
│  CHATS                              │
│  • Saturday Party Planning          │
│  • Invoice March 2026               │
│  • Book Chapter 4                   │
│                                     │
│  ──────────────────                 │
│  [👤] Nadir          ⚙  ⬇          │
└─────────────────────────────────────┘
```

---

## Part 4 — Screen-by-Screen Design Specification for Gemini

Each screen corresponds to specific tasks across Phase 3, Phase 4, Phase 7, and Phase 15.

### Screen 1 — Home (Default Chat Mode)
- **Route:** `/`
- **Task:** 3.1
- **Layout:**
  - Center canvas, vertically stacked, max-width 760px
  - Logo at top (small, muted)
  - Large greeting: "Good morning, Nadir" or mode-specific title
  - **Universal Input Box** (component `ChatInput`) — see Screen 11
  - **Quick Action Chips** below input: Swarm, Workflows, Deep Research, Docs, Sheets, Diagrams
  - **Featured Cases Grid** — 3 cards, "Explore inspiration" section
  - **Recent Projects row** — horizontal scroll of 4 project cards
- **Empty state content:**
  - Chip row: `Swarm · Workflows · Deep Research · Docs · Sheets · Diagrams · Code`
  - Featured cards:
    1. "Build an invoice agent" (business case)
    2. "Write a book chapter" (author case)
    3. "Analyze a codebase" (dev case)
    4. "Plan a marketing launch" (workflow case)
  - Inspiration footer: "Scroll to explore"
- **Acceptance criteria:**
  - Streaming tokens render at 60fps
  - Input remembers last mode/model/project
  - `Ctrl+K` focuses input from any screen

---

### Screen 2 — My Agent (Identity, Memory, Growth)
- **Route:** `/agent`
- **Task:** 3.7
- **Layout:**
  - **Header:** `{User}'s Agent` — e.g., "Nadir's Agent"
  - **Stats strip:** days active · total sessions · current streak · total cost saved vs frontier
  - **Tabs:** `Closeness` / `Growth` / `Memory` / `Cost`
  - **Closeness tab:** GitHub-style contribution heatmap (12 months), hover shows daily session count
  - **Growth tab:** capability visualization — which skills/agents have been used, which are new
  - **Memory tab:** list of observational memories with edit/delete, importance score
  - **Cost tab:** inline mini cost dashboard (links to full Cost screen)
  - **Self-growth toggle:** "Enable self-growth" — when on, agent learns preferences and habits across sessions
  - **Neural visualization:** animated dots showing memory network — subtle, non-distracting
- **Acceptance criteria:**
  - Heatmap loads in <200ms for 365 days
  - Memory list searchable, editable inline
  - Toggle persists per-user
  - Stats update in real-time after each session

---

### Screen 3 — Scheduled Tasks
- **Route:** `/tasks`
- **Task:** 3.8
- **Layout:**
  - **Header:** "Scheduled Tasks" + "Create ▾" dropdown button (top right)
  - **Subtitle:** "Let your agent run tasks on schedule and deliver results automatically"
  - **Empty state:** Calendar illustration + "Create a scheduled task" + "Add manually or Create via chat" links
  - **Populated state:** Table/card list — name, schedule (cron preview in human language), agent, last run, next run, status
  - **Create dropdown options:** "Manually" / "Via chat" / "From template"
- **Templates to include:**
  - "Daily inbox digest at 8 AM"
  - "Weekly expense report Sunday 6 PM"
  - "Hourly code audit on save"
  - "Monthly book progress summary"
- **Acceptance criteria:**
  - Cron expression builder with plain-English preview
  - Tasks run off-peak by default (Law 7)
  - Failure sends notification via Channel adapter
  - Each task shows cost-per-run and monthly estimate

---

### Screen 4 — Swarm (Multi-Agent)
- **Route:** `/swarm`
- **Task:** 7.4
- **Layout:**
  - **Header:** "Swarm" + subtitle "Assign a task to your AI team"
  - **Input box** with `Swarm` mode chip and `Swarm High` model selector
  - **Featured Swarm cases** — 3 cards showing multi-agent outputs:
    1. "Build & deploy an API" — 4 agents (architect, coder, tester, deployer)
    2. "Deep code review" — 3 agents (security, lint, fix)
    3. "Market research report" — 4 agents (search, analyst, writer, editor)
- **Behavior:**
  - Swarm runs N pipelines in parallel; results merged
  - Each agent's progress shown as a live progress strip
  - Final output aggregated with attribution per agent
- **Acceptance criteria:**
  - Parallel execution respects cost router (each agent uses cheapest tier)
  - Partial failures don't kill the swarm
  - Cost shown per agent before run ("Estimated: $0.04")

---

### Screen 5 — Workflows
- **Route:** `/workflows`
- **Task:** 7.2 & 7.5
- **Layout:**
  - **List view:** saved workflows + "New workflow" button
  - **Editor view:** React Flow canvas
  - **Left palette:** Pipelines, Skills, Agents, Gates (human approval), Conditions, Parallel, Merge
  - **Right inspector:** selected node config
  - **Top bar:** Save, Run, Validate, Export YAML
- **Acceptance criteria:**
  - Round-trip YAML ↔ canvas lossless
  - Dry-run mode shows path without executing
  - Human gates show as pause nodes

---

### Screen 6 — Mode Pages (Code, Deep Research, Docs, Sheets, Slides, Websites, Design, Diagrams)
- **Routes:** `/modes/{mode}`
- **Tasks:** 3.1 & 3.10
- **Mode-specific content:**
  | Mode | Tagline | Featured Cases |
  |---|---|---|
  | Code | "Ship code with a local-first coding agent" | Code review, refactor, test generation |
  | Deep Research | "Ask your agent for an in-depth research report" | Silicon history, market analysis, academic paper |
  | Docs | "Write and edit documents grounded in your files" | Contract review, technical spec, essay |
  | Sheets | "Upload a spreadsheet or create from scratch" | Bibliometric graph, financial panorama, health dashboard |
  | Slides | "Turn your ideas into stunning slides in minutes" | Annual report, pitch deck, academic presentation |
  | Websites | "Build a site in minutes" | Portfolio, SaaS landing, docs site |
  | Design | "Design UI and visuals" | App mockup, brand kit, icon set |
  | Diagrams | "Describe an app in one line, get an architecture diagram" | Microservices, data pipeline, AI stack |
- **Acceptance criteria:**
  - Every mode uses the same `ChatInput` component
  - Switching modes preserves chat history
  - Mode-specific skills load automatically

---

### Screen 7 — Channels (OpenClaw + Switch)
- **Route:** `/channels`
- **Task:** 5B.1–5B.3, 5C.1–5C.4
- **Layout:**
  - **Tabs:** Personal (OpenClaw) | Team (Native collaboration)
  - **Personal tab:** list of connected channels — WhatsApp, Telegram — each with status, last message, agent binding
  - **Team tab:** Slack, Teams, Discord, Mattermost — each with workspace, channels, roles synced
  - **Connect button** per channel — OAuth or token flow
  - **Agent binding** — each channel maps to an agent instance
- **Acceptance criteria:**
  - Adding a channel works in <2 minutes
  - Test message button verifies connection
  - Role sync visible in UI

---

### Screen 8 — Skills Library
- **Route:** `/skills`
- **Task:** 6.1–6.5
- **Layout:**
  - **Top tabs:** `Installed` | `Registry` | `Collections`
  - **Left filter:** source tool (Claude Code, Cursor, Codex, Goose, Agent Engine native)
  - **Main grid:** skill cards — name, description, source, version, author
  - **Editor panel:** Monaco editor with frontmatter parsing
  - **Search bar:** full-text + tag filters
- **Acceptance criteria:**
  - Editing a skill writes to correct per-tool path
  - Registry install works in <10s
  - Remote discovery works via SSH/API

---

### Screen 9 — Marketplace
- **Route:** `/marketplace`
- **Task:** 12.4
- **Layout:**
  - **Hero section:** featured agents this week
  - **Category tabs:** Productivity, Finance, Code, Research, Writing, Design, Enterprise
  - **Agent grid:** card with icon, name, author, rating, installs, price (free/paid)
  - **Detail page:** description, screenshots, version history, reviews, install button
  - **Installed tab:** your installed agents
- **Acceptance criteria:**
  - Install in <60s
  - License validation for paid agents
  - Security audit scan runs automatically before install

---

### Screen 10 — Cost Dashboard
- **Route:** `/cost`
- **Task:** 4.9 & 9.5
- **Layout:**
  - **Top metrics:** this month's spend, forecast, savings vs frontier-only baseline
  - **90/9/1 split chart:** donut showing distribution across CODE/CACHE/SMALL/MID/FRONTIER
  - **Cost per task type:** bar chart
  - **Cache hit rate:** line chart
  - **Distillation candidates:** list of tasks > 10k/month with "distill now" button
  - **Budget alerts:** set monthly ceiling per project/agent
  - **Export:** CSV / JSON
- **Acceptance criteria:**
  - Numbers match sidecar `/v1/telemetry/cost`
  - Alerts fire at 80% and 100% of budget
  - Distill button triggers Task 9.3 pipeline

---

### Screen 11 — Universal Chat Input (The Core Component)
- **Component:** `ChatInput.tsx` (Task 3.9)
- **Used in:** Every screen
- **Anatomy:**
```
┌──────────────────────────────────────────────────────────────┐
│  [Placeholder — mode-specific]                               │
│                                                              │
│  [+]                     [Model ▾]              [↑ Send]     │
├──────────────────────────────────────────────────────────────┤
│  [Project ▾]   [plugin icons]   [Plugins ▾]                  │
└──────────────────────────────────────────────────────────────┘
```
- **Props interface:**
```typescript
interface ChatInputProps {
  mode: Mode;                    // 'chat' | 'swarm' | 'code' | ...
  placeholder?: string;          // defaults to mode-specific
  model: ModelTier;              // 'instant' | 'k3' | 'swarm-high' | ...
  projectId?: string;
  plugins: Plugin[];
  onSend: (message: string, options: SendOptions) => void;
  onModeChange: (mode: Mode) => void;
  onModelChange: (model: ModelTier) => void;
  onProjectChange: (projectId: string) => void;
}
```
- **Features:**
  - `Ctrl+K` global focus
  - Slash commands (`/skill`, `/agent`, `/workflow`)
  - `@` mentions for files, projects, agents
  - Drag-drop file attachments
  - Paste image support
  - Enter to send, Shift+Enter for newline
  - Streaming stop button (replaces send while streaming)
  - Token cost preview above send button
  - Inline error banner if model unavailable
- **Acceptance criteria:**
  - 60fps on 10,000-char input
  - Attachments upload progressively
  - Cost preview accurate to ±5%

---

### Screen 12 — Policies & Approvals
- **Route:** `/policies`
- **Task:** 4.4 & 4.6
- **Layout:**
  - **Tabs:** `Policies` | `Approval Queue` | `Audit Log`
  - **Policies tab:** YAML editor + rule builder + test playground
  - **Approval Queue:** pending tool calls with risk score, diff, context, Approve/Reject/Edit
  - **Audit Log:** searchable, exportable, tamper-evident
- **Acceptance criteria:**
  - Policy changes take effect without restart
  - Approval action executes within 500ms
  - Audit log immutable

#### Shared Component: `ApprovalCard.tsx` (Task 3.3)
- **File:** `apps/desktop/src/renderer/components/ApprovalCard.tsx`
- **Purpose:** Universal inline confirmation card rendered in conversation streams (`Message.tsx`) and Screen 12 queues when dangerous or high-risk tool calls are intercepted.
- **Key Features:**
  - **Risk Badges:** Color-coded glowing risk indicators (`critical` in red, `high` in amber, `medium` in yellow, `low` in emerald) with numeric risk scores (e.g. `95%`).
  - **Diff Preview Engine:** Line-by-line syntax-highlighted diffs for code/file edits (`+` additions in green, `-` deletions in red), terminal command preview boxes with `$ ` prompts, and SQL query inspector.
  - **Action Trio:** `Approve & Execute` (<500ms resolution SLA), `Reject` (with optional operator reason dialog), and `Edit Payload` (inline JSON argument editor with instant re-validation).
  - **Audit Ledger Integration:** Persists operator human decisions directly into SQLite/Postgres audit logs via `POST /v1/safety/approval` and displays immutable audit stamps (`#aud-<id>`).

---

### Screen 13 — Projects (Workspaces)
- **Route:** `/projects`
- **Task:** 4.1
- **List view:** grid of project cards — icon, name, last activity, agents active, thread count
- **Detail view (Organiser):**
  - Project name as title
  - Thread list with preview
  - **Right panel:**
    - **Instructions** — persistent system prompt
    - **Files** — attached files referenced across threads
    - **Agents** — active adapters in project
    - **Policy** — project-scoped policy override
    - **Cost** — project-scoped cost summary
  - **Bottom input** — chat scoped to project
- **Create project flow:**
  - Centered modal
  - "Keep one topic in one place" subtitle
  - Icon picker carousel
  - Name input
  - Optional: bind to git repo, bind to agent, set policy

---

### Screen 14 — Settings
- **Route:** `/settings`
- **Task:** 4.8
- **Tabs:**
  - **Providers** — API keys (keychain-backed), test connection
  - **Models** — default tier per task type
  - **Local Runtime** — Ollama / llama.cpp config, context size, GPU usage
  - **Adapters** — enable/disable Claude Code, Codex, Goose, Cursor, etc.
  - **Channels** — OpenClaw, WhatsApp, Telegram, Slack tokens
  - **Storage** — SQLite path, Postgres URL, cloud sync
  - **Security** — AES key, policy defaults, sandbox toggle
  - **Appearance** — theme, density, font
  - **About** — version, update channel, diagnostics export

---

## Part 5 — Design System (Tokens Gemini Must Use)

### Colors (Dark Theme Default)
```css
--bg-base:        #0a0a0a;   /* page background */
--bg-elevated:    #141414;   /* cards, input */
--bg-hover:       #1c1c1c;   /* hover state */
--border-subtle:  #1f1f1f;   /* hairlines */
--border-strong:  #2a2a2a;   /* input borders */
--text-primary:   #f5f5f5;
--text-secondary: #a0a0a0;
--text-tertiary:  #666666;
--accent:         #3b82f6;   /* primary blue */
--accent-hover:   #2563eb;
--success:        #10b981;
--warning:        #f59e0b;
--danger:         #ef4444;
--code-bg:        #1a1a1a;
```

### Typography
- **UI:** Inter or Geist Sans, 14px base, 1.5 line-height
- **Code:** JetBrains Mono or Geist Mono, 13px
- **Headers:** same family, 1.25× / 1.5× / 2× scale
- **No serif fonts anywhere**

### Spacing
- Base unit: 4px
- Scale: 4, 8, 12, 16, 24, 32, 48, 64
- Sidebar width: 280px
- Chat max-width: 760px
- Input max-width: 760px

### Component Build Order
1. `Sidebar` — nav + projects + chats + footer
2. `ChatInput` — universal input (Screen 11)
3. `Message` — streaming markdown, code, tables, images
4. `ApprovalCard` — inline approval (Screen 12)
5. `ModePage` — reusable mode template
6. `FeaturedGrid` — cards for empty states
7. `ProjectCard` — project tile
8. `AgentCard` — agent instance tile
9. `SkillCard` — skill tile
10. `MetricCard` — KPI tile
11. `Chart` — line, bar, donut (Recharts)
12. `Modal` — create/confirm dialogs

### Motion & Accessibility
- Transitions: 150ms ease-out for hovers, 250ms for panels
- No bouncy springs, no excessive animation
- Streaming text: no per-character animation (feels sluggish)
- Loading: subtle pulsing dots, never spinners >2s
- WCAG 2.1 AA minimum; keyboard navigable everywhere (`Ctrl+K` global palette)
- Focus rings visible; screen reader labels on all icons; reduced-motion respects OS setting

---

## Part 6 — Instructions for Gemini (How to Build)

### Gemini's Role
Gemini implements the Agent Engine GUI **one screen at a time**:
1. Read the screen spec (Part 4).
2. Check dependencies (Phase tasks it depends on).
3. Build the component in `apps/desktop/src/renderer/`.
4. Use the design system tokens (Part 5).
5. Reuse `ChatInput`, `Message`, `Sidebar`, `ApprovalCard` — **never duplicate**.
6. Add Playwright E2E test.
7. Verify acceptance criteria.
8. Update `docs/GUI.md` with screenshots.

### File Structure
```
apps/desktop/src/
├── renderer/
│   ├── App.tsx                     # Router
│   ├── shell/
│   │   ├── Sidebar.tsx
│   │   ├── TopBar.tsx
│   │   └── Layout.tsx
│   ├── components/                 # Reusable
│   │   ├── ChatInput.tsx
│   │   ├── Message.tsx
│   │   ├── ApprovalCard.tsx
│   │   ├── FeaturedGrid.tsx
│   │   ├── MetricCard.tsx
│   │   ├── Chart.tsx
│   │   └── Modal.tsx
│   ├── screens/
│   │   ├── Home.tsx
│   │   ├── Agent.tsx
│   │   ├── Tasks.tsx
│   │   ├── Swarm.tsx
│   │   ├── Workflows.tsx
│   │   ├── Modes/
│   │   │   ├── Code.tsx
│   │   │   ├── DeepResearch.tsx
│   │   │   ├── Docs.tsx
│   │   │   ├── Sheets.tsx
│   │   │   ├── Slides.tsx
│   │   │   ├── Websites.tsx
│   │   │   ├── Design.tsx
│   │   │   └── Diagrams.tsx
│   │   ├── Channels.tsx
│   │   ├── Skills.tsx
│   │   ├── Marketplace.tsx
│   │   ├── Cost.tsx
│   │   ├── Policies.tsx
│   │   ├── Projects.tsx
│   │   ├── ProjectDetail.tsx
│   │   └── Settings.tsx
│   ├── state/
│   │   ├── sessions.ts
│   │   ├── projects.ts
│   │   ├── agents.ts
│   │   ├── skills.ts
│   │   └── settings.ts
│   └── api/
│       └── client.ts               # Typed client for sidecar API
```

### Rules for Gemini
1. **One screen per PR.** Never mix screens in one PR.
2. **Reuse `ChatInput`** in every screen.
3. **Follow Kimi's pattern:** sidebar + main canvas. No floating windows.
4. **Every mode landing page has featured cards.** Never ship an empty state without examples.
5. **Dark theme is default.** Light theme is Phase 15.
6. **No emojis in UI copy.** Use icons from Lucide.
7. **Keyboard first:** `Ctrl+K`, `Ctrl+N`, `Ctrl+/`, `Esc`.
8. **No custom fonts.** Inter + JetBrains Mono only.
9. **Every screen must have E2E test.** Playwright.
10. **Every screen must have loading, empty, error, and populated states.**
11. **Use the sidecar API** — never call models directly from the renderer.
12. **Respect the cost guide:** every screen that triggers a model call must show a cost estimate before execution.
13. **Every action that could be dangerous** must show an approval card inline.
14. **No new dependencies without ADR.**
15. **Update `docs/GUI.md`** with each new screen, including a screenshot and a 3-line description.

### Definition of Done (GUI Task)
- [ ] Screen implemented at the correct route
- [ ] Uses design system tokens
- [ ] Reuses `ChatInput`, `Message`, `Sidebar` where applicable
- [ ] Loading, empty, error, populated states all implemented
- [ ] Keyboard navigation works
- [ ] Screen reader labels present
- [ ] Playwright E2E test passes
- [ ] Cost estimate shown before any model call
- [ ] Approval card shown for dangerous actions
- [ ] Screenshot added to `docs/GUI.md`
- [ ] No console errors or warnings
- [ ] Cross-platform build passes (Win/Mac/Linux)

---

## Part 7 — Updated Master Plan Additions

### Phase 3 (extended) — Kimi-Style GUI
- **Task 3.7** — My Agent screen (identity, memory, growth)
- **Task 3.8** — Scheduled Tasks screen
- **Task 3.9** — Universal Chat Input component
- **Task 3.10** — Mode landing page template
- **Task 3.11** — Featured cases content curation

### Phase 4 (extended) — Dashboard
- **Task 4.8** — Settings screen
- **Task 4.9** — Cost dashboard (react version, replaces Streamlit tab)
- **Task 4.10** — Remove Streamlit from user-facing build

### Phase 7 (extended) — Workflows
- **Task 7.4** — Swarm screen
- **Task 7.5** — Workflow builder screen

### Phase 15 (new) — Light Theme & Accessibility Polish
- **Task 15.1** — Light theme
- **Task 15.2** — High-contrast mode
- **Task 15.3** — Reduced motion mode
- **Task 15.4** — Full keyboard shortcut system

---

## Part 8 — Final Architectural Synthesis

**1. Should we keep both dashboards?**
**No.** Streamline to **one Tauri shell**. Demote Streamlit to `make dev` only. This is a hard architectural decision, not a preference.

**2. Can it be a base for any agent — email, personal finance, company finance, author study?**
**Yes.** The GUI structure proves it: Kimi's mode-based sidebar is exactly the pattern for **any vertical**:
- Email agent → "Inbox" mode
- Personal finance → "Finance" mode
- Company finance → "Company Finance" mode (with RBAC overlay from Phase 11)
- Author → "Writing" mode + "Research" mode
- Study → "Study" mode with RAG over PDFs

Each mode uses the same shell, the same input, the same chat history, the same project system. The only differences are the skills, pipelines, and policies bound to each mode. **Adding a new vertical is a new mode + new skills, not a new app.**
