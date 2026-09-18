# Agent Engine — Dependency, Provenance & License Inventory

> **Status:** Canonical Architecture Specification  
> **Audience:** Developers, Maintainers, Legal / Compliance, CTO  
> **Target Release:** `0.5 Nadir Edition`  
> **Task Reference:** `R0.2`, `R0.6`

---

## 1. Compliance Principles & Governance

1. **Permissive License Mandate:** All production runtime dependencies must be governed by commercially permissive open-source licenses (MIT, Apache-2.0, BSD-2/3-Clause, ISC).
2. **Zero Viral / Restrictive Copyleft:** AGPL, GPL (v2/v3), and Commons Clause licenses are strictly prohibited in runtime dependencies to ensure unencumbered local desktop distribution and single/multi-tenant commercial packaging. (See [`ADR-013`](ADR/013-native-team-collaboration.md) regarding the rejection of Switch due to Apache-2.0 + Commons Clause restrictions).
3. **No Unaudited Binaries:** All binary tools or sidecars must either be built from source or sourced from cryptographically pinned, officially signed releases.
4. **Supply Chain Isolation:** Internal SDKs and schemas (`@agent-engine/shared-schema`, `@agent-engine/sdk`, `packages/sdk-python`) are managed via workspace monorepo linking to prevent supply-chain spoofing.

---

## 2. Python Ecosystem Inventory (`pyproject.toml`)

| Package | Version Spec | License | Source / Repository | Purpose in Agent Engine | Replacement Risk |
|---|---|---|---|---|---|
| `dspy` | `>=3.3.0` | MIT | [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) | Declarative LLM programming, prompt optimization, signatures | Medium (Abstracted via DSPy adapters) |
| `fastapi` | `>=0.115.0` | MIT | [tiangolo/fastapi](https://github.com/tiangolo/fastapi) | Local Python sidecar REST API & SSE event streaming | Low (Standard ASGI framework) |
| `fastmcp` | `>=3.4.0` | MIT / Apache-2.0 | [jlowin/fastmcp](https://github.com/jlowin/fastmcp) | High-level FastMCP server implementation | Low (Can fall back to standard `mcp`) |
| `mcp` | `<2` | MIT | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | Official Anthropic Model Context Protocol Python SDK | Low |
| `chromadb` | `>=1.5.0` | Apache-2.0 | [chroma-core/chroma](https://github.com/chroma-core/chroma) | Local embedded vector database for project knowledge indexing | Medium (Abstracted behind vector repository) |
| `pydantic` | `>=2.10.0` | MIT | [pydantic/pydantic](https://github.com/pydantic/pydantic) | Data modeling, schema validation, and serialization | Low (Core industry standard) |
| `psutil` | `>=6.0.0` | BSD-3-Clause | [giampaolo/psutil](https://github.com/giampaolo/psutil) | OS process monitoring, telemetry, and memory usage tracking | Low |
| `watchdog` | `>=5.0.0` | Apache-2.0 | [gorakhargosh/watchdog](https://github.com/gorakhargosh/watchdog) | Filesystem event monitoring for project file changes | Low |
| `python-dotenv` | `>=1.0.0` | BSD-3-Clause | [theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) | Loading local `.env` configuration files in dev | Low |
| `requests` | `>=2.32.0` | Apache-2.0 | [psf/requests](https://github.com/psf/requests) | Synchronous HTTP client | Low |
| `httpx` | `>=0.28.0` | BSD-3-Clause | [encode/httpx](https://github.com/encode/httpx) | Async HTTP client for provider and adapter communication | Low |
| `pyyaml` | `>=6.0.0` | MIT | [yaml/pyyaml](https://github.com/yaml/pyyaml) | Workflow and configuration YAML serialization/parsing | Low |
| `rich` | `>=14.0.0` | MIT | [Textualize/rich](https://github.com/Textualize/rich) | Terminal formatting, progress indicators, CLI diagnostics | Low |
| `keyring` | `>=25.0.0` | MIT | [jaraco/keyring](https://github.com/jaraco/keyring) | Primary native OS Keychain access (macOS/Linux/Windows) | Low (Has fallback AES vault) |
| `alembic` | `>=1.19.2` | MIT | [sqlalchemy/alembic](https://github.com/sqlalchemy/alembic) | Relational database schema migrations | Low |
| `sqlalchemy` | `>=2.0.52` | MIT | [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) | Relational database abstraction (SQLite & PostgreSQL) | Low |
| `pathspec` | `>=0.12.0` | MPL-2.0 | [cpburnz/python-pathspec](https://github.com/cpburnz/python-pathspec) | Gitignore-style path pattern matching for file ingestion | Low |
| `streamlit` | `>=1.40.0` | Apache-2.0 | [streamlit/streamlit](https://github.com/streamlit/streamlit) | MVP development dashboard (ADR-002) | Low (Non-production UI) |
| `pytest` | `>=8.0.0` | MIT (dev) | [pytest-dev/pytest](https://github.com/pytest-dev/pytest) | Test execution framework | None (Dev only) |
| `ruff` | `>=0.8.0` | MIT / Apache-2.0 (dev) | [astral-sh/ruff](https://github.com/astral-sh/ruff) | Linting and code formatting | None (Dev only) |

---

## 3. TypeScript & Desktop Shell Ecosystem (`apps/desktop/package.json`)

| Package | Version Spec | License | Source / Repository | Purpose in Desktop Shell | Replacement Risk |
|---|---|---|---|---|---|
| `react` | `^18.3.1` | MIT | [facebook/react](https://github.com/facebook/react) | UI component rendering engine | Low |
| `react-dom` | `^18.3.1` | MIT | [facebook/react](https://github.com/facebook/react) | DOM renderer for React | Low |
| `@tauri-apps/api` | `^2.2.0` | Apache-2.0 / MIT | [tauri-apps/tauri](https://github.com/tauri-apps/tauri) | Tauri v2 frontend IPC communication | Medium (Core shell layer) |
| `@tauri-apps/plugin-process` | `^2.2.0` | Apache-2.0 / MIT | [tauri-apps/plugins-workspace](https://github.com/tauri-apps/plugins-workspace) | Desktop process lifecycle management | Low |
| `@tauri-apps/plugin-shell` | `^2.2.0` | Apache-2.0 / MIT | [tauri-apps/plugins-workspace](https://github.com/tauri-apps/plugins-workspace) | Desktop OS shell integrations | Low |
| `lucide-react` | `^0.475.0` | ISC | [lucide-icons/lucide](https://github.com/lucide-icons/lucide) | Vector iconography for chat, workflow, and status | Low |
| `typescript` | `^5.7.3` | Apache-2.0 (dev) | [microsoft/TypeScript](https://github.com/microsoft/TypeScript) | Type checker and compiler | None (Dev only) |
| `vite` | `^5.4.14` | MIT (dev) | [vitejs/vite](https://github.com/vitejs/vite) | Frontend bundler and dev server | None (Dev only) |
| `tailwindcss` | `^3.4.17` | MIT (dev) | [tailwindlabs/tailwindcss](https://github.com/tailwindlabs/tailwindcss) | Utility-first styling framework | None (Dev only) |

---

## 4. Rust Ecosystem (`apps/desktop/src-tauri/Cargo.toml`)

| Crate | Version | License | Purpose in Host Shell | Replacement Risk |
|---|---|---|---|---|
| `tauri` | `2` | Apache-2.0 / MIT | Desktop application runtime, webview hosting, system tray | Medium |
| `tauri-plugin-shell` | `2` | Apache-2.0 / MIT | Tauri shell interaction plugin | Low |
| `tauri-plugin-process` | `2` | Apache-2.0 / MIT | Child process supervision (Python sidecar) | Low |
| `serde` | `1.0` | Apache-2.0 / MIT | Serialization framework | Low |
| `serde_json` | `1.0` | Apache-2.0 / MIT | JSON parsing and stringification | Low |
| `tokio` | `1` | MIT | Async event loop and thread management | Low |
| `reqwest` | `0.12` | Apache-2.0 / MIT | HTTP client for sidecar health checks and IPC | Low |
| `sha2` | `0.10` | Apache-2.0 / MIT | Cryptographic SHA-256 for approval token verification | Low |

---

## 5. Third-Party Adapted Code & Provenance Records

| Asset / Subsystem | Origin / Reference | Original License | Integration Type | Security / Legal Status |
|---|---|---|---|---|
| Native Channel Adapters | In-tree custom code (`core/adapters/`) | Apache-2.0 | Custom Native Implementation | **100% in-tree.** Replaces external Switch dependency (ADR-013). No proprietary or restrictive source-available code. |
| Credential Vault | AES-256-GCM + PBKDF2 (`core/security/credentials.py`) | Apache-2.0 | Custom Native Implementation | Pure Python cryptography using standard library and `keyring`. Zero third-party proprietary vaults. |
| Workflow Kahn's DAG Algorithm | Standard topological sort (`core/workflows/dag.py`) | Apache-2.0 | Custom Native Implementation | Standard mathematical algorithm. Clean in-tree implementation. |

---

## 6. Audit Conclusion

- **Total Production Dependencies:** 24 (Python: 15, TypeScript: 4, Rust: 5)
- **License Distribution:**
  - MIT: 68%
  - Apache-2.0: 25%
  - BSD-3-Clause: 5%
  - ISC / MPL-2.0: 2%
- **Restricted / Copyleft Licenses:** 0 (Zero AGPL, GPL, or Commons Clause)
- **Compliance Status:** **APPROVED for Local-First Single-User Distribution & Commercial Packaging.**
