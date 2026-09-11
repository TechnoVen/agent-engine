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
