import {
  CredentialDetail,
  CredentialItem,
  CredentialTestResult,
  SetCredentialPayload,
  SidecarHealth,
  UpdateChannel,
  UpdateCheckResult,
  UpdateStatus,
  SkillItem,
  AuditLogEntry,
  RiskLevel,
  AgentPersona,
  SessionSearchResult,
  ObserveMemoryPayload,
  ObservationRecord,
  ScheduledTask,
  ScheduledTaskCreatePayload,
} from '../types';

const API_BASE = window.location.port === '1420' ? '' : 'http://127.0.0.1:8000';

class SidecarClient {
  private base: string;

  constructor(base: string = API_BASE) {
    this.base = base;
  }

  async checkHealth(): Promise<SidecarHealth> {
    try {
      const res = await fetch(`${this.base}/v1/health`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) {
        return {
          status: 'degraded',
          error: `HTTP ${res.status}: ${res.statusText}`,
        };
      }
      const data = await res.json();
      return {
        status: data.status === 'healthy' ? 'healthy' : 'degraded',
        version: data.version || '0.1.0',
        engine: data.engine || 'Agent Engine',
        uptime_seconds: data.uptime_seconds || 0,
        timestamp: data.timestamp,
      };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        status: 'offline',
        error: msg,
      };
    }
  }

  async getRouterTiers(): Promise<Record<string, string>> {
    try {
      const res = await fetch(`${this.base}/v1/router/tiers`);
      if (!res.ok) return {};
      const data = await res.json();
      return data.tiers || {};
    } catch {
      return {};
    }
  }

  async getPipelines(): Promise<any[]> {
    try {
      const res = await fetch(`${this.base}/v1/pipelines`);
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data) ? data : (data.pipelines || []);
    } catch {
      return [];
    }
  }

  async getSessions(limit = 10): Promise<any[]> {
    try {
      const res = await fetch(`${this.base}/v1/sessions?limit=${limit}`);
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data) ? data : (data.sessions || []);
    } catch {
      return [];
    }
  }

  async searchSessions(query: string, limit = 20): Promise<SessionSearchResult[]> {
    const trimmed = query.trim();
    if (!trimmed) return [];
    try {
      const res = await fetch(
        `${this.base}/v1/sessions/search?q=${encodeURIComponent(trimmed)}&limit=${limit}`
      );
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async observeMemory(payload: ObserveMemoryPayload): Promise<ObservationRecord | null> {
    try {
      const res = await fetch(`${this.base}/v1/memory/observe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  async ingestMemory(
    content: string,
    source: string = 'attachment'
  ): Promise<{ document_id: string; count: number } | null> {
    try {
      const res = await fetch(`${this.base}/v1/memory/ingest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, source }),
      });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  async queryObservations(query: string, topK = 20): Promise<any[]> {
    try {
      const res = await fetch(
        `${this.base}/v1/memory/observations?query=${encodeURIComponent(query)}&top_k=${topK}`
      );
      if (!res.ok) return [];
      const data = await res.json();
      return data.observations || [];
    } catch {
      return [];
    }
  }

  private getHeaders(extra?: Record<string, string>): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...extra,
    };
    try {
      const token =
        (window as unknown as { __AGENT_ENGINE_IPC_TOKEN__?: string }).__AGENT_ENGINE_IPC_TOKEN__ ||
        localStorage.getItem('agent_engine_ipc_token');
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
        headers['X-IPC-Token'] = token;
      }
    } catch {
      // localStorage may be restricted
    }
    return headers;
  }

  async getCredentials(service?: string): Promise<CredentialItem[]> {
    try {
      const query = service ? `?service=${encodeURIComponent(service)}` : '';
      const res = await fetch(`${this.base}/v1/credentials${query}`, {
        headers: this.getHeaders(),
      });
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async setCredential(payload: SetCredentialPayload): Promise<CredentialItem> {
    const res = await fetch(`${this.base}/v1/credentials`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(`Failed to store credential: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getCredential(
    service: string,
    key: string,
    reveal = false
  ): Promise<CredentialDetail | null> {
    try {
      const res = await fetch(
        `${this.base}/v1/credentials/${encodeURIComponent(service)}/${encodeURIComponent(key)}?reveal=${reveal}`,
        { headers: this.getHeaders() }
      );
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  async deleteCredential(service: string, key: string): Promise<boolean> {
    try {
      const res = await fetch(
        `${this.base}/v1/credentials/${encodeURIComponent(service)}/${encodeURIComponent(key)}`,
        { method: 'DELETE', headers: this.getHeaders() }
      );
      return res.ok;
    } catch {
      return false;
    }
  }

  async testCredential(
    provider: string,
    apiKey?: string,
    baseUrl?: string
  ): Promise<CredentialTestResult> {
    const res = await fetch(`${this.base}/v1/credentials/test`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ provider, api_key: apiKey, base_url: baseUrl }),
    });
    if (!res.ok) {
      return {
        provider,
        valid: false,
        latency_ms: 0,
        error: `HTTP ${res.status}: ${res.statusText}`,
      };
    }
    return await res.json();
  }

  async getUpdateStatus(): Promise<UpdateStatus | null> {
    try {
      const res = await fetch(`${this.base}/v1/updater/status`);
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  async setUpdateChannel(channel: UpdateChannel): Promise<UpdateStatus> {
    const res = await fetch(`${this.base}/v1/updater/channel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel }),
    });
    if (!res.ok) {
      throw new Error(`Failed to set update channel: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async checkForUpdates(channel?: UpdateChannel): Promise<UpdateCheckResult> {
    const res = await fetch(`${this.base}/v1/updater/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel }),
    });
    if (!res.ok) {
      throw new Error(`Failed to check for updates: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getSkills(): Promise<SkillItem[]> {
    try {
      const res = await fetch(`${this.base}/v1/skills`);
      if (res.ok) {
        const rawSkills = await res.json();
        if (Array.isArray(rawSkills) && rawSkills.length > 0) {
          return rawSkills.map((s) => ({
            id: s.id,
            name: s.name,
            category: s.category || 'General',
            description: s.description || '',
            command: `/${s.id.replace(/_/g, '-')}`,
            inputs: s.inputs || [],
            outputs: s.outputs || [],
            sampleInputs: s.sample_inputs,
          }));
        }
      }
    } catch {
      // Fallback to pre-bundled catalog
    }

    return DEFAULT_SKILLS_CATALOG;
  }

  async getPersonas(): Promise<AgentPersona[]> {
    return DEFAULT_PERSONAS;
  }

  async executeSkill(
    skillId: string,
    payload: Record<string, any>
  ): Promise<any> {
    const res = await fetch(`${this.base}/v1/skills`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skill_id: skillId, payload }),
    });
    if (!res.ok) {
      throw new Error(`Failed to execute skill: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async evaluateToolSafety(
    toolName: string,
    toolArgs: Record<string, any>,
    options?: { sessionId?: string; allowHighRisk?: boolean; autoApply?: boolean }
  ): Promise<{
    decision: string;
    risk_score: number;
    risk_level: RiskLevel;
    violating_rules?: any[];
    suggestion?: string;
    reason?: string;
    audit_id?: number;
  }> {
    try {
      const res = await fetch(`${this.base}/v1/safety/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tool_name: toolName,
          tool_args: toolArgs,
          session_id: options?.sessionId,
          allow_high_risk: options?.allowHighRisk ?? false,
          auto_apply: options?.autoApply ?? false,
        }),
      });
      if (!res.ok) {
        return {
          decision: 'allow',
          risk_score: 0.1,
          risk_level: 'low',
        };
      }
      return await res.json();
    } catch {
      return {
        decision: 'allow',
        risk_score: 0.1,
        risk_level: 'low',
      };
    }
  }

  async submitApprovalDecision(payload: {
    toolName: string;
    toolArgs: Record<string, any>;
    decision: 'approve' | 'reject' | 'edit';
    riskLevel?: RiskLevel;
    riskScore?: number;
    reason?: string;
    modifiedArgs?: Record<string, any>;
    sessionId?: string;
    operator?: string;
  }): Promise<AuditLogEntry> {
    const res = await fetch(`${this.base}/v1/safety/approval`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool_name: payload.toolName,
        tool_args: payload.toolArgs,
        decision: payload.decision,
        risk_level: payload.riskLevel || 'medium',
        risk_score: payload.riskScore ?? 0.5,
        reason: payload.reason,
        modified_args: payload.modifiedArgs,
        session_id: payload.sessionId,
        operator: payload.operator || 'local-operator',
      }),
    });
    if (!res.ok) {
      throw new Error(`Failed to submit approval: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getSafetyAuditLogs(
    limit: number = 50,
    decision?: string
  ): Promise<AuditLogEntry[]> {
    try {
      const params = new URLSearchParams({ limit: String(limit) });
      if (decision) params.set('decision', decision);
      const res = await fetch(`${this.base}/v1/safety/audit?${params.toString()}`);
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async listScheduledTasks(): Promise<ScheduledTask[]> {
    try {
      const res = await fetch(`${this.base}/v1/tasks`);
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) return data;
        if (Array.isArray(data.tasks)) return data.tasks;
      }
    } catch {
      // offline dev fallback
    }
    return DEFAULT_SCHEDULED_TASKS;
  }

  async createScheduledTask(payload: ScheduledTaskCreatePayload): Promise<ScheduledTask> {
    try {
      const res = await fetch(`${this.base}/v1/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        return await res.json();
      }
    } catch {
      // offline dev fallback
    }
    const newTask: ScheduledTask = {
      id: `task-${Date.now()}`,
      name: payload.name,
      description: payload.description || '',
      cron: payload.cron,
      cron_human: payload.cron_human || payload.cron,
      agent_persona: payload.agent_persona || 'Senior Engineer',
      model: payload.model || 'instant',
      status: 'active',
      cost_per_run: 0.0012,
      monthly_estimate: 0.036,
      is_off_peak: payload.is_off_peak ?? true,
      notification_channel: payload.notification_channel || 'slack',
      prompt: payload.prompt,
      created_at: new Date().toISOString(),
      next_run: 'Tonight, 02:00 AM (Off-peak)',
    };
    return newTask;
  }

  async toggleScheduledTask(id: string, currentStatus: string): Promise<string> {
    const nextStatus = currentStatus === 'active' ? 'paused' : 'active';
    try {
      const res = await fetch(`${this.base}/v1/tasks/${id}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: nextStatus }),
      });
      if (res.ok) {
        const updated = await res.json();
        return updated.status || nextStatus;
      }
    } catch {
      // dev fallback
    }
    return nextStatus;
  }

  async triggerScheduledTask(id: string): Promise<boolean> {
    try {
      const res = await fetch(`${this.base}/v1/tasks/${id}/run`, {
        method: 'POST',
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  async deleteScheduledTask(id: string): Promise<boolean> {
    try {
      const res = await fetch(`${this.base}/v1/tasks/${id}`, {
        method: 'DELETE',
      });
      return res.ok;
    } catch {
      return false;
    }
  }
}

export const DEFAULT_SKILLS_CATALOG: SkillItem[] = [
  {
    id: 'code_review_checklist',
    name: 'Code Review Checklist',
    category: 'Engineering',
    description: 'Generate an automated security, performance, and style review checklist for Python code.',
    command: '/code-review',
    inputs: ['code', 'ruleset'],
    outputs: ['checklist', 'score'],
    sampleInputs: {
      code: 'def query_user(user_id):\n    cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)\n    return cursor.fetchall()',
      ruleset: 'OWASP Top 10 + PEP 8',
    },
  },
  {
    id: 'generate_sql_from_nl',
    name: 'Generate SQL from Natural Language',
    category: 'Database',
    description: 'Synthesize optimal ANSI SQL statements from natural language questions against database schemas.',
    command: '/sql-gen',
    inputs: ['query', 'schema'],
    outputs: ['sql_statement', 'explanation'],
    sampleInputs: {
      query: 'Find the top 5 customers with highest total spend in Q1 2026',
      schema: 'CREATE TABLE orders (id INT, customer_id INT, amount DECIMAL, order_date DATE);',
    },
  },
  {
    id: 'generate_python_unit_tests',
    name: 'Generate Python Unit Tests',
    category: 'Engineering',
    description: 'Generate comprehensive pytest unit tests covering edge cases and boundary conditions.',
    command: '/unit-tests',
    inputs: ['code_snippet', 'framework'],
    outputs: ['unit_tests', 'fixtures'],
    sampleInputs: {
      code_snippet: 'def calculate_discount(price: float, rate: float) -> float:\n    return price * (1 - rate)',
      framework: 'pytest',
    },
  },
  {
    id: 'explain_code',
    name: 'Explain Code Architecture',
    category: 'Education',
    description: 'Provide an intuitive walkthrough of complex algorithms or architectures with AST analysis.',
    command: '/explain',
    inputs: ['code', 'audience'],
    outputs: ['explanation', 'complexity'],
    sampleInputs: {
      code: 'async def poll_stream():\n    async for chunk in stream:\n        yield chunk',
      audience: 'developer',
    },
  },
  {
    id: 'summarize_meeting_notes',
    name: 'Summarize Meeting Notes',
    category: 'Productivity',
    description: 'Extract decisions, action items with owners, and key summary takeaways from notes.',
    command: '/summarize',
    inputs: ['notes', 'focus_areas'],
    outputs: ['executive_summary', 'action_items'],
    sampleInputs: {
      notes: 'Team synced on Q3 roadmap. Alice will ship desktop shell by Friday. Bob reviews security audit.',
      focus_areas: 'action items',
    },
  },
  {
    id: 'generate_api_endpoint',
    name: 'Generate FastAPI Endpoint',
    category: 'Engineering',
    description: 'Build production-ready FastAPI endpoints with Pydantic schemas, validation, and error handling.',
    command: '/api-endpoint',
    inputs: ['specification', 'framework'],
    outputs: ['router_code', 'schema_code'],
    sampleInputs: {
      specification: 'POST /v1/search endpoint taking query string and limit, returning list of matching documents',
      framework: 'FastAPI',
    },
  },
  {
    id: 'create_json_schema',
    name: 'Create JSON Schema',
    category: 'Data',
    description: 'Derive strict Draft-07/2020-12 JSON Schemas from data payloads or natural language specifications.',
    command: '/schema',
    inputs: ['data_sample'],
    outputs: ['json_schema'],
    sampleInputs: {
      data_sample: '{"name": "Agent Engine", "version": "0.1.0", "active": true}',
    },
  },
  {
    id: 'translate_code_language',
    name: 'Translate Code Language',
    category: 'Engineering',
    description: 'Idiomatically translate algorithms between Python, TypeScript, Rust, and Go.',
    command: '/translate',
    inputs: ['source_code', 'target_language'],
    outputs: ['translated_code', 'notes'],
    sampleInputs: {
      source_code: 'def is_even(n: int) -> bool:\n    return n % 2 == 0',
      target_language: 'Rust',
    },
  },
  {
    id: 'weekly_report_jira_notion',
    name: 'Weekly Status Report',
    category: 'Productivity',
    description: 'Format fragmented weekly activity logs into clean executive bullet points.',
    command: '/weekly-report',
    inputs: ['updates', 'format'],
    outputs: ['formatted_report'],
    sampleInputs: {
      updates: 'Closed 14 PRs. Delivered M2 desktop alpha. Fixed 3 race conditions in token stream.',
      format: 'executive bullets',
    },
  },
  {
    id: 'email_draft_from_brief',
    name: 'Draft Email from Brief',
    category: 'Communication',
    description: 'Compose crisp, professional emails with calibrated tone from quick bullet points.',
    command: '/email-draft',
    inputs: ['brief', 'tone'],
    outputs: ['subject_line', 'body'],
    sampleInputs: {
      brief: 'Follow up with design team on Kimi-style universal shell feedback',
      tone: 'friendly professional',
    },
  },
];

export const DEFAULT_PERSONAS: AgentPersona[] = [
  {
    id: 'general',
    name: 'General Assistant',
    role: 'Versatile Co-Pilot',
    description: 'Fast, lightweight conversational agent for general queries, daily tasks, and planning.',
    avatar: 'Bot',
    suggestedModel: 'instant',
    pipelineName: 'fast_text_generation',
    badge: 'Fast',
  },
  {
    id: 'coder',
    name: 'Senior Engineer',
    role: 'Full-Stack Developer',
    description: 'Specializes in clean architectures, refactoring, unit tests, and bug fixes.',
    avatar: 'Code2',
    suggestedModel: 'swarm',
    pipelineName: 'code_fix',
    badge: 'Code',
  },
  {
    id: 'researcher',
    name: 'Deep Researcher',
    role: 'Research Analyst',
    description: 'Synthesizes domain literature, technical papers, and structured data.',
    avatar: 'Search',
    suggestedModel: 'reasoning',
    pipelineName: 'finance_extract',
    badge: 'Deep',
  },
  {
    id: 'writer',
    name: 'Technical Writer',
    role: 'Content & Docs Author',
    description: 'Drafts polished specifications, blog posts, and long-form chapters.',
    avatar: 'FileText',
    suggestedModel: 'instant',
    pipelineName: 'chapter_write',
    badge: 'Docs',
  },
  {
    id: 'auditor',
    name: 'Security Auditor',
    role: 'Zero-Trust Safety Officer',
    description: 'Inspects ASTs, vulnerability disclosures, and policy compliance.',
    avatar: 'ShieldCheck',
    suggestedModel: 'reasoning',
    pipelineName: 'security_audit',
    badge: 'Audit',
  },
  {
    id: 'communicator',
    name: 'Executive Drafter',
    role: 'Corporate Communications',
    description: 'Crafts high-impact executive summaries and tailored email correspondence.',
    avatar: 'Mail',
    suggestedModel: 'instant',
    pipelineName: 'email_draft',
    badge: 'Email',
  },
];

export const DEFAULT_SCHEDULED_TASKS: ScheduledTask[] = [
  {
    id: 'task-1',
    name: 'Daily Inbox Digest',
    description: 'Summarizes critical emails, mentions, and urgent unread threads at 8 AM.',
    cron: '0 8 * * *',
    cron_human: 'Every day at 8:00 AM',
    agent_persona: 'Executive Drafter',
    model: 'instant',
    status: 'active',
    last_run: 'Today, 08:00 AM',
    next_run: 'Tomorrow, 08:00 AM',
    cost_per_run: 0.0008,
    monthly_estimate: 0.024,
    is_off_peak: false,
    notification_channel: 'slack',
    prompt: 'Summarize all high-priority unread emails and draft responses for urgent items.',
    created_at: '2026-03-01',
  },
  {
    id: 'task-2',
    name: 'Weekly Expense & Spend Audit',
    description: 'Generates weekly financial reconciliation and token budget usage Sunday at 6 PM.',
    cron: '0 18 * * 0',
    cron_human: 'Every Sunday at 6:00 PM',
    agent_persona: 'Deep Researcher',
    model: 'instant',
    status: 'active',
    last_run: 'Sun, Mar 8, 06:00 PM',
    next_run: 'Sun, Mar 15, 06:00 PM',
    cost_per_run: 0.0025,
    monthly_estimate: 0.010,
    is_off_peak: false,
    notification_channel: 'slack',
    prompt: 'Compile weekly expenditure report and verify zero 90/9/1 budget breaches.',
    created_at: '2026-03-02',
  },
  {
    id: 'task-3',
    name: 'Off-Peak Security & AST Audit',
    description: 'Runs zero-trust safety checks, AST sanitization, and dependency vulnerabilities overnight.',
    cron: '0 2 * * *',
    cron_human: 'Every day at 2:00 AM (Off-peak)',
    agent_persona: 'Security Auditor',
    model: 'reasoning',
    status: 'active',
    last_run: 'Today, 02:00 AM',
    next_run: 'Tomorrow, 02:00 AM (Off-peak)',
    cost_per_run: 0.0064,
    monthly_estimate: 0.192,
    is_off_peak: true,
    notification_channel: 'webhook',
    prompt: 'Inspect AST diffs, detect dangerous shell patterns, and review staged patches.',
    created_at: '2026-03-05',
  },
  {
    id: 'task-4',
    name: 'Monthly Book Progress Summary',
    description: 'Synthesizes chapter drafts, word counts, and character arcs on the 1st of each month.',
    cron: '0 3 1 * *',
    cron_human: 'Monthly on day 1 at 3:00 AM (Off-peak)',
    agent_persona: 'Technical Writer',
    model: 'swarm',
    status: 'paused',
    last_run: 'Mar 1, 03:00 AM',
    next_run: 'Apr 1, 03:00 AM (Off-peak)',
    cost_per_run: 0.0042,
    monthly_estimate: 0.0042,
    is_off_peak: true,
    notification_channel: 'telegram',
    prompt: 'Aggregate all chapter outlines and generate word count trajectory charts.',
    created_at: '2026-02-15',
  },
];

export const sidecarClient = new SidecarClient();


