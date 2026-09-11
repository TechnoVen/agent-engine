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
