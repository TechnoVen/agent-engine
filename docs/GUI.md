# Agent Engine — Canonical GUI & Interaction Architecture

**Status:** Canonical product interface specification  
**Supersedes:** The earlier Kimi-inspired GUI document as the primary design authority  
**Purpose:** Define a professional, non-gimmicky desktop interface for Agent Engine that feels like a mature operating environment rather than a generic AI chat product.

---

# 1. Product Design Position

Agent Engine should not visually present itself as “an AI app.”

It should feel closer to:

- a professional IDE;
- a modern research workspace;
- a document and data workbench;
- a reliable operations console;
- a native desktop productivity environment.

AI is an implementation detail. The interface should communicate **work, context, control, provenance, and execution state**.

The user should not have to think in terms of:

- models;
- prompts;
- swarms;
- agents everywhere;
- neural networks;
- magic buttons;
- glowing AI states;
- “growth” gamification.

Those concepts may exist internally or in Developer Mode, but the default product should feel calm, precise, and useful.

---

# 2. Core Design Principles

## 2.1 Work first, AI second

Primary navigation should describe what the user wants to do:

```text
Home
Projects
Tasks
Automations
Knowledge
Developer
Research
Writing
Data
```

not which AI subsystem is responsible.

Avoid making the user choose between agent concepts before starting work.

---

## 2.2 Restraint over spectacle

Avoid:

- neon glows;
- gradients used as decoration;
- animated “thinking” orbs;
- neural-network visualizations;
- oversized hero cards;
- glassmorphism;
- excessive pills/chips;
- multicolor icon walls;
- anthropomorphic “relationship” metrics;
- arbitrary badges on every surface.

Use:

- neutral surfaces;
- clear alignment;
- consistent spacing;
- subtle depth;
- single accent color;
- typography and layout for hierarchy;
- color only for meaning.

---

## 2.3 Desktop density, not SaaS-card density

Agent Engine is a desktop work environment.

Favor:

- split panes;
- lists;
- tables;
- sidebars;
- inspectors;
- activity drawers;
- command palettes;
- context panels;

over dashboards made of large floating cards.

Cards should exist only when they represent discrete entities such as projects, packages, or templates.

---

## 2.4 Show system state without exposing internals

The user should be able to understand:

```text
Ready
Running
Waiting for approval
Paused
Failed
Offline
Degraded
```

without needing to know which framework or provider produced the state.

Technical detail remains available through disclosure.

---

## 2.5 Progressive disclosure

Use three interface levels:

### Standard

For everyday work.

### Advanced

Shows:

- models;
- execution details;
- context sources;
- skills;
- cost;
- approvals.

### Developer

Shows:

- DSPy;
- MCP;
- ACP;
- traces;
- workflow internals;
- provider details;
- policy evaluation;
- runtime logs.

The main UI must remain useful with all advanced panels hidden.

---

# 3. Visual Character

## 3.1 Desired character

Agent Engine should feel:

```text
quiet
serious
precise
fast
local
technical
trustworthy
desktop-native
```

Reference qualities:

- VS Code density;
- Linear precision;
- Arc/Raycast restraint;
- modern native macOS/Linux utility apps;
- professional financial/research terminals;
- high-quality developer tools.

Do not imitate their branding directly.

---

## 3.2 Avoid “AI app” clichés

Do not use:

```text
sparkle icons for AI
purple/blue gradients
glowing borders
brain icons
neural illustrations
magic wand imagery
robot avatars
animated constellation backgrounds
```

Do not label ordinary operations as “AI-powered.”

---

# 4. Information Architecture

The previous GUI grew from feature-by-feature development and exposes too many implementation concepts in the main sidebar.

The canonical sidebar should instead be organized around user work.

## 4.1 Primary Navigation

```text
┌───────────────────────────────┐
│ AE  Agent Engine         [⌘K] │
│                               │
│ + New                         │
│                               │
│ WORK                          │
│ Home                          │
│ Projects                      │
│ Tasks                         │
│ Automations                   │
│                               │
│ TOOLS                         │
│ Research                      │
│ Writing                       │
│ Data                          │
│ Developer                     │
│                               │
│ LIBRARY                       │
│ Knowledge                     │
│ Skills                        │
│                               │
│ SYSTEM                        │
│ Activity                      │
│ Approvals                     │
│ Models                        │
│                               │
│ ───────────────────────────   │
│ Recent                        │
│ Agent Engine                  │
│ THE DEN                       │
│ Writing                       │
│                               │
│ Nadir                    [⚙]  │
└───────────────────────────────┘
```

### Why this is better

It removes internal concepts such as:

- Swarm;
- Adapters;
- Rooms;
- Channels;
- Benchmarks;
- Marketplace;

from the default mental model.

Those features still exist, but appear where they belong:

| Old navigation concept | Canonical location |
|---|---|
| Swarm | Teams inside Automations / Developer |
| Workflows | Automations |
| Channels | Settings → Connections |
| Adapters | Settings → Integrations |
| Rooms | Shared Projects / Team features |
| Marketplace | Skills → Browse |
| Cost | Activity → Usage |
| Policies | Approvals / Settings → Security |
| Benchmarks | Models → Diagnostics |
| Diagrams | Developer / Writing tools |
| Slides | Writing / Documents tools |
| Websites | Developer |
| Design | Writing/Creative pack or installed capability |

---

# 5. Shell Architecture

## 5.1 Left Sidebar

Default width:

```text
240px
```

Collapsed width:

```text
52px
```

Avoid the previous 280px default unless labels require it.

The sidebar should be calm and low-contrast.

Section headings use 11px uppercase tracking, not decorative separators.

No emoji.

Use Lucide icons at 16px.

---

## 5.2 Top Bar

The top bar should be very restrained.

Default:

```text
Project / location breadcrumb               System status
```

Example:

```text
Agent Engine / Workflows / Security Review          Ready
```

Do not permanently show:

```text
VRAM
tokens/sec
CPU
RAM
model tier
cost
```

in the global top bar.

Those metrics make the app feel like a model demo.

Instead provide a single system-state indicator:

```text
Ready
Busy
Offline
Degraded
```

Clicking it opens the System Status popover with detailed metrics.

---

## 5.3 Main Canvas

Main content should usually use one of four patterns:

1. **Conversation**
2. **List + Inspector**
3. **Canvas + Inspector**
4. **Document/Editor + Context Panel**

Avoid using a grid of cards simply because a screen is empty.

---

# 6. Home

## 6.1 Purpose

Home is a launch surface, not a marketing landing page.

Avoid:

- giant logo;
- “Explore inspiration” carousel;
- showcase cards;
- slogans.

Use:

```text
Good morning, Nadir
What are you working on?
```

Below:

```text
[ Large command/input surface ]
```

Then two compact sections:

```text
Recent work
Pinned projects
```

Optional contextual shortcuts:

```text
Research
Write
Analyze data
Work on code
```

Use text + icon rows, not promotional cards.

---

## 6.2 Example

```text
Good morning, Nadir

┌──────────────────────────────────────────────────┐
│ Ask, open a project, or describe a task...       │
│                                                  │
│ Attach   Project: Agent Engine        Run        │
└──────────────────────────────────────────────────┘

Recent work
────────────────────────────────────────────────────
Agent Engine architecture review         18 min ago
THE DEN opening checklist                 Yesterday
Article draft: Local AI                  2 days ago

Pinned projects
────────────────────────────────────────────────────
Agent Engine
THE DEN
Writing
```

---

# 7. Universal Input

The universal input remains important but should look like a command surface, not a chat toy.

## 7.1 Structure

```text
┌────────────────────────────────────────────────────────┐
│ Ask, describe a task, or type / for commands...        │
│                                                        │
│ [Attach]  Project: Agent Engine       [Model ▾] [Run] │
└────────────────────────────────────────────────────────┘
```

Use a simple rectangular surface.

Radius:

```text
8px
```

not 16–24px.

Avoid:

- floating chips inside chips;
- colored mode pills;
- multiple plugin avatars;
- glowing send buttons.

---

## 7.2 Model selection

Model choice is secondary.

Default display:

```text
Automatic
```

Advanced options:

```text
Local
Balanced
Best quality
Specific model...
```

Do not expose internal names such as:

```text
K3 Swarm High
Instant High
```

unless in Developer Mode.

---

## 7.3 Cost

Do not put cost estimates permanently beside every send button.

Default:

```text
Automatic · Local preferred
```

When meaningful:

```text
Estimated cloud cost: €0.04
```

Show it only if the task is expected to use paid cloud inference.

---

# 8. Projects

Projects should feel like real workspaces.

## 8.1 Project page layout

```text
┌─────────────────────────────────────────────────────────────┐
│ Agent Engine                             [•••]              │
│ Local repository · Active today                              │
├────────────────────────────┬────────────────────────────────┤
│ Work                       │ Project context                │
│                            │                                │
│ Sessions                   │ Instructions                   │
│ Documents                  │ Files                          │
│ Tasks                      │ Repository                     │
│ Automations                │ Connected sources              │
│                            │                                │
├────────────────────────────┴────────────────────────────────┤
│ Ask about this project...                                   │
└─────────────────────────────────────────────────────────────┘
```

Right panel should be collapsible.

Do not turn project metadata into many cards.

---

# 9. Tasks

Scheduled and one-off work belong under **Tasks**.

Use a table by default:

| Task | Schedule | Project | Last run | Next run | Status |
|---|---|---|---|---|---|

Do not use large colorful status cards.

Statuses use subtle text + icon:

```text
Scheduled
Running
Waiting
Failed
Paused
```

---

# 10. Automations

Rename the former Workflows area to **Automations** in Standard Mode.

Inside:

```text
Automations
├── Workflows
├── Schedules
└── Teams
```

Developer Mode may expose the exact concepts.

---

# 11. Workflow Builder

The existing workflow builder is one of the strongest interfaces and should largely remain.

## 11.1 Preserve

- dark canvas;
- node palette;
- inspector;
- graph connections;
- Validate;
- YAML/source;
- Dry Run;
- Run;
- Save.

## 11.2 Visual refinement

Nodes should resemble a professional graph editor.

Avoid:

- bright type badges;
- glowing node outlines;
- excessive color coding.

Use a neutral node:

```text
┌──────────────────────────────┐
│ Query Analyzer               │
│ Agent                        │
│                              │
│ Parses request and context   │
└──────────────────────────────┘
```

Node type is secondary metadata.

Use color only for runtime status:

```text
running    blue
success    green
waiting    amber
failed     red
```

At rest, nodes are monochrome.

---

## 11.3 Palette

Group nodes by purpose:

```text
Logic
  Condition
  Parallel
  Join
  Wait

Work
  Program
  Skill
  Agent
  Tool

Control
  Approval
  Human Input
  Subworkflow
```

This is easier to understand than an unstructured list.

---

## 11.4 Runtime states

Node state should be shown through:

- small status dot;
- border;
- compact footer.

Never animate the whole card.

---

# 12. Research

Research should look like a research workspace.

Use:

```text
query / prompt
sources
notes
report
```

Suggested layout:

```text
┌───────────────────────┬───────────────────────────────┐
│ Sources               │ Research report               │
│                       │                               │
│ 12 collected          │ # Market structure            │
│ 8 used                │ ...                           │
│ 3 conflicting         │                               │
│                       │                               │
├───────────────────────┤                               │
│ Notes / claims        │                               │
└───────────────────────┴───────────────────────────────┘
```

Source provenance should be visually more important than “AI activity.”

---

# 13. Writing

Writing should resemble a document editor.

Primary surface:

```text
document
```

Secondary side panel:

```text
outline
sources
comments
versions
```

Conversation remains available but should not dominate the interface.

Avoid presenting all writing as chat output.

---

# 14. Data

Use spreadsheet/table metaphors.

Layout:

```text
dataset/table
filters
analysis panel
chart/output
```

AI suggestions should appear as actions:

```text
Explain anomaly
Create formula
Summarize this selection
Build chart
```

not as an omnipresent assistant persona.

---

# 15. Developer

Developer is the place for advanced system capabilities.

Possible tabs:

```text
Code
Repository
Worktrees
Executions
Tools
Architecture
```

This is also where IDE/ACP/MCP details belong.

---

# 16. Knowledge

Knowledge replaces the idea of a generic RAG screen.

Sections:

```text
Sources
Documents
Project knowledge
User memory
Procedures
```

Each record should show provenance.

Avoid “memory network” diagrams.

---

# 17. Memory

The earlier design used:

- closeness;
- trust;
- streaks;
- neural visualizations;
- growth radar;
- interaction heatmaps.

These features make the product feel anthropomorphic and AI-centric.

Remove them from the main product.

Replace `My Agent` with:

# Profile & Memory

Tabs:

```text
Preferences
Memory
Instructions
Privacy
```

Optional Developer tab:

```text
Memory diagnostics
```

Do not quantify “closeness.”

Do not gamify use with streaks.

Do not visualize memory as neural nodes.

---

# 18. Skills

Skills should feel like installed capabilities, similar to extensions in an IDE.

Use:

```text
Installed
Browse
Updates
```

List or compact grid:

```text
Financial Modeling
Finance · v2.4
Used 18 times · 96% successful

Threat Modeling
Security · v1.9
Used 7 times · 100% successful
```

Primary signals:

- purpose;
- publisher;
- version;
- permissions;
- reliability.

Avoid ratings and marketplace-style hype in the local product.

---

# 19. Marketplace / Browse

Rename default entry to:

```text
Browse
```

inside Skills.

The marketplace itself may exist later, but the UI should resemble a professional extension registry.

Avoid:

- “featured agents this week”;
- hero banners;
- huge install counts;
- consumer app-store appearance.

Use:

```text
Search
Categories
Verified
Installed
Updates
```

---

# 20. Approvals

Approvals are consequential and should look sober.

Do not use:

- glowing red cards;
- pulsing borders;
- giant risk percentages.

Use a plain decision panel:

```text
Approval required

Modify 4 files in Agent Engine

Command
pytest tests/execution -q

Reason
Workflow requested verification after applying patch.

Risk
Medium

Files
core/execution/coordinator.py
...

[Reject]                     [Approve once]
```

Risk is communicated through language, not spectacle.

---

# 21. Activity

Combine:

```text
execution history
cost
audit
system activity
```

into a unified Activity area.

Tabs:

```text
Executions
Usage
Audit
System
```

This avoids separate top-level pages for Cost and Benchmarks.

---

# 22. Usage

Replace the old “90/9/1 Cost Dashboard.”

The old chart is overly theoretical and feels like an AI optimization demo.

Use practical metrics:

```text
Cloud spend this month
Local inference time
Cost by project
Cost by task
Successful task cost
Provider usage
Cache savings
```

Do not show hypothetical savings against an imaginary frontier-only baseline unless clearly labeled as modeled.

---

# 23. Models

Models page:

```text
Models

Local
────────────────────────────────────────
Fast Local             Ready
Balanced Local         Ready
Best Local             Not installed

Cloud
────────────────────────────────────────
OpenAI                 Connected
Anthropic              Connected
Google                 Not connected
```

Advanced panel exposes:

```text
context
VRAM
quantization
latency
tokens/sec
```

Do not make benchmark numbers part of the normal interface.

---

# 24. System Status

The previous global top bar displays too many machine metrics.

Replace with one state:

```text
Ready
Degraded
Offline
Busy
```

Clicking opens:

```text
System Status

Execution service         Ready
Local model               Ready
Database                  Ready
Sandbox                   Ready
Cloud providers           2 connected

Resources
CPU                       24%
Memory                    65%
VRAM                      85%

[Open diagnostics]
```

---

# 25. Settings

Settings should use familiar desktop categories:

```text
General
Appearance
Models
Connections
Storage
Security
Notifications
Developer
About
```

Do not expose architecture terminology in top-level settings.

For example:

```text
Adapters
Channels
Providers
```

all belong under:

```text
Connections
```

---

# 26. Design System

## 26.1 Color palette

Dark theme:

```css
--surface-0: #0d0e10;
--surface-1: #121417;
--surface-2: #181a1e;
--surface-3: #202329;

--border-1: #24272d;
--border-2: #30343b;

--text-1: #f1f3f5;
--text-2: #b5bac1;
--text-3: #777d86;

--accent: #6b8afd;
--accent-hover: #8099ff;

--success: #4fa474;
--warning: #c79a4b;
--danger: #c86464;
```

The accent should appear sparingly.

Avoid pure black `#000` or extreme contrast everywhere.

---

## 26.2 Radius

```text
4px   small controls
6px   buttons
8px   panels/input
10px  large modal maximum
```

Do not use bubbly 16–24px radii.

---

## 26.3 Shadows

Minimal.

Use borders and tonal surface changes before shadows.

No glow shadows.

---

## 26.4 Typography

Recommended:

```text
UI:
Inter / Geist / system sans

Code:
JetBrains Mono / Geist Mono
```

Base:

```text
13px–14px
```

Desktop density should remain compact.

Headings should not become oversized marketing typography.

---

## 26.5 Icons

Use one icon family only.

Recommended:

```text
Lucide
```

Standard sizes:

```text
14
16
18
```

Avoid emojis entirely.

---

# 27. Motion

Motion communicates state, not personality.

Use:

```text
120–160ms hover/focus
180–220ms panels
```

Avoid:

- springy movement;
- floating elements;
- glowing pulses;
- constant animations;
- “AI thinking” waves.

For running executions:

```text
subtle progress indicator
```

For waiting:

```text
static status + elapsed time
```

---

# 28. Empty States

The previous document mandates featured cards on every empty state.

Change this.

Empty states should help the user begin work but remain minimal.

Example:

```text
No automations yet

Automations can run recurring or multi-step work.

[Create automation]

Examples:
Weekly project review
Invoice processing
Morning brief
```

Examples can be simple text rows.

Do not always use promotional card grids.

---

# 29. Copy Style

Use plain professional language.

Avoid:

```text
Meet your AI team
Unlock your potential
Supercharge
Magic
Intelligent
Powerful AI
Your agent is growing
```

Prefer:

```text
Run
Review
Analyze
Create
Schedule
Compare
Open
Continue
```

Status copy must be factual.

---

# 30. Remove Anthropomorphic Product Language

Replace:

```text
My Agent
Nadir's Agent
Closeness
Growth
Self-growth
Agent relationship
```

with:

```text
Profile & Memory
Preferences
Memory
Capabilities
Learning settings
```

Agent identity may still exist internally or for configured specialist agents.

The product itself should not imitate a companion unless the user explicitly creates one.

---

# 31. Canonical Screen Map

```text
Home

Work
├── Projects
├── Tasks
└── Automations
    ├── Workflows
    ├── Schedules
    └── Teams

Tools
├── Research
├── Writing
├── Data
└── Developer

Library
├── Knowledge
└── Skills
    └── Browse

System
├── Activity
│   ├── Executions
│   ├── Usage
│   ├── Audit
│   └── System
├── Approvals
└── Models

Settings
```

Installed capability packs can add tool entries without restructuring the entire application.

---

# 32. Component Architecture

```text
apps/desktop/src/renderer/
├── shell/
│   ├── Sidebar.tsx
│   ├── TopBar.tsx
│   ├── WorkspaceLayout.tsx
│   └── StatusPopover.tsx
│
├── components/
│   ├── CommandInput.tsx
│   ├── Conversation.tsx
│   ├── ApprovalPanel.tsx
│   ├── Inspector.tsx
│   ├── EmptyState.tsx
│   ├── StatusBadge.tsx
│   ├── DataTable.tsx
│   ├── SplitPane.tsx
│   └── Modal.tsx
│
├── screens/
│   ├── Home.tsx
│   ├── Projects/
│   ├── Tasks/
│   ├── Automations/
│   ├── Research/
│   ├── Writing/
│   ├── Data/
│   ├── Developer/
│   ├── Knowledge/
│   ├── Skills/
│   ├── Activity/
│   ├── Approvals/
│   ├── Models/
│   └── Settings/
```

Do not force every screen through one generic `ModePage`.

Shared behavior should come from layout primitives and command/execution infrastructure, not visual sameness.

---

# 33. Refactoring Existing Screens

## Keep nearly as-is

```text
Workflow Builder
Project list/detail
Policy editor foundations
Session search
Document attachments
```

## Restyle / reorganize

```text
Home
Scheduled Tasks
Cost
Skills
Settings
System telemetry
```

## Rename / reposition

```text
Swarm
→ Automations → Teams

My Agent
→ Settings / Profile & Memory

Cost
→ Activity → Usage

Benchmarks
→ Models → Diagnostics

Marketplace
→ Skills → Browse

Channels
→ Settings → Connections

Adapters
→ Settings → Integrations
```

## Remove from default UX

```text
Closeness
streak
neural visualization
growth radar
AI persona badges
90/9/1 donut
frontier-savings vanity metric
always-visible hardware telemetry
always-visible model tier badges
```

---

# 34. Workflow Builder Specific Design

The current Workflow Builder should become the visual benchmark for Agent Engine.

Recommended shell:

```text
Breadcrumb
Automation / Security remediation

Toolbar
Validate | Dry run | Source | Run | Save

────────────────────────────────────────────────────────
Palette |                  Canvas                 | Inspector
```

Keep the dark editor aesthetic.

Reduce chrome around it.

Inspector should use compact forms.

Node details appear only when selected.

Execution details open in a bottom drawer rather than permanently occupying space.

---

# 35. Execution Drawer

Any active operation may open a bottom drawer:

```text
Execution
────────────────────────────────────────
Status        Running
Elapsed       00:18
Project       Agent Engine
Model         Automatic
Steps         3 / 7

Current
Running tests

[Stop]                         [Details]
```

Expanded details may show:

```text
model
tokens
cost
context
tool calls
trace
```

This keeps technical transparency available without making the entire application feel like a model dashboard.

---

# 36. Developer Mode

Developer Mode is where technical depth belongs.

Enable:

```text
Settings → Developer → Developer Mode
```

Then expose:

```text
runtime names
model IDs
DSPy pipelines
MCP servers
ACP state
token counts
context inspector
execution trace
raw events
API endpoints
hardware telemetry
```

This preserves Agent Engine's technical power without making the default interface intimidating.

---

# 37. Accessibility

Minimum:

```text
WCAG 2.2 AA
full keyboard navigation
visible focus
screen reader labels
reduced motion
high contrast
text scaling
```

Keyboard behavior should follow desktop conventions.

Do not overload `Ctrl+K` for both chat focus and global palette.

Recommended:

```text
Ctrl/Cmd + K      Command palette
Ctrl/Cmd + N      New task/chat
Ctrl/Cmd + P      Quick project switcher
Ctrl/Cmd + ,      Settings
Esc               Close / cancel current overlay
```

---

# 38. Product State Language

Canonical state vocabulary:

```text
Ready
Queued
Running
Waiting
Needs approval
Paused
Completed
Partial
Failed
Cancelled
Blocked
Offline
Degraded
```

Use this everywhere.

Do not invent screen-specific synonyms.

---

# 39. Design Governance

Every new screen must answer:

1. What user job does this screen support?
2. Does it need to be a top-level screen?
3. Can it be a panel/tab inside an existing area?
4. Is this showing a product concept or an implementation concept?
5. Is any information decorative rather than actionable?
6. Does the screen still work without animations?
7. Can a professional user understand it without knowing AI terminology?

If not, redesign before implementation.

---

# 40. Gemini Implementation Rules

Gemini should not perform a wholesale UI rewrite.

Apply the redesign incrementally.

Priority:

```text
1. Navigation information architecture
2. Top bar / system status
3. Home
4. Profile & Memory simplification
5. Activity / Usage consolidation
6. Settings consolidation
7. Skills / Browse redesign
8. Workflow visual refinement
9. Tool workspaces
10. Accessibility / polish
```

Preserve working behavior.

Separate layout/refactor commits from execution/runtime changes.

For each change:

```text
inspect existing component
preserve functionality
update component hierarchy
update routes safely
add migration aliases where needed
run Playwright
capture screenshot
compare density/hierarchy
```

---

# 41. Acceptance Standard

The UI succeeds when a new user describes it as:

```text
"workbench"
"desktop app"
"project environment"
"professional tool"
```

rather than:

```text
"AI dashboard"
"chatbot"
"agent demo"
"LLM frontend"
```

That is the intended visual identity of Agent Engine.

---

# 42. Final Direction

Agent Engine should visually express its architecture:

```text
work
context
execution
control
evidence
```

not:

```text
AI
models
agents
prompts
magic
```

The interface should make sophisticated AI infrastructure disappear into a calm, reliable professional environment.

The result should feel like software a developer, researcher, writer, analyst, founder, or business operator could keep open all day—even if the words “AI” and “agent” were removed from most of the interface.
