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
