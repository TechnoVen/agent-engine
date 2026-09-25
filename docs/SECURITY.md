# Agent Engine — Canonical Security Specification

> **Status:** Canonical Security Architecture  
> **Governing ADRs:** ADR-006 (Staged Patches), ADR-008 (Zero-Trust Encryption), ADR-014 (Room Governance)  
> **Target Release:** 0.5 (Stage R2 Implementation Target)  

---

## 1. Core Security Invariants

1. **Fail-Closed Security Architecture:**
   * Any ambiguity, policy conflict, credential error, or missing permission immediately halts execution and fails closed.
2. **Zero Plaintext Credential Footprint (ADR-008):**
   * API keys and secrets are never committed to git or stored in plaintext configuration files. They are managed via the OS Keyring or an AES-256-GCM encrypted hardware-anchored vault (`data/credentials.vault`).
3. **Cryptographic Action Approval Boundary:**
   * Consequential actions (file destruction, code execution, shell commands, database mutation) require an explicit, cryptographic approval token from the operator.
4. **Separation of Workflow Gates from Security Authorization:**
   * A workflow `ApprovalTask` is a user decision-making step. It does **not** grant ambient authority to execute dangerous tools downstream. Consequential tool execution must separately invoke the canonical Approval Service.
5. **No Ambiguous Execution Authority:**
   * External untrusted content (retrieved web documents, emails, chat messages) cannot grant or elevate execution privileges. Prompt injection defenses treat retrieved context as untrusted text.

---

## 2. Canonical Approval Service

### 2.1. Approval Token Specification
An approval request is defined by an immutable cryptographic structure:

```python
class ApprovalRequest(BaseModel):
    approval_id: str = Field(default_factory=lambda: f"appr_{uuid.uuid4().hex[:12]}")
    execution_id: str
    project_id: str
    action_type: str  # "file_write", "shell_exec", "db_drop", "network_send"
    target_resource: str  # "/home/nadir/code/agent_engine/core/..."
    arguments: Dict[str, Any]
    argument_hash: str  # SHA-256 of canonical JSON arguments
    risk_level: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    reason: str
    expires_at: str  # ISO-8601 timestamp (default TTL: 15 minutes)
    consumed: bool = False
    consumed_at: Optional[str] = None
    reviewer_identity: Optional[str] = None
```

### 2.2. Verification & Replay Protection
* **Argument Tamper Resistance:** If arguments change even by one byte after approval is granted, `SHA256(canonical_json(arguments)) != argument_hash` and the operation fails closed.
* **Single-Use Consumption:** Tokens are marked `consumed=True` immediately upon execution. Replay attempts fail closed.
* **Time Expiration:** Expired tokens cannot be redeemed.

---

## 3. AST Safety Guardrails & Code Execution Boundaries

1. **Static AST Analysis (`core/security/guardrails.py`):**
   * Inspects Python and shell commands for hazardous patterns:
     * Recursive filesystem deletion (`rm -rf /`, `shutil.rmtree("/")`).
     * Direct raw disk writes (`dd if=... of=/dev/sd...`).
     * Netcat/bash reverse shells (`nc -e`, `bash -i >& /dev/tcp/...`).
     * Host privilege escalation (`sudo`, `pkexec`).
     * Arbitrary code execution (`eval()`, `exec()`, `os.system()` with unsanitized variables).
2. **Worktree Isolation for Coding Workflows:**
   * Automated code editing must execute inside an isolated ephemeral Git worktree:
     ```bash
     git worktree add ../agent_engine_worktree_<id> -b agent/<feature>
     ```
   * The canonical repository working tree remains completely untouched until test verification passes and the operator explicitly approves merging the patch.

---

## 4. Credential Vault Architecture (ADR-008)

```text
               ┌───────────────────────────────┐
               │    Credential Access Request  │
               └───────────────┬───────────────┘
                               │
                Is OS Keyring Available?
                     /                  \
                  (Yes)                 (No - Headless/Server)
                   /                      \
        ┌─────────▼──────────┐   ┌─────────▼───────────┐
        │  OS Desktop Keyring│   │  AES-256-GCM Vault  │
        │  (SecretService,   │   │  data/credentials.  │
        │   macOS Keychain,  │   │  vault (PBKDF2-SHA, │
        │   Windows CredMgr) │   │  0o600 permissions) │
        └────────────────────┘   └─────────────────────┘
```

* **Secret Masking Invariant:**
  * All log outputs, telemetry records, and REST API responses mask secrets (`sk-...xxxx`).
  * Plaintext secret exposure requires an explicit administrative parameter (`reveal=true`) and is recorded in the security audit log.

---

## 5. Local Operator Identity Boundary & Limitations (R2.4)

* **IPC Secret Possession vs. Human Identity:**
  * Local IPC authentication verifies possession of the ephemeral secret generated for the active engine launch (`~/.agent_engine/ipc.token`).
  * Shared token possession confirms that the caller resides on the authorized local loopback bus; it does **not** constitute cryptographically verified human identity or enterprise multi-user identity.
* **Single-User Principal (`local_operator`):**
  * The current security model binds operations and approvals to the default local product principal `local_operator`.
  * Multi-user tenancy, strong operator authentication, and cryptographic human signing boundaries are deferred to Milestone R16 (Business / Multi-User RBAC).
* **Fail-Closed Capability Model:**
  * Consequential operations (destructive filesystem writes, arbitrary process execution, financial transactions) require explicit human approval regardless of the caller's IPC token validity.

---

## 6. Renderer JavaScript Heap Trust Boundary

* **Non-Persistent In-Memory Secrets:**
  * `localStorage`, `sessionStorage`, `IndexedDB`, and URL query parameter token transports are strictly prohibited and eliminated. IPC credentials exist solely in JavaScript heap memory during an active session.
* **Trust Limitation:**
  * Any credential resident in browser/renderer JavaScript memory remains subject to exfiltration if the renderer context is compromised (e.g. through Cross-Site Scripting or malicious dependencies).
* **Future Hardening Roadmap:**
  * Under future isolation passes, master IPC credentials will remain strictly confined within the Tauri/Rust native host process. The frontend will invoke fine-grained, capability-bounded Tauri IPC commands rather than handling raw master bearer tokens.

---

## 7. Exact-Operation Cryptographic Authorization & CAS Persistence (R2.3 & R2.4)

* **Operation-Level Enforcement Authority:**
  * Preflight root execution policy checks provide early gating, but the authoritative security boundary sits immediately in front of the actual side effect (`CapabilityBoundary.write_file`, `CapabilityBoundary.delete_file`, `CapabilityBoundary.run_subprocess`, `CapabilityBoundary.invoke`).
* **Canonical Versioned Digest (`operation_digest_version = 1`):**
  * Exact operation binding encompasses:
    ```json
    {
      "version": 1,
      "capability": "filesystem",
      "operation": "filesystem.delete_file",
      "normalized_arguments": {"path": "/safe/project/tmp.txt"},
      "execution_binding": "exec_123",
      "actor_binding": "local_operator"
    }
    ```
  * Arguments are recursively normalized: keys sorted alphabetically, Unicode normalized to NFC, floats formatted to canonical decimals, paths resolved to project-contained canonical strings, commands split into executable + argv arrays.
* **Durable SQLite Persistence with Atomic CAS Consumption:**
  * Approvals are durably persisted in SQLite (`approvals` table).
  * Consumption uses database-level Compare-And-Swap:
    ```sql
    UPDATE approvals
    SET status = 'consumed', consumed_at = ?
    WHERE approval_id = ?
      AND token_verifier = ?
      AND status = 'approved'
      AND expires_at > ?;
    ```
  * Exactly one concurrent consumer can succeed (`cursor.rowcount == 1`). Replays, post-restart reuses, or expired executions fail closed.
* **Raw Bearer Token Elimination:**
  * The database, ledger, logs, and public API representations persist strictly the `token_verifier` (`SHA-256(bearer_token)`). Raw bearer tokens are never written to disk or audit logs.

---

## 8. Canonical Workspace Path Enforcement & Containment (R2.5)

* **Trusted Scope Authority & Hierarchy:**
  * Authorized workspace scopes are established exclusively from trusted sources (project root, capability metadata declarations, and administrative policy). Arbitrary caller/LLM payloads may only narrow, never widen, the authorized boundary:
    $$\text{effective\_scopes} = \text{project\_root} \cap \bigcup(\text{capability\_scopes}) \cap \bigcup(\text{policy\_scopes}) \cap \text{optional\_caller\_narrowing}$$
  * If effective authority is empty (disjoint capability and policy scopes, or invalid caller narrowing), execution fails closed with `WorkspacePathViolation`.
  * Caller narrowing is strictly separated from security authority (`requested_workspace_scope` / `requested_working_directory`). Any attempt by a caller to widen scopes (e.g. requesting project root when capability is scoped to `src/`) is strictly ignored fail-closed.
  * All configured scopes undergo self-validation on initialization: any scope resolving outside `project_root` raises `WorkspacePathViolation`.

* **Single Canonical Value Object (`ResolvedWorkspacePath`):**
  * All path resolution produces an immutable `ResolvedWorkspacePath` object implementing `os.PathLike[str]` with explicit fields:
    * `requested_path: str`
    * `canonical_path: Path`
    * `canonical_relative_path: str` (relative to project root)
    * `project_root: Path`
    * `matched_scope: Path`
    * `exists: bool`
  * `__fspath__()` returns `str(canonical_path)` ensuring `os.fspath(val)` always produces the canonical destination on disk even for malicious or aliased inputs.
  * `to_public_dict()` redacts host machine absolute paths, exposing only project-relative paths and relative scope identifiers.

* **Pre-Creation / Non-Existent Target Handling:**
  * Non-existent targets are resolved by ascending the parent hierarchy to locate the nearest existing ancestor, resolving its realpath, verifying that all intermediate non-existent components contain no lexical traversal (`..`, `.`), and verifying that the reconstructed target resides strictly within the matched scope and project root.

* **Internal Symlinks & Exact Approval Binding:**
  * Symlinks are resolved to their canonical destination (`canonical_relative_path`) before policy evaluation and approval registration.
  * Exact approval tokens bind to the canonical resolved destination, NOT the symlink alias. If an internal symlink is swapped to point to a different file between authorization and execution, the cryptographic argument digest fails closed.
  * Immutable project identity (`project_id`) is cryptographically bound into file authorization and operation digests. An approval granted for Project A cannot authorize Project B even with identical relative paths.

* **Pre-Side-Effect TOCTOU Revalidation:**
  * In addition to pre-authorization resolution, `CapabilityBoundary` re-resolves target paths immediately before side effects (`read_file`, `write_file`, `delete_file`, `run_subprocess`).
  * If `current_resolved.canonical_path != initial_resolved.canonical_path`, execution halts fail-closed with `SecurityBoundaryViolation`.

* **Residual Filesystem TOCTOU Limitations:**
  * Standard user-space path canonicalization cannot eliminate the fundamental filesystem race between `realpath()` and subsequent syscalls (`open()`, `unlink()`, `mkdir()`) without kernel-level file descriptor pinning (`openat2` with `RESOLVE_BENEATH` on Linux 5.6+). On systems where local hostile processes share filesystem permissions, an attacker with microsecond scheduling control could theoretically swap a symlink between the pre-side-effect check and the filesystem syscall. Full mitigation requires OS-level containerization/sandboxing (Milestone R2 sandbox isolation passes).

* **Cross-Platform Normalization & Attack Vector Rejection:**
  * Rejects null bytes (`\0`) fail-closed in all path inputs and declared scopes.
  * Rejects ambiguous Windows drive-relative paths (e.g. `C:file.txt`) on all platforms.
  * Rejects foreign Windows drive absolute paths (e.g. `C:\Windows\System32`) on POSIX systems.
  * Cross-platform path semantics are implemented and tested at the unit level.
  * Subprocess boundaries enforce canonical working directory (`cwd`) resolution, requiring `cwd` to exist, be a directory, and reside within authorized scopes. Subprocess commands are executed with structured argument vectors (`*cmd`), eliminating shell injection.

