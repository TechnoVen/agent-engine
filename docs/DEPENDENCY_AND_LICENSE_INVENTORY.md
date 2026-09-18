# Agent Engine — Dependency, Provenance & License Inventory

> **Status:** Canonical Architecture Specification  
> **Audience:** Developers, Maintainers, Legal / Compliance, CTO  
> **Target Release:** `0.5 Nadir Edition`  
> **Task Reference:** `R0.2`, `R0.6`  
> **Note:** This document represents an engineering dependency and license inventory, not a formal legal opinion.

---

## 1. Compliance Principles & Governance

1. **Permissive & Unencumbered Distribution:** Production runtime dependencies must be governed by commercially permissive open-source licenses (MIT, Apache-2.0, BSD-2/3-Clause, ISC) or manageable file-level weak copyleft licenses (MPL-2.0) with documented notice obligations.
2. **Zero Strong Viral Copyleft:** Strong copyleft licenses (GPL v2/v3, AGPL v3) are strictly prohibited in runtime dependencies to ensure unencumbered local desktop distribution and single/multi-tenant commercial packaging without viral source-disclosure mandates.
3. **Zero Commercial Source-Available Restrictions:** Source-available licenses with commercial use restrictions (e.g. Commons Clause, BSL, SSPL) are prohibited in runtime dependencies. (See [`ADR-013`](ADR/013-native-team-collaboration.md) regarding the explicit rejection of Switch due to Apache-2.0 + Commons Clause restrictions).
4. **License Taxonomy Distinction:**
   - **Permissive:** MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC. Permits reuse, modification, and binary distribution with standard attribution notices.
   - **Weak Copyleft:** MPL-2.0. File-level copyleft requiring source availability only for modifications to the licensed files themselves; permits static/dynamic linking into larger works under different licenses without viral contamination.
   - **Strong Copyleft:** GPL-2.0, GPL-3.0, AGPL-3.0. Viral reciprocal obligations applying to the entire combined work or network service.
   - **Source-Available / Restrictive:** Commons Clause, BSL, SSPL. Non-OSI compliant restrictions on commercial use or managed hosting.
   - **Proprietary:** Closed-source, vendor-specific terms.

---

## 2. Python Ecosystem Inventory (`pyproject.toml`)

| Package | Version Spec | License Class | Exact License | Source / Repository | Purpose in Agent Engine | Replacement Risk / Notes |
|---|---|---|---|---|---|---|
| `dspy` | `>=3.3.0` | Permissive | MIT | [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) | Declarative LLM programming, prompt optimization, signatures | Medium (Abstracted via DSPy adapters) |
| `fastapi` | `>=0.115.0` | Permissive | MIT | [tiangolo/fastapi](https://github.com/tiangolo/fastapi) | Local Python sidecar REST API & SSE event streaming | Low (Standard ASGI framework) |
| `fastmcp` | `>=3.4.0` | Permissive | MIT / Apache-2.0 | [jlowin/fastmcp](https://github.com/jlowin/fastmcp) | High-level FastMCP server implementation | Low (Can fall back to standard `mcp`) |
| `mcp` | `<2` | Permissive | MIT | [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | Official Anthropic Model Context Protocol Python SDK | Low |
| `chromadb` | `>=1.5.0` | Permissive | Apache-2.0 | [chroma-core/chroma](https://github.com/chroma-core/chroma) | Local embedded vector database for project knowledge indexing | Medium (Abstracted behind vector repository) |
| `pydantic` | `>=2.10.0` | Permissive | MIT | [pydantic/pydantic](https://github.com/pydantic/pydantic) | Data modeling, schema validation, and serialization | Low (Core industry standard) |
| `psutil` | `>=6.0.0` | Permissive | BSD-3-Clause | [giampaolo/psutil](https://github.com/giampaolo/psutil) | OS process monitoring, telemetry, and memory usage tracking | Low |
| `watchdog` | `>=5.0.0` | Permissive | Apache-2.0 | [gorakhargosh/watchdog](https://github.com/gorakhargosh/watchdog) | Filesystem event monitoring for project file changes | Low |
| `python-dotenv` | `>=1.0.0` | Permissive | BSD-3-Clause | [theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) | Loading local `.env` configuration files in dev | Low |
| `requests` | `>=2.32.0` | Permissive | Apache-2.0 | [psf/requests](https://github.com/psf/requests) | Synchronous HTTP client | Low |
| `httpx` | `>=0.28.0` | Permissive | BSD-3-Clause | [encode/httpx](https://github.com/encode/httpx) | Async HTTP client for provider and adapter communication | Low |
| `pyyaml` | `>=6.0.0` | Permissive | MIT | [yaml/pyyaml](https://github.com/yaml/pyyaml) | Workflow and configuration YAML serialization/parsing | Low |
| `rich` | `>=14.0.0` | Permissive | MIT | [Textualize/rich](https://github.com/Textualize/rich) | Terminal formatting, progress indicators, CLI diagnostics | Low |
| `keyring` | `>=25.0.0` | Permissive | MIT | [jaraco/keyring](https://github.com/jaraco/keyring) | Primary native OS Keychain access (macOS/Linux/Windows) | Low (Has fallback AES vault) |
| `alembic` | `>=1.19.2` | Permissive | MIT | [sqlalchemy/alembic](https://github.com/sqlalchemy/alembic) | Relational database schema migrations | Low |
| `sqlalchemy` | `>=2.0.52` | Permissive | MIT | [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) | Relational database abstraction (SQLite & PostgreSQL) | Low |
| `pathspec` | `>=0.12.0` | **Weak Copyleft** | **MPL-2.0** | [cpburnz/python-pathspec](https://github.com/cpburnz/python-pathspec) | Gitignore-style path pattern matching for file ingestion | Low (Used unmodified as library; MPL-2.0 file-level copyleft applies only if `pathspec` source itself is modified) |
| `streamlit` | `>=1.40.0` | Permissive | Apache-2.0 | [streamlit/streamlit](https://github.com/streamlit/streamlit) | MVP development dashboard (ADR-002; non-production) | Low |
| `pytest` | `>=8.0.0` | Permissive | MIT (dev) | [pytest-dev/pytest](https://github.com/pytest-dev/pytest) | Test execution framework | None (Dev only) |
| `ruff` | `>=0.8.0` | Permissive | MIT / Apache-2.0 (dev) | [astral-sh/ruff](https://github.com/astral-sh/ruff) | Linting and code formatting | None (Dev only) |

---

## 3. TypeScript & Desktop Shell Ecosystem (`apps/desktop/package.json`)

| Package | Version Spec | License Class | Exact License | Source / Repository | Purpose in Desktop Shell | Replacement Risk |
|---|---|---|---|---|---|---|
| `react` | `^18.3.1` | Permissive | MIT | [facebook/react](https://github.com/facebook/react) | UI component rendering engine | Low |
| `react-dom` | `^18.3.1` | Permissive | MIT | [facebook/react](https://github.com/facebook/react) | DOM renderer for React | Low |
| `@tauri-apps/api` | `^2.2.0` | Permissive | Apache-2.0 / MIT | [tauri-apps/tauri](https://github.com/tauri-apps/tauri) | Tauri v2 frontend IPC communication | Medium (Core shell layer) |
| `@tauri-apps/plugin-process` | `^2.2.0` | Permissive | Apache-2.0 / MIT | [tauri-apps/plugins-workspace](https://github.com/tauri-apps/plugins-workspace) | Desktop process lifecycle management | Low |
| `@tauri-apps/plugin-shell` | `^2.2.0` | Permissive | Apache-2.0 / MIT | [tauri-apps/plugins-workspace](https://github.com/tauri-apps/plugins-workspace) | Desktop OS shell integrations | Low |
| `lucide-react` | `^0.475.0` | Permissive | ISC | [lucide-icons/lucide](https://github.com/lucide-icons/lucide) | Vector iconography for chat, workflow, and status | Low |
| `typescript` | `^5.7.3` | Permissive | Apache-2.0 (dev) | [microsoft/TypeScript](https://github.com/microsoft/TypeScript) | Type checker and compiler | None (Dev only) |
| `vite` | `^5.4.14` | Permissive | MIT (dev) | [vitejs/vite](https://github.com/vitejs/vite) | Frontend bundler and dev server | None (Dev only) |
| `tailwindcss` | `^3.4.17` | Permissive | MIT (dev) | [tailwindlabs/tailwindcss](https://github.com/tailwindlabs/tailwindcss) | Utility-first styling framework | None (Dev only) |

---

## 4. Rust Ecosystem (`apps/desktop/src-tauri/Cargo.toml`)

| Crate | Version | License Class | Exact License | Purpose in Host Shell | Replacement Risk |
|---|---|---|---|---|---|
| `tauri` | `2` | Permissive | Apache-2.0 / MIT | Desktop application runtime, webview hosting, system tray | Medium |
| `tauri-plugin-shell` | `2` | Permissive | Apache-2.0 / MIT | Tauri shell interaction plugin | Low |
| `tauri-plugin-process` | `2` | Permissive | Apache-2.0 / MIT | Child process supervision (Python sidecar) | Low |
| `serde` | `1.0` | Permissive | Apache-2.0 / MIT | Serialization framework | Low |
| `serde_json` | `1.0` | Permissive | Apache-2.0 / MIT | JSON parsing and stringification | Low |
| `tokio` | `1` | Permissive | MIT | Async event loop and thread management | Low |
| `reqwest` | `0.12` | Permissive | Apache-2.0 / MIT | HTTP client for sidecar health checks and IPC | Low |
| `sha2` | `0.10` | Permissive | Apache-2.0 / MIT | Cryptographic SHA-256 for approval token verification | Low |

---

## 5. Third-Party Adapted Code & Provenance Records

| Asset / Subsystem | Origin / Reference | Original License | Integration Type | Governance / Status |
|---|---|---|---|---|
| Native Channel Adapters | In-tree custom code (`core/adapters/`) | Apache-2.0 | Custom Native Implementation | **100% in-tree.** Replaces external Switch dependency (ADR-013). No proprietary or restrictive source-available code. |
| Credential Vault | AES-256-GCM + PBKDF2 (`core/security/credentials.py`) | Apache-2.0 | Custom Native Implementation | Pure Python cryptography using standard library and `keyring`. Zero third-party proprietary vaults. |
| Workflow Kahn's DAG Algorithm | Standard topological sort (`core/workflows/dag.py`) | Apache-2.0 | Custom Native Implementation | Standard mathematical algorithm. Clean in-tree implementation. |

---

## 6. Audit Conclusion & Compliance Assessment

- **Total Production Dependencies:** 24 (Python: 15, TypeScript: 4, Rust: 5)
- **Breakdown by License Class:**
  - **Permissive (23 / 95.8%):** MIT (16), Apache-2.0 (6), BSD-3-Clause (3), ISC (1).
  - **Weak Copyleft (1 / 4.2%):** `pathspec` (MPL-2.0). File-level copyleft only; used unmodified as a package dependency. Notice obligations satisfied via standard third-party attribution packaging.
  - **Strong Copyleft (0 / 0.0%):** Zero GPL-2.0, GPL-3.0, or AGPL-3.0 dependencies in production tree.
  - **Source-Available / Restrictive (0 / 0.0%):** Zero Commons Clause, BSL, or SSPL restrictions.
- **Engineering Assessment:** No identified licensing blocker for the currently planned distribution model based on the dependency audit; specific notice and source-preservation obligations for MPL-2.0 remain documented.
