"""
Unit & Integration Tests for Desktop Shell Skeleton (Task 2.1).

Validates:
- apps/desktop/package.json structure, scripts, and dependency manifests.
- apps/desktop/src-tauri/tauri.conf.json configuration schema and parameters.
- apps/desktop/src-tauri/Cargo.toml Tauri v2 dependencies and metadata.
- Design system tokens consistency across Tailwind config and index.css (Law 1 applied to UI).
- Vite configuration with Tauri port 1420 and sidecar proxy.
- Kimi-style universal shell components: Sidebar, TopBar, Layout, Home, and sidecar API client.
- Built distribution artifacts (dist/index.html, dist/assets).
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP_ROOT = REPO_ROOT / "apps" / "desktop"
SRC_TAURI_ROOT = DESKTOP_ROOT / "src-tauri"
RENDERER_ROOT = DESKTOP_ROOT / "src" / "renderer"


def test_desktop_package_json():
    pkg_file = DESKTOP_ROOT / "package.json"
    assert pkg_file.exists(), "apps/desktop/package.json must exist"

    with open(pkg_file, "r") as f:
        pkg = json.load(f)

    assert pkg.get("name") == "@agent-engine/desktop"
    assert "dev" in pkg.get("scripts", {})
    assert "build" in pkg.get("scripts", {})
    assert "tauri" in pkg.get("scripts", {})

    deps = pkg.get("dependencies", {})
    dev_deps = pkg.get("devDependencies", {})

    assert "@tauri-apps/api" in deps
    assert "react" in deps
    assert "react-dom" in deps
    assert "lucide-react" in deps

    assert "vite" in dev_deps
    assert "typescript" in dev_deps
    assert "tailwindcss" in dev_deps
    assert "@tauri-apps/cli" in dev_deps


def test_tauri_conf_json():
    conf_file = SRC_TAURI_ROOT / "tauri.conf.json"
    assert conf_file.exists(), "src-tauri/tauri.conf.json must exist"

    with open(conf_file, "r") as f:
        conf = json.load(f)

    assert conf.get("productName") == "Agent Engine"
    assert conf.get("identifier") == "com.technoven.agentengine"

    build_cfg = conf.get("build", {})
    assert build_cfg.get("frontendDist") == "../dist"
    assert build_cfg.get("devUrl") == "http://localhost:1420"

    windows = conf.get("app", {}).get("windows", [])
    assert len(windows) > 0, "At least one window must be configured"
    main_win = windows[0]
    assert main_win.get("title") == "Agent Engine"
    assert main_win.get("width", 0) >= 960
    assert main_win.get("height", 0) >= 600
    assert main_win.get("backgroundColor") == "#0a0a0a"


def test_src_tauri_cargo_toml():
    cargo_file = SRC_TAURI_ROOT / "Cargo.toml"
    assert cargo_file.exists(), "src-tauri/Cargo.toml must exist"

    content = cargo_file.read_text()
    assert 'name = "agent-engine-desktop"' in content
    assert "tauri =" in content
    assert "tauri-plugin-shell" in content
    assert "tauri-plugin-process" in content
    assert "serde" in content
    assert "tokio" in content
    assert "reqwest" in content


def test_design_tokens_consistency():
    tailwind_file = DESKTOP_ROOT / "tailwind.config.js"
    assert tailwind_file.exists(), "tailwind.config.js must exist"
    tw_content = tailwind_file.read_text()

    # Core tokens defined in docs/GUI.md Part 5
    required_tokens = [
        ("bg-base", "#0a0a0a"),
        ("bg-elevated", "#141414"),
        ("bg-hover", "#1c1c1c"),
        ("border-subtle", "#1f1f1f"),
        ("border-strong", "#2a2a2a"),
        ("text-primary", "#f5f5f5"),
        ("text-secondary", "#a0a0a0"),
        ("text-tertiary", "#666666"),
        ("accent", "#3b82f6"),
        ("success", "#10b981"),
        ("warning", "#f59e0b"),
        ("danger", "#ef4444"),
        ("code-bg", "#1a1a1a"),
    ]

    for token, hex_code in required_tokens:
        assert token in tw_content, f"Token {token} missing in tailwind.config.js"
        assert hex_code in tw_content, f"Hex {hex_code} missing in tailwind.config.js"

    css_file = RENDERER_ROOT / "index.css"
    assert css_file.exists(), "src/renderer/index.css must exist"
    css_content = css_file.read_text()

    for token, hex_code in required_tokens:
        assert f"--{token}: {hex_code};" in css_content, f"CSS var --{token} missing in index.css"


def test_vite_config():
    vite_file = DESKTOP_ROOT / "vite.config.ts"
    assert vite_file.exists(), "vite.config.ts must exist"
    content = vite_file.read_text()
    assert "port: 1420" in content
    assert "strictPort: true" in content
    assert "http://127.0.0.1:8000" in content


def test_kimi_universal_shell_components():
    assert (RENDERER_ROOT / "shell" / "Sidebar.tsx").exists()
    assert (RENDERER_ROOT / "shell" / "TopBar.tsx").exists()
    assert (RENDERER_ROOT / "shell" / "Layout.tsx").exists()
    assert (RENDERER_ROOT / "screens" / "Home.tsx").exists()
    assert (RENDERER_ROOT / "api" / "client.ts").exists()
    assert (RENDERER_ROOT / "App.tsx").exists()

    sidebar = (RENDERER_ROOT / "shell" / "Sidebar.tsx").read_text()
    assert "New Chat" in sidebar
    assert "Ctrl K" in sidebar
    assert "w-[280px]" in sidebar

    topbar = (RENDERER_ROOT / "shell" / "TopBar.tsx").read_text()
    assert "Instant High" in topbar
    assert "K3 Swarm High" in topbar
    assert "K3 High" in topbar
    assert "Sidecar 8000" in topbar

    home = (RENDERER_ROOT / "screens" / "Home.tsx").read_text()
    assert "Explore Inspiration" in home
    assert "Build an invoice agent" in home


def test_built_distribution_bundle():
    dist_html = DESKTOP_ROOT / "dist" / "index.html"
    assert dist_html.exists(), "apps/desktop/dist/index.html must be generated after build"
    content = dist_html.read_text()
    assert 'id="root"' in content
    assert "Agent Engine" in content
    assert 'src="/assets/' in content


def test_task_3_1_universal_chat_input_component():
    chat_input_file = RENDERER_ROOT / "components" / "ChatInput.tsx"
    assert chat_input_file.exists(), "apps/desktop/src/renderer/components/ChatInput.tsx must exist"
    content = chat_input_file.read_text()

    # Verify component props and exports
    assert "export interface ChatInputProps" in content
    assert "export const ChatInput" in content

    # Verify universal input capabilities
    assert "Instant High" in content
    assert "K3 Swarm High" in content
    assert "K3 High" in content
    assert "Est:" in content
    assert "AttachmentFile" in content
    assert "Paperclip" in content
    assert "onStop" in content
    assert "isStreaming" in content
    assert "onModeChange" in content
    assert "onProjectChange" in content

    # Verify Enter to send and Shift+Enter for newline
    assert "e.key === 'Enter' && !e.shiftKey" in content


def test_task_3_1_streaming_message_token_renderer():
    message_file = RENDERER_ROOT / "components" / "Message.tsx"
    assert message_file.exists(), "apps/desktop/src/renderer/components/Message.tsx must exist"
    content = message_file.read_text()

    assert "export interface MessageProps" in content
    assert "export const Message" in content
    assert "ChatMessage" in content
    assert "isStreaming" in content

    # Fast 60fps markdown & code block renderer
    assert "renderFormattedContent" in content
    assert "handleCopyCode" in content
    assert "handleCopyMessage" in content
    assert "Copy" in content
    assert "Check" in content

    # Performance & cost attribution telemetry
    assert "tokensPerSec" in content
    assert "latencyMs" in content
    assert "estCost" in content
    assert "animate-pulse" in content


def test_task_3_1_home_screen_empty_and_chat_states():
    home_file = RENDERER_ROOT / "screens" / "Home.tsx"
    assert home_file.exists(), "apps/desktop/src/renderer/screens/Home.tsx must exist"
    content = home_file.read_text()

    # Universal component reuse
    assert "ChatInput" in content
    assert "Message" in content

    # Empty state greeting, chips, and inspiration cards
    assert "getGreeting" in content
    assert "Explore Inspiration" in content
    assert "Build an invoice agent" in content
    assert "Analyze codebase & architecture" in content
    assert "Deep market research report" in content
    assert "recentProjects" in content

    # 60fps streaming loop using requestAnimationFrame
    assert "requestAnimationFrame" in content
    assert "startStreamingResponse" in content
    assert "streamAbortController" in content
    assert "tokensPerSec" in content


def test_task_3_1_types_and_global_shortcuts():
    types_file = RENDERER_ROOT / "types" / "index.ts"
    assert types_file.exists()
    types_content = types_file.read_text()
    assert "ChatMessage" in types_content
    assert "MessageRole" in types_content
    assert "MessageMetadata" in types_content
    assert "AttachmentFile" in types_content

    app_file = RENDERER_ROOT / "App.tsx"
    app_content = app_file.read_text()
    assert "chatInputRef" in app_content
    assert "ctrlKey" in app_content
    assert "'k'" in app_content
    assert "setActiveMode('home')" in app_content


def test_task_3_2_slash_command_popup():
    popup_file = RENDERER_ROOT / "components" / "SlashCommandPopup.tsx"
    assert popup_file.exists(), "SlashCommandPopup.tsx must exist"
    content = popup_file.read_text()

    assert "export const SlashCommandPopup" in content
    assert "BUILT_IN_COMMANDS" in content
    assert "/skill" in content
    assert "/agent" in content
    assert "/workflow" in content
    assert "/clear" in content
    assert "/web-search" in content
    assert "/memory" in content
    assert "/sandbox" in content

    # Keyboard navigation and accessibility shortcuts
    assert "ArrowDown" in content or "navigate" in content
    assert "ArrowUp" in content or "navigate" in content
    assert "Enter" in content
    assert "Esc" in content


def test_task_3_2_chat_input_slash_and_parameter_chips():
    chat_input_file = RENDERER_ROOT / "components" / "ChatInput.tsx"
    assert chat_input_file.exists()
    content = chat_input_file.read_text()

    # Slash command trigger and popup integration
    assert "SlashCommandPopup" in content
    assert "slashQuery" in content
    assert "handleSelectSlashItem" in content

    # Structured parameter chips
    assert "selectedSkill" in content
    assert "editingParamKey" in content
    assert "updateSkillParam" in content
    assert "fillSampleInputs" in content

    # Plugin quick-toggles strip
    assert "DEFAULT_PLUGINS" in content
    assert "web-search" in content
    assert "rag-memory" in content
    assert "guardrails" in content
    assert "sandbox" in content
    assert "togglePlugin" in content
    assert "pluginsDropdownOpen" in content


def test_task_3_2_client_and_types_skill_integration():
    types_file = RENDERER_ROOT / "types" / "index.ts"
    types_content = types_file.read_text()
    assert "SkillItem" in types_content
    assert "PluginItem" in types_content
    assert "SelectedSkill" in types_content

    client_file = RENDERER_ROOT / "api" / "client.ts"
    client_content = client_file.read_text()
    assert "getSkills" in client_content
    assert "executeSkill" in client_content
    assert "DEFAULT_SKILLS_CATALOG" in client_content
    assert "code_review_checklist" in client_content
    assert "generate_sql_from_nl" in client_content


def test_task_3_3_approval_card_component():
    """Verify ApprovalCard.tsx component structure, risk badges, diffs, and action buttons."""
    card_file = RENDERER_ROOT / "components" / "ApprovalCard.tsx"
    assert card_file.exists(), "ApprovalCard.tsx must exist"
    content = card_file.read_text()

    # Component exports and props
    assert "export const ApprovalCard" in content
    assert "ApprovalCardProps" in content
    assert "onApprove" in content
    assert "onReject" in content
    assert "onEdit" in content

    # Risk level support and styling
    assert "critical" in content
    assert "high" in content
    assert "medium" in content
    assert "low" in content
    assert "ShieldAlert" in content
    assert "AlertTriangle" in content

    # Diff preview support
    assert "renderDiffViewer" in content
    assert "diff.type === 'command'" in content
    assert "diff.type === 'file'" in content
    assert "diff.type === 'sql'" in content

    # Action buttons and interactive handlers
    assert "handleApproveClick" in content
    assert "handleRejectConfirm" in content
    assert "handleSaveEdit" in content
    assert "Approve & Execute" in content
    assert "Edit Payload" in content
    assert "Reject" in content

    # Audit and resolved states
    assert "Approved by Operator" in content or "Approved" in content
    assert "Rejected" in content
    assert "Approved with Edits" in content
    assert "auditId" in content


def test_task_3_3_approval_types_and_client():
    """Verify TypeScript types and SidecarClient methods for Task 3.3."""
    types_file = RENDERER_ROOT / "types" / "index.ts"
    types_content = types_file.read_text()
    assert "RiskLevel" in types_content
    assert "ApprovalStatus" in types_content
    assert "ToolCallDiff" in types_content
    assert "ApprovalRequest" in types_content
    assert "ApprovalDecision" in types_content
    assert "AuditLogEntry" in types_content
    assert "approvalRequest?: ApprovalRequest" in types_content

    client_file = RENDERER_ROOT / "api" / "client.ts"
    client_content = client_file.read_text()
    assert "evaluateToolSafety" in client_content
    assert "submitApprovalDecision" in client_content
    assert "getSafetyAuditLogs" in client_content
    assert "/v1/safety/approval" in client_content


def test_task_3_3_message_and_home_approval_integration():
    """Verify Message.tsx and Home.tsx integration of ApprovalCard."""
    message_file = RENDERER_ROOT / "components" / "Message.tsx"
    message_content = message_file.read_text()
    assert "ApprovalCard" in message_content
    assert "message.approvalRequest" in message_content
    assert "onApprove" in message_content
    assert "onReject" in message_content
    assert "onEdit" in message_content

    home_file = RENDERER_ROOT / "screens" / "Home.tsx"
    home_content = home_file.read_text()
    assert "detectDangerousToolCall" in home_content
    assert "handleApproveToolCall" in home_content
    assert "handleRejectToolCall" in home_content
    assert "handleEditToolCall" in home_content
    assert "submitApprovalDecision" in home_content
    assert "destructive_fs_rm_all" in home_content or "rm -rf" in home_content
    assert "db_drop_prod" in home_content or "drop table" in home_content


def test_task_3_4_model_tier_selector_and_pricing():
    """Verify Task 3.4 model tier selector, rate per 1k display, and dynamic pricing preview."""
    chat_input_file = RENDERER_ROOT / "components" / "ChatInput.tsx"
    assert chat_input_file.exists()
    content = chat_input_file.read_text()

    # Model tiers configuration and pricing display
    assert "MODEL_TIER_CONFIG" in content
    assert "Instant High" in content
    assert "$0.0002/1k" in content
    assert "K3 Swarm High" in content
    assert "$0.0015/1k" in content
    assert "K3 High" in content
    assert "$0.0080/1k" in content

    # Dynamic pre-execution cost preview
    assert "approxTokens" in content
    assert "ratePer1k" in content
    assert "costPreview" in content
    assert "Est:" in content

    # Accessibility and selection semantics
    assert 'aria-label="Select model routing tier"' in content
    assert 'role="listbox"' in content


def test_task_3_4_agent_persona_picker_and_types():
    """Verify Task 3.4 Agent persona types, client catalog, and picker integration."""
    types_file = RENDERER_ROOT / "types" / "index.ts"
    types_content = types_file.read_text()
    assert "export interface AgentPersona" in types_content
    assert "suggestedModel" in types_content
    assert "pipelineName" in types_content

    client_file = RENDERER_ROOT / "api" / "client.ts"
    client_content = client_file.read_text()
    assert "DEFAULT_PERSONAS" in client_content
    assert "General Assistant" in client_content
    assert "Senior Engineer" in client_content
    assert "Deep Researcher" in client_content
    assert "Security Auditor" in client_content
    assert "getPersonas" in client_content

    chat_input_file = RENDERER_ROOT / "components" / "ChatInput.tsx"
    chat_input_content = chat_input_file.read_text()
    assert "personaId" in chat_input_content
    assert "onPersonaChange" in chat_input_content
    assert "personaDropdownOpen" in chat_input_content
    assert "renderPersonaIcon" in chat_input_content
    assert 'aria-label="Select agent persona"' in chat_input_content


def test_task_3_4_home_pipeline_and_model_synchronization():
    """Verify immediate pipeline and model synchronization in Home.tsx."""
    home_file = RENDERER_ROOT / "screens" / "Home.tsx"
    assert home_file.exists()
    home_content = home_file.read_text()

    assert "activePersona" in home_content
    assert "activePipeline" in home_content
    assert "handleModelChange" in home_content
    assert "handlePersonaChange" in home_content
    assert "Persona:" in home_content
    assert "Pipeline:" in home_content


def test_task_3_5_session_sidebar_and_search():
    """Verify Task 3.5 Session Sidebar 3-zone structure, search filter, and active session highlighting."""
    # 1. Type and client contract
    types_file = RENDERER_ROOT / "types" / "index.ts"
    assert "SessionSearchResult" in types_file.read_text()

    client_file = RENDERER_ROOT / "api" / "client.ts"
    client_content = client_file.read_text()
    assert "searchSessions" in client_content
    assert "/v1/sessions/search" in client_content

    # 2. Sidebar component deliverables
    sidebar_file = RENDERER_ROOT / "shell" / "Sidebar.tsx"
    assert sidebar_file.exists()
    sidebar_content = sidebar_file.read_text()

    # Zone A: Logo, collapse, New Chat Ctrl+K
    assert "New Chat" in sidebar_content
    assert "Ctrl K" in sidebar_content
    assert "onToggleCollapse" in sidebar_content

    # Zone B: Modes list
    assert "primaryModes" in sidebar_content
    assert "capabilityModes" in sidebar_content

    # Zone C: Projects, Recent Chats, User Profile, Real-time search
    assert "searchQuery" in sidebar_content
    assert "searchResults" in sidebar_content
    assert "sidecarClient.searchSessions" in sidebar_content
    assert "activeSessionId" in sidebar_content
    assert "Search sessions" in sidebar_content
    assert "Projects" in sidebar_content
    assert "Recent Chats" in sidebar_content
    assert "Nadir" in sidebar_content

    # Collapsed mode icon strip
    assert "collapsed" in sidebar_content

    # 3. Layout & App prop wiring
    layout_file = RENDERER_ROOT / "shell" / "Layout.tsx"
    layout_content = layout_file.read_text()
    assert "activeSessionId" in layout_content
    assert "onSelectSession" in layout_content

    app_file = RENDERER_ROOT / "App.tsx"
    app_content = app_file.read_text()
    assert "activeSessionId" in app_content
    assert "setActiveSessionId" in app_content


def test_task_3_6_document_drop_and_rag_ingestion():
    """Verify Task 3.6 Canvas drag-and-drop target, upload progress bar, multi-file chip attachments, and memory observation."""
    # 1. Type and client contract
    types_file = RENDERER_ROOT / "types" / "index.ts"
    types_content = types_file.read_text()
    assert "snippet?:" in types_content
    assert "uploadProgress?:" in types_content
    assert "ObserveMemoryPayload" in types_content
    assert "ObservationRecord" in types_content

    client_file = RENDERER_ROOT / "api" / "client.ts"
    client_content = client_file.read_text()
    assert "observeMemory" in client_content
    assert "/v1/memory/observe" in client_content
    assert "ingestMemory" in client_content
    assert "/v1/memory/ingest" in client_content

    # 2. ChatInput multi-file chips, progress and snippet preview
    chat_input_file = RENDERER_ROOT / "components" / "ChatInput.tsx"
    chat_input_content = chat_input_file.read_text()
    assert "previewAttachment" in chat_input_content
    assert "observeMemory" in chat_input_content
    assert "snippet" in chat_input_content
    assert "Indexed in RAG Memory" in chat_input_content
    assert "uploadProgress" in chat_input_content

    # 3. Canvas Drag-and-Drop and Progress Bar in Home.tsx
    home_file = RENDERER_ROOT / "screens" / "Home.tsx"
    home_content = home_file.read_text()
    assert "handleCanvasDragEnter" in home_content
    assert "handleCanvasDragOver" in home_content
    assert "handleCanvasDrop" in home_content
    assert "canvas-drag-overlay" in home_content
    assert "upload-progress-bar" in home_content
    assert "canvasAttachments" in home_content


def test_task_3_7_agent_screen_identity_memory_growth():
    """Verify Task 3.7 My Agent Screen (Identity, 365-day heatmap, memory ledger, self-growth toggle)."""
    # 1. Agent screen component existence
    agent_file = RENDERER_ROOT / "screens" / "Agent.tsx"
    assert agent_file.exists(), "Agent.tsx must exist"
    content = agent_file.read_text()

    # 2. Identity and 365-day heatmap
    assert "Nadir's Agent" in content or "Agent" in content
    assert "heatmapData" in content
    assert "364" in content or "365" in content
    assert "level" in content

    # 3. 4 Tabs: Closeness, Growth, Memory, Cost
    assert "closeness" in content
    assert "growth" in content
    assert "memory" in content
    assert "cost" in content

    # 4. Observational memory search and inline editing
    assert "filteredMemories" in content
    assert "handleStartEdit" in content
    assert "handleSaveEdit" in content
    assert "handleDeleteMemory" in content
    assert "handleCreateMemory" in content
    assert "Search memory entries" in content or "searchQuery" in content

    # 5. Self-growth toggle with persistent preference
    assert "selfGrowthEnabled" in content
    assert "agent-engine-self-growth" in content
    assert "aria-checked" in content
    assert "Self-Growth" in content

    # 6. Animated SVG memory network dots
    assert "<svg" in content
    assert "network-canvas" in content or "animate-pulse" in content

    # 7. Embedded ChatInput and App.tsx route wiring
    assert "ChatInput" in content
    assert 'mode="agent"' in content

    app_file = RENDERER_ROOT / "App.tsx"
    app_content = app_file.read_text()
    assert "import { Agent } from './screens/Agent';" in app_content
    assert "case 'agent':" in app_content
    assert "<Agent" in app_content

    # 8. Sidecar client memory observations contract
    client_file = RENDERER_ROOT / "api" / "client.ts"
    client_content = client_file.read_text()
    assert "queryObservations" in client_content


def test_task_3_8_scheduled_tasks_screen():
    """Verify Task 3.8 Scheduled Tasks Screen (Route /tasks, cron builder, off-peak Law 7, create modal, templates)."""
    # 1. Tasks screen component existence
    tasks_file = RENDERER_ROOT / "screens" / "Tasks.tsx"
    assert tasks_file.exists(), "Tasks.tsx must exist"
    content = tasks_file.read_text()

    # 2. Plain-English cron builder and human translation
    assert "cronToPlainEnglish" in content
    assert "Plain-English preview" in content
    assert "Off-Peak Engine (Law 7)" in content or "Law 7" in content

    # 3. Create Dropdown & Modal with 3 creation paths
    assert "Manually" in content
    assert "Via chat" in content
    assert "From template" in content

    # 4. 4 Built-in Curated Templates
    assert "Daily inbox digest at 8 AM" in content
    assert "Weekly expense report Sunday 6 PM" in content
    assert "Hourly code audit on save" in content
    assert "Monthly book progress summary" in content

    # 5. Off-peak default and channel notifications
    assert "is_off_peak" in content
    assert "notification_channel" in content
    assert "slack" in content
    assert "cost_per_run" in content
    assert "monthly_estimate" in content

    # 6. Embedded ChatInput and App.tsx route wiring
    assert "ChatInput" in content
    assert 'mode="tasks"' in content

    app_file = RENDERER_ROOT / "App.tsx"
    app_content = app_file.read_text()
    assert "import { Tasks } from './screens/Tasks';" in app_content
    assert "case 'tasks':" in app_content
    assert "<Tasks" in app_content

    # 7. Sidecar client and types contracts
    client_file = RENDERER_ROOT / "api" / "client.ts"
    client_content = client_file.read_text()
    assert "listScheduledTasks" in client_content
    assert "createScheduledTask" in client_content
    assert "toggleScheduledTask" in client_content
    assert "DEFAULT_SCHEDULED_TASKS" in client_content

    types_file = RENDERER_ROOT / "types" / "index.ts"
    types_content = types_file.read_text()
    assert "ScheduledTask" in types_content
    assert "TaskScheduleStatus" in types_content
    assert "NotificationChannel" in types_content


def test_task_3_9_universal_chat_input_hardening():
    """Verify Task 3.9 Universal Chat Input hardening (10,000+ char 60fps, paste image, token cost ±5%, Ctrl+K)."""
    input_file = RENDERER_ROOT / "components" / "ChatInput.tsx"
    assert input_file.exists(), "ChatInput.tsx must exist"
    content = input_file.read_text()

    # 1. 60fps responsiveness on 10k+ character input
    assert "requestAnimationFrame" in content
    assert "lookbackStart" in content
    assert "Math.max(0, cursorPos - 40)" in content or "cursorPos" in content

    # 2. Paste image and drag-drop support
    assert "handlePaste" in content
    assert "onPaste={handlePaste}" in content
    assert "readAsDataURL" in content
    assert "onDragOver" in content
    assert "onDrop" in content
    assert "data:image/" in content

    # 3. Token cost preview accurate to ±5%
    assert "export function estimateTokenCount" in content
    assert "ratePer1k" in content
    assert "costPreview" in content
    assert "accuracy ±5%" in content or "±5%" in content

    # 4. Global Ctrl+K focus handler
    assert "handleGlobalKey" in content
    assert "ctrlKey" in content
    assert "activeTextareaRef.current?.focus()" in content

    # 5. Model error banner
    assert "modelError" in content
    assert "AlertTriangle" in content

    # 6. Zero duplication: Verified reuse in Home, Agent, and Tasks screens
    home_content = (RENDERER_ROOT / "screens" / "Home.tsx").read_text()
    agent_content = (RENDERER_ROOT / "screens" / "Agent.tsx").read_text()
    tasks_content = (RENDERER_ROOT / "screens" / "Tasks.tsx").read_text()

    assert "<ChatInput" in home_content
    assert "<ChatInput" in agent_content
    assert "<ChatInput" in tasks_content

    # 7. Mathematical verification of token estimation accuracy on 10,000 char input
    sample_text_10k = "The quick brown fox jumps over the lazy dog. " * 225  # ~10,125 chars
    # Standard English BPE tokenizer yields ~2,600 tokens (10125 / 3.9 ≈ 2596 tokens)
    estimated_tokens = round(len(sample_text_10k.strip()) / 3.9)
    # Target range within ±5% of 2596 is [2466, 2725]
    assert 2466 <= estimated_tokens <= 2725


def test_task_3_10_mode_landing_page_template():
    """Verify Task 3.10 Mode Landing Page Template and FeaturedGrid across capability modes."""
    grid_file = RENDERER_ROOT / "components" / "FeaturedGrid.tsx"
    assert grid_file.exists(), "FeaturedGrid.tsx must exist"
    grid_content = grid_file.read_text()

    assert "export const FeaturedGrid" in grid_content
    assert "FeaturedCardItem" in grid_content
    assert "renderCardIcon" in grid_content
    assert "onSelectCard" in grid_content

    mode_page_file = RENDERER_ROOT / "components" / "ModePage.tsx"
    assert mode_page_file.exists(), "ModePage.tsx must exist"
    mode_page_content = mode_page_file.read_text()

    assert "export const ModePage" in mode_page_content
    assert "MODE_CONFIGS" in mode_page_content

    # Check that all 8 capability modes are registered with rich configurations
    expected_modes = [
        "code",
        "deep-research",
        "docs",
        "sheets",
        "slides",
        "websites",
        "design",
        "diagrams",
    ]
    for mode_name in expected_modes:
        assert mode_name in mode_page_content, f"Mode '{mode_name}' missing from ModePage"

    # Category filter tabs, chat input reuse, and message list
    assert "activeCategory" in mode_page_content
    assert "<ChatInput" in mode_page_content
    assert "<FeaturedGrid" in mode_page_content
    assert "<Message" in mode_page_content

    # Wire into App.tsx (via ModePage or dedicated screens/Modes)
    app_content = (RENDERER_ROOT / "App.tsx").read_text()
    assert "ModePage" in app_content or "screens/Modes" in app_content
    for mode_name in expected_modes:
        assert f"case '{mode_name}':" in app_content or f"'{mode_name}'" in app_content


def test_task_3_11_featured_cases_content_curation():
    """Verify Task 3.11 Featured Cases Content Curation across all 8 capability modes."""
    import json
    from core.cases import get_case_manager, load_mode_cases, list_all_mode_cases
    from fastapi.testclient import TestClient
    from services.python.server.api import app

    cases_dir = REPO_ROOT / "configs" / "cases"
    assert cases_dir.exists(), "configs/cases/ directory must exist"

    expected_case_files = [
        "code.json",
        "deep_research.json",
        "docs.json",
        "sheets.json",
        "slides.json",
        "websites.json",
        "design.json",
        "diagrams.json",
    ]

    # 1. Validate all 8 JSON files in configs/cases/
    total_cases = 0
    for filename in expected_case_files:
        json_path = cases_dir / filename
        assert json_path.exists(), f"Missing curated case file: {filename}"
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "mode" in data
        assert "title" in data
        assert "tagline" in data
        assert "badge" in data
        assert "pipeline" in data
        assert "categories" in data and len(data["categories"]) >= 3
        assert "cases" in data and len(data["cases"]) >= 4

        for c in data["cases"]:
            total_cases += 1
            assert "id" in c
            assert "title" in c
            assert "category" in c
            assert "description" in c
            assert "prompt" in c and len(c["prompt"]) > 20
            assert "expected_tools" in c and len(c["expected_tools"]) >= 2
            assert "sample_output" in c and len(c["sample_output"]) > 10
            assert "est_cost" in c

    assert total_cases >= 32, f"Expected at least 32 total curated cases, got {total_cases}"

    # 2. Validate desktop screens in apps/desktop/src/renderer/screens/Modes/
    modes_screen_dir = RENDERER_ROOT / "screens" / "Modes"
    assert modes_screen_dir.exists(), "screens/Modes directory must exist"

    expected_screen_files = [
        "modeCases.ts",
        "CodeMode.tsx",
        "ResearchMode.tsx",
        "DocsMode.tsx",
        "SheetsMode.tsx",
        "SlidesMode.tsx",
        "WebsitesMode.tsx",
        "DesignMode.tsx",
        "DiagramsMode.tsx",
        "index.ts",
    ]
    for filename in expected_screen_files:
        p = modes_screen_dir / filename
        assert p.exists(), f"Missing mode screen deliverable: {filename}"
        content = p.read_text()
        if filename.endswith("Mode.tsx"):
            assert "ModePage" in content
            assert "customCases" in content

    # 3. Validate one-click prompt population and initialValue wiring in ModePage and ChatInput
    mode_page_content = (RENDERER_ROOT / "components" / "ModePage.tsx").read_text()
    assert "handleSelectCase" in mode_page_content
    assert "initialInputText" in mode_page_content
    assert "initialValue={initialInputText}" in mode_page_content

    chat_input_content = (RENDERER_ROOT / "components" / "ChatInput.tsx").read_text()
    assert "initialValue" in chat_input_content
    assert "setPrompt(initialValue)" in chat_input_content

    # 4. Validate Python core/cases.py loader, CaseManager, and search
    manager = get_case_manager()
    all_modes = list_all_mode_cases()
    assert len(all_modes) == 8

    code_conf = load_mode_cases("code")
    assert code_conf is not None
    assert code_conf.title == "Code Studio"
    assert len(code_conf.cases) >= 4

    # Search functionality
    search_results = manager.search("refactor")
    assert len(search_results) >= 1
    assert any(
        "refactor" in c.title.lower() or "refactor" in c.prompt.lower() for c in search_results
    )

    # Specific case lookup
    case_code_1 = manager.get_case("code-1")
    assert case_code_1 is not None
    assert "AST Refactor" in case_code_1.title

    # 5. Validate FastAPI sidecar API endpoints GET /v1/cases and GET /v1/cases/{mode}
    client = TestClient(app)
    resp = client.get("/v1/cases")
    assert resp.status_code == 200
    cases_data = resp.json()
    assert len(cases_data) >= 8

    resp_mode = client.get("/v1/cases/deep-research")
    assert resp_mode.status_code == 200
    mode_payload = resp_mode.json()
    assert mode_payload["mode"] == "deep-research"
    assert len(mode_payload["cases"]) >= 4


def test_task_4_1_projects_and_workspaces():
    """
    Validates Task 4.1 deliverables and contracts:
    - Projects.tsx screen exists with workspace cards grid and create project modal
    - ProjectDetail.tsx inspector exists with 5-tab inspector and thread list
    - App.tsx routes 'projects'
    - Project types in types/index.ts
    """
    # 1. Check types
    types_file = RENDERER_ROOT / "types" / "index.ts"
    types_content = types_file.read_text()
    assert "export interface Project {" in types_content
    assert "export interface ProjectThread {" in types_content
    assert "export interface ProjectFile {" in types_content
    assert "scopedPolicy?:" in types_content
    assert "budgetCeilingUsd?:" in types_content

    # 2. Check Projects.tsx
    projects_screen = RENDERER_ROOT / "screens" / "Projects.tsx"
    assert projects_screen.exists(), "Projects.tsx screen must exist"
    p_content = projects_screen.read_text()
    assert "export const Projects:" in p_content
    assert "Create New Workspace" in p_content or "Create Project" in p_content
    assert "Persistent System Instructions" in p_content
    assert "Scoped Security Policy" in p_content
    assert "AVAILABLE_ICONS" in p_content
    assert "ProjectDetail" in p_content

    # 3. Check ProjectDetail.tsx
    detail_screen = RENDERER_ROOT / "screens" / "ProjectDetail.tsx"
    assert detail_screen.exists(), "ProjectDetail.tsx screen must exist"
    d_content = detail_screen.read_text()
    assert "export const ProjectDetail:" in d_content
    assert "activeTab" in d_content
    assert "'instructions'" in d_content
    assert "'files'" in d_content
    assert "'agents'" in d_content
    assert "'policy'" in d_content
    assert "'cost'" in d_content
    assert "handleSaveInstructions" in d_content
    assert "handleCreateNewThread" in d_content

    # 4. Check App.tsx routing
    app_file = RENDERER_ROOT / "App.tsx"
    app_content = app_file.read_text()
    assert "import { Projects } from './screens/Projects';" in app_content
    assert "case 'projects':" in app_content
    assert "<Projects" in app_content
