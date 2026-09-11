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
      return data.pipelines || [];
    } catch {
      return [];
    }
  }

  async getSessions(limit = 10): Promise<any[]> {
    try {
      const res = await fetch(`${this.base}/v1/sessions?limit=${limit}`);
      if (!res.ok) return [];
      const data = await res.json();
      return data.sessions || [];
    } catch {
      return [];
    }
  }

  async getCredentials(service?: string): Promise<CredentialItem[]> {
    try {
      const query = service ? `?service=${encodeURIComponent(service)}` : '';
      const res = await fetch(`${this.base}/v1/credentials${query}`);
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async setCredential(payload: SetCredentialPayload): Promise<CredentialItem> {
    const res = await fetch(`${this.base}/v1/credentials`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
        `${this.base}/v1/credentials/${encodeURIComponent(service)}/${encodeURIComponent(key)}?reveal=${reveal}`
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
        { method: 'DELETE' }
      );
      return res.ok;
    } catch {
      return false;
    }
  }

  async testCredential(
    provider: string,
    apiKey?: string
  ): Promise<CredentialTestResult> {
    const res = await fetch(`${this.base}/v1/credentials/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, api_key: apiKey }),
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

export const sidecarClient = new SidecarClient();

