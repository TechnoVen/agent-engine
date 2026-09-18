# Agent Engine — Product Specification

> **Status:** Canonical Product Definition  
> **Release Target:** Agent Engine 0.5 “Nadir Edition” (Founder MVP)  
> **Audience:** Maintainers, Architects, Product Owners, Developers  

---

## 1. Product North Star

> **One trustworthy local-first AI operating environment where models, skills, tools, workflows, knowledge and automation are installed and governed once, can be used from every surface, and improve from verified outcomes without sacrificing user control.**

Agent Engine is not another disposable chatbot, thin LLM wrapper, or fragmented developer framework. It is an **integrated personal and professional AI operating environment** designed to run on the user's personal workstation, maintain zero-trust privacy, manage local and cloud models transparently, and orchestrate verifiable work across multiple domains.

---

## 2. Target Release: Agent Engine 0.5 (Nadir Founder MVP)

The immediate product milestone is **Agent Engine 0.5 “Nadir Edition”**. 

The goal of version 0.5 is **not** to build a public marketplace, an enterprise multi-tenant server, or an unbounded feature surface. It is to build a rock-solid, truthful tool that the founder (Nadir) can use all day, every day for:
* Persistent project-scoped chat.
* Multi-model routing (Ollama/local + cloud frontier).
* Document ingestion and grounded context retrieval.
* Long-form writing with iterative critique and artifact creation.
* Deep, cited research with provenance tracking.
* Safe, worktree-isolated coding assistance with automated tests.
* Read-only financial CSV and invoice analysis.
* Dependable recurring automation that survives desktop reboots.
* Truthful spend and latency tracking without fabricated numbers.

---

## 3. Product Personas

| Persona | Role | Primary Goal in Agent Engine |
|---|---|---|
| **Nadir / Founder User** | Daily Operator & Founder | Uses Agent Engine daily for coding, writing, research, business planning, and personal workflows. Demands rock-solid reliability, zero fake success, and absolute privacy control. |
| **Everyday User** | Knowledge Worker / Writer | Wants high-quality AI assistance without needing to know model architectures, context windows, or prompting quirks. |
| **Power User** | Technical Professional | Demands fine-grained control over model routing, temperature, local vs. cloud execution, cost caps, and approval policies. |
| **Developer** | Software Engineer / Creator | Builds code in isolated worktrees, creates custom skills/tools, inspects execution traces, and runs automated evaluations. |
| **Workspace Admin** | Team Lead / Security Officer | Manages project environments, credential vaults, trust boundaries, and approval queues. |
| **Package Author** | Ecosystem Contributor | Authors reusable skills, tools, and capability packs with declarative manifests and safety contracts. |
| **Enterprise Admin** | IT / Systems Administrator | Oversees multi-user deployment, SSO, directory synchronization, and compliance audit logs (Post-1.0). |

---

## 4. MVP Capability Packs (Release 0.5)

To maintain focus and avoid architectural bloat, Agent Engine 0.5 ships with exactly **six curated Capability Packs**:

1. **Core Pack:**
   * Universal conversational shell (`ChatInput`), persistent session management, project workspaces, model selector, execution ledger, approval queue, and scheduled job monitor.
2. **Personal Pack:**
   * General notes, task lists, personal file search, and simple personal automation.
3. **Writing Pack:**
   * Multi-stage document generation: Outline $\rightarrow$ Draft $\rightarrow$ Style Review $\rightarrow$ Factual Review $\rightarrow$ Final Markdown/Docx Artifact.
4. **Research Pack:**
   * Research planning, multi-source evidence collection, claim extraction, and citation synthesis with provenance links.
5. **Developer Pack:**
   * Issue diagnosis, technical plan generation, isolated Git worktree implementation, automated pytest validation, and independent code review.
6. **Finance Reader Pack:**
   * Invoice entity extraction, bank CSV transaction categorization, and reconciliation proposals. **Strictly read-only: zero financial write/movement actions.**

---

## 5. The 12 Founder User Journeys (MVP-J1 – MVP-J12)

Every release candidate for Agent Engine 0.5 must satisfy the following 12 golden journeys:

* **MVP-J1 — Project-Aware Conversation:**
  * *Story:* As Nadir, I want to open the Agent Engine project and ask questions that use its files, architecture docs, and prior sessions without repeatedly re-explaining context.
  * *Pass Condition:* Real project instructions reach the model; the execution ledger explicitly records retrieved context passages.
* **MVP-J2 — Writing Workflow:**
  * *Story:* As Nadir, I want to turn rough notes into a polished article through structured drafting, style critique, and claim verification.
  * *Pass Condition:* Final document is saved as a persistent artifact; every model and tool step is traceable.
* **MVP-J3 — Deep Research:**
  * *Story:* As Nadir, I want evidence-aware research distinguishing verified facts, uncertainty, and model synthesis.
  * *Pass Condition:* Sources and extracted citations are traceable; retrieval failures are reported truthfully rather than masked as success.
* **MVP-J4 — Coding Workflow:**
  * *Story:* As Nadir, I want the agent to diagnose an issue, create a plan, execute in an isolated Git worktree, run tests, and perform a self-review.
  * *Pass Condition:* Canonical branches are never touched without approval; test execution output is linked directly to the run ledger.
* **MVP-J5 — Document Intelligence:**
  * *Story:* As Nadir, I want to drop PDFs, Markdown, CSVs, and code into a project and have the engine choose the correct parsing and retrieval strategy automatically.
  * *Pass Condition:* User does not manually toggle RAG knobs; parsing decisions and chunk citations are saved in execution metadata.
* **MVP-J6 — Finance Reader:**
  * *Story:* As Nadir, I want the engine to parse invoices and bank statements, proposing classifications while explicitly highlighting low-confidence items.
  * *Pass Condition:* Outputs are strictly proposals; zero automated transaction posting is permitted.
* **MVP-J7 — Local / Cloud Dynamic Routing:**
  * *Story:* As Nadir, I want private/simple tasks handled by local models ($0 cost) while complex tasks route to frontier cloud models according to cost-per-success metrics.
  * *Pass Condition:* Actual provider used is clearly visible; routing aligns with policy rules.
* **MVP-J8 — Consequential Operation Approval:**
  * *Story:* As Nadir, I want dangerous operations (file overwrite, shell command, database write) to pause with an exact argument preview for operator sign-off.
  * *Pass Condition:* Altered arguments invalidate previous approval tokens; replay attacks fail closed.
* **MVP-J9 — Real Cancellation:**
  * *Story:* As Nadir, I want the Stop button to genuinely halt local/cloud inference and tool processes.
  * *Pass Condition:* Upstream processes are cancelled; execution status is marked `CANCELLED`, never `COMPLETED`.
* **MVP-J10 — Desktop Restart Recovery:**
  * *Story:* As Nadir, I want active sessions, queued jobs, and paused approval gates to survive closing or crashing the desktop app.
  * *Pass Condition:* In-flight state resumes or gracefully presents recovery options without duplicating already-completed steps.
* **MVP-J11 — Scheduled Durable Automation:**
  * *Story:* As Nadir, I want a weekly project review to run automatically off-peak and generate a summary brief.
  * *Pass Condition:* Scheduler survives system restart and triggers exactly one idempotent durable job per scheduled occurrence.
* **MVP-J12 — Truthful Execution History:**
  * *Story:* As Nadir, I want an uncompromised view of which models, tools, skills, tokens, dollar costs, and latencies occurred.
  * *Pass Condition:* Zero fabricated telemetry; unknown or estimated metrics are explicitly labeled.

---

## 6. What Agent Engine Is NOT (Non-Goals for 0.5)

* **Not a cloud-hosted SaaS platform:** 0.5 is 100% local-first desktop application.
* **Not an uncurated marketplace:** 0.5 only includes verified built-in capability packs.
* **Not an autonomous financial agent:** 0.5 will never move money or execute payments.
* **Not a benchmark gaming tool:** We optimize for quality-adjusted cost per successful task, not superficial leaderboard scores.
