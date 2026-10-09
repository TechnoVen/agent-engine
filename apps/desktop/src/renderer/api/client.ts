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
  SkillDetailed,
  SkillRegistryPackage,
  SkillCollectionItem,
  AuditLogEntry,
  RiskLevel,
  AgentPersona,
  SessionSearchResult,
  ObserveMemoryPayload,
  ObservationRecord,
  ScheduledTask,
  ScheduledTaskCreatePayload,
  PendingOperation,
  SafetyPolicyRuleInfo,
  CostMetrics,
  BudgetConfig,
  DistillationCandidate,
  PolicyYamlResponse,
  DryRunRequest,
  DryRunResult,
  PaginatedAuditLogsResponse,
  HardwareTelemetry,
  SpeedRecordPayload,
  AppSettings,
  DiagnosticsBundle,
  AdapterMetadata,
  AdapterHealth,
  AdapterExecutionRequest,
  AdapterExecutionResponse,
  CollaborativeRoom,
  CreateRoomPayload,
  RoomParticipant,
  AddRoomParticipantPayload,
  RoomTask,
  CreateRoomTaskPayload,
  SwarmCase,
  SwarmRunResult,
  WorkflowDefinition,
  WorkflowRun,
  WorkflowValidationResult,
  PendingGateInfo,
  CatalogModelEntry,
  LocalRecommendationResponse,
  TaskRequirements,
  DownloadStatus,
  ModelEconomicsSummary,
  ProviderConnectionVerification,
  RoutingObjective,
  PrivacyBoundary,
} from '../types';

const API_BASE = window.location.port === '1420' ? '' : 'http://127.0.0.1:8000';

class SidecarClient {
  private base: string;
  private inMemoryToken: string | null = null;

  constructor(base: string = API_BASE) {
    this.base = base;
  }

  setIpcToken(token: string | null): void {
    this.inMemoryToken = token;
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

  async getSession(sessionId: string): Promise<any | null> {
    try {
      const res = await fetch(`${this.base}/v1/sessions/${encodeURIComponent(sessionId)}`, {
        headers: this.getHeaders(),
      });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  async runPipeline(name: string, inputs: Record<string, any>): Promise<any> {
    const res = await fetch(`${this.base}/v1/pipelines/${encodeURIComponent(name)}/run`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ inputs }),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(errData.detail || `Pipeline execution failed: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async streamChatCompletion(options: {
    prompt: string;
    sessionId?: string;
    model?: string;
    routingObjective?: RoutingObjective;
    privacyBoundary?: PrivacyBoundary;
    signal?: AbortSignal;
    onToken: (token: string) => void;
    onRoutingResolved?: (routingData: any) => void;
    onApprovalRequired?: (approvalData: any) => void;
    onCostUpdate?: (costData: any) => void;
    onError?: (error: string) => void;
    onDone?: (doneData?: any) => void;
  }): Promise<void> {
    const {
      prompt,
      sessionId,
      model,
      routingObjective,
      privacyBoundary,
      signal,
      onToken,
      onRoutingResolved,
      onApprovalRequired,
      onCostUpdate,
      onError,
      onDone,
    } = options;
    try {
      const res = await fetch(`${this.base}/v1/chat/completions`, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify({
          prompt,
          session_id: sessionId,
          model,
          routing_objective: routingObjective,
          privacy_boundary: privacyBoundary,
          stream: true,
        }),
        signal,
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({ detail: `HTTP ${res.status}: ${res.statusText}` }));
        const errMsg = errJson.detail || `HTTP ${res.status}: ${res.statusText}`;
        onError?.(errMsg);
        return;
      }

      if (!res.body) {
        onError?.('Response body is empty');
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith('data: ')) {
            const jsonStr = trimmed.slice(6).trim();
            if (!jsonStr) continue;
            try {
              const payload = JSON.parse(jsonStr);
              if (payload.event === 'token' && payload.delta) {
                onToken(payload.delta);
              } else if (payload.event === 'routing_resolved') {
                onRoutingResolved?.(payload);
              } else if (payload.event === 'approval_required') {
                onApprovalRequired?.(payload);
              } else if (payload.event === 'cost_update') {
                onCostUpdate?.(payload);
              } else if (payload.event === 'error') {
                onError?.(payload.error || 'Execution failed');
              } else if (payload.event === 'done') {
                onDone?.(payload);
              }
            } catch {
              // ignore malformed JSON chunk
            }
          }
        }
      }
      onDone?.();
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        // Aborted by user cancellation
        return;
      }
      const msg = err instanceof Error ? err.message : String(err);
      onError?.(msg);
    }
  }

  async getExecution(executionId: string): Promise<any | null> {
    try {
      const res = await fetch(`${this.base}/v1/executions/${encodeURIComponent(executionId)}`, {
        headers: this.getHeaders(),
      });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
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
    const token =
      this.inMemoryToken ||
      (window as unknown as { __AGENT_ENGINE_IPC_TOKEN__?: string }).__AGENT_ENGINE_IPC_TOKEN__;
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
      headers['X-IPC-Token'] = token;
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

  async getSkillsDetailed(query?: string, tool?: string, tag?: string): Promise<SkillDetailed[]> {
    try {
      const params = new URLSearchParams();
      if (query) params.set('query', query);
      if (tool) params.set('tool', tool);
      if (tag) params.set('tag', tag);
      const url = `${this.base}/v1/skills${params.toString() ? `?${params.toString()}` : ''}`;
      const res = await fetch(url);
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data) ? data : [];
    } catch {
      return [];
    }
  }

  async getSkillContent(skillId: string): Promise<SkillDetailed | null> {
    try {
      const res = await fetch(`${this.base}/v1/skills/${encodeURIComponent(skillId)}`);
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  async createSkill(payload: {
    name: string;
    description: string;
    content: string;
    source_tool?: string;
    skill_id?: string;
    tags?: string[];
    author?: string;
    version?: string;
    format?: string;
  }): Promise<SkillDetailed> {
    const res = await fetch(`${this.base}/v1/skills/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Failed to create skill: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async updateSkillContent(skillId: string, content: string): Promise<SkillDetailed> {
    const res = await fetch(`${this.base}/v1/skills/${encodeURIComponent(skillId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Failed to update skill: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async validateSkillContent(content: string, format = 'markdown'): Promise<{
    valid: boolean;
    errors: string[];
    warnings: string[];
    parsed_metadata?: Record<string, any>;
  }> {
    try {
      const res = await fetch(`${this.base}/v1/skills/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, format }),
      });
      if (!res.ok) {
        return { valid: false, errors: [`Server returned HTTP ${res.status}`], warnings: [] };
      }
      return await res.json();
    } catch (e: any) {
      return { valid: false, errors: [e.message || 'Validation request failed'], warnings: [] };
    }
  }

  async searchSkills(query: string, tag?: string, limit = 20): Promise<Array<{ skill: SkillDetailed; score: number }>> {
    try {
      const params = new URLSearchParams({ q: query, limit: String(limit) });
      if (tag) params.set('tag', tag);
      const res = await fetch(`${this.base}/v1/skills/search?${params.toString()}`);
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async getSkillCollections(): Promise<SkillCollectionItem[]> {
    try {
      const res = await fetch(`${this.base}/v1/skills/collections`);
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async getSkillCollection(id: string): Promise<SkillCollectionItem | null> {
    try {
      const res = await fetch(`${this.base}/v1/skills/collections/${encodeURIComponent(id)}`);
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  async createSkillCollection(payload: {
    name: string;
    description?: string;
    tags?: string[];
    skill_ids?: string[];
    collection_id?: string;
  }): Promise<SkillCollectionItem> {
    const res = await fetch(`${this.base}/v1/skills/collections`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Failed to create collection: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async deleteSkillCollection(id: string): Promise<boolean> {
    try {
      const res = await fetch(`${this.base}/v1/skills/collections/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  async addSkillToCollection(collectionId: string, skillId: string): Promise<boolean> {
    try {
      const res = await fetch(
        `${this.base}/v1/skills/collections/${encodeURIComponent(collectionId)}/skills/${encodeURIComponent(skillId)}`,
        { method: 'POST' }
      );
      return res.ok;
    } catch {
      return false;
    }
  }

  async removeSkillFromCollection(collectionId: string, skillId: string): Promise<boolean> {
    try {
      const res = await fetch(
        `${this.base}/v1/skills/collections/${encodeURIComponent(collectionId)}/skills/${encodeURIComponent(skillId)}`,
        { method: 'DELETE' }
      );
      return res.ok;
    } catch {
      return false;
    }
  }

  async getSkillRegistryPackages(query?: string, category?: string, tag?: string): Promise<SkillRegistryPackage[]> {
    try {
      const params = new URLSearchParams();
      if (query) params.set('query', query);
      if (category) params.set('category', category);
      if (tag) params.set('tag', tag);
      const url = `${this.base}/v1/skills/registry${params.toString() ? `?${params.toString()}` : ''}`;
      const res = await fetch(url);
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async installRegistryPackage(packageId: string, force = false): Promise<SkillRegistryPackage> {
    const res = await fetch(`${this.base}/v1/skills/registry/install`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ package_id: packageId, force }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Installation failed: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async uninstallRegistryPackage(packageId: string): Promise<boolean> {
    const res = await fetch(`${this.base}/v1/skills/registry/uninstall`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ package_id: packageId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Uninstall failed: HTTP ${res.status}`);
    }
    return true;
  }

  async discoverRemoteSkills(endpointUrl: string, apiToken?: string): Promise<SkillDetailed[]> {
    const res = await fetch(`${this.base}/v1/skills/remote/discover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint_url: endpointUrl, api_token: apiToken }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Remote discovery failed: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async importRemoteSkill(
    endpointUrl: string,
    skillId: string,
    targetTool = 'agent-engine',
    apiToken?: string,
    force = false
  ): Promise<SkillDetailed> {
    const res = await fetch(`${this.base}/v1/skills/remote/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        endpoint_url: endpointUrl,
        skill_id: skillId,
        target_tool: targetTool,
        api_token: apiToken,
        force,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Remote import failed: HTTP ${res.status}`);
    }
    return await res.json();
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
    operation_id?: string;
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
        // F06: Fail closed with deny decision on HTTP error
        return {
          decision: 'deny',
          risk_score: 1.0,
          risk_level: 'critical',
          reason: `Safety evaluation service returned HTTP ${res.status} (fail-closed)`,
          suggestion: 'High-risk execution blocked by safety boundary',
        };
      }
      return await res.json();
    } catch (err: any) {
      // F06: Fail closed with deny decision on network/transport failure
      return {
        decision: 'deny',
        risk_score: 1.0,
        risk_level: 'critical',
        reason: `Safety evaluation service unreachable: ${err?.message || 'network error'} (fail-closed)`,
        suggestion: 'Execution halted: safety boundary offline',
      };
    }
  }

  async listPendingOperations(
    status?: string,
    sessionId?: string
  ): Promise<PendingOperation[]> {
    try {
      const params = new URLSearchParams();
      if (status) params.set('status', status);
      if (sessionId) params.set('session_id', sessionId);
      const qs = params.toString() ? `?${params.toString()}` : '';
      const res = await fetch(`${this.base}/v1/safety/operations${qs}`);
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async getPendingOperation(operationId: string): Promise<PendingOperation | null> {
    try {
      const res = await fetch(`${this.base}/v1/safety/operations/${operationId}`);
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  async registerPendingOperation(payload: {
    tool_name: string;
    tool_args: Record<string, any>;
    risk_level?: RiskLevel;
    risk_score?: number;
    session_id?: string;
    reason?: string;
    suggestion?: string;
    diff?: any;
    ttl_seconds?: number;
  }): Promise<PendingOperation> {
    const res = await fetch(`${this.base}/v1/safety/operations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(`Failed to register pending operation: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async approveOperation(
    operationId: string,
    actor?: string,
    modifiedArgs?: Record<string, any>
  ): Promise<PendingOperation> {
    const res = await fetch(`${this.base}/v1/safety/operations/${operationId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actor: actor || 'operator', modified_args: modifiedArgs }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Failed to approve operation: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async rejectOperation(
    operationId: string,
    actor?: string,
    reason?: string
  ): Promise<PendingOperation> {
    const res = await fetch(`${this.base}/v1/safety/operations/${operationId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actor: actor || 'operator', reason: reason || 'Rejected by operator' }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Failed to reject operation: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async batchOperations(
    operationIds: string[],
    action: 'approve' | 'reject',
    actor?: string,
    reason?: string
  ): Promise<PendingOperation[]> {
    const res = await fetch(`${this.base}/v1/safety/operations/batch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        operation_ids: operationIds,
        action,
        actor: actor || 'operator',
        reason,
      }),
    });
    if (!res.ok) {
      throw new Error(`Failed to execute batch operation: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async verifyExecution(
    approvalToken: string,
    toolName: string,
    toolArgs: Record<string, any>
  ): Promise<{
    authorized: boolean;
    operation_id: string;
    tool_name: string;
    actor: string;
    message: string;
  }> {
    const res = await fetch(`${this.base}/v1/safety/verify-execution`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        approval_token: approvalToken,
        tool_name: toolName,
        tool_args: toolArgs,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Execution verification failed: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async listSafetyPolicies(): Promise<SafetyPolicyRuleInfo[]> {
    try {
      const res = await fetch(`${this.base}/v1/safety/policies`);
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
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

  async getPolicyYaml(): Promise<PolicyYamlResponse> {
    try {
      const res = await fetch(`${this.base}/v1/safety/policies/yaml`);
      if (res.ok) return await res.json();
    } catch (err) {
      console.error('Failed to load policy YAML', err);
    }
    return { yaml_content: '', rules_count: 0 };
  }

  async updatePolicyYaml(yamlContent: string): Promise<{ success: boolean; message: string; rules_count?: number }> {
    const res = await fetch(`${this.base}/v1/safety/policies/yaml`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ yaml_content: yamlContent }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Failed to update policy YAML: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async dryRunPolicy(payload: DryRunRequest): Promise<DryRunResult> {
    const res = await fetch(`${this.base}/v1/safety/policies/dry-run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tool_name: payload.tool_name,
        tool_args: payload.tool_args || {},
        context: payload.context,
      }),
    });
    if (!res.ok) {
      throw new Error(`Dry run failed: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getSafetyAuditLogsPage(query: {
    limit?: number;
    offset?: number;
    decision?: string;
    riskLevel?: string;
    toolName?: string;
    sessionId?: string;
  } = {}): Promise<PaginatedAuditLogsResponse> {
    try {
      const params = new URLSearchParams();
      if (query.limit !== undefined) params.set('limit', String(query.limit));
      if (query.offset !== undefined) params.set('offset', String(query.offset));
      if (query.decision && query.decision !== 'all') params.set('decision', query.decision);
      if (query.riskLevel && query.riskLevel !== 'all') params.set('risk_level', query.riskLevel);
      if (query.toolName) params.set('tool_name', query.toolName);
      if (query.sessionId) params.set('session_id', query.sessionId);

      const res = await fetch(`${this.base}/v1/safety/audit-logs?${params.toString()}`);
      if (res.ok) return await res.json();
    } catch (err) {
      console.error('Failed to load paginated audit logs', err);
    }
    return { total: 0, limit: query.limit || 50, offset: query.offset || 0, items: [] };
  }

  async exportSafetyAuditLogs(
    format: 'csv' | 'json' = 'csv',
    filters: { decision?: string; riskLevel?: string; toolName?: string; limit?: number } = {}
  ): Promise<string | AuditLogEntry[]> {
    const params = new URLSearchParams({ format });
    if (filters.decision && filters.decision !== 'all') params.set('decision', filters.decision);
    if (filters.riskLevel && filters.riskLevel !== 'all') params.set('risk_level', filters.riskLevel);
    if (filters.toolName) params.set('tool_name', filters.toolName);
    if (filters.limit) params.set('limit', String(filters.limit));

    const res = await fetch(`${this.base}/v1/safety/audit-logs/export?${params.toString()}`);
    if (!res.ok) {
      throw new Error(`Export failed: HTTP ${res.status}`);
    }
    if (format === 'csv') {
      return await res.text();
    }
    return await res.json();
  }

  async getCostMetrics(
    groupBy: string = 'day',
    project?: string,
    agentName?: string,
    modelName?: string
  ): Promise<CostMetrics> {
    try {
      const params = new URLSearchParams({ group_by: groupBy });
      if (project) params.set('project', project);
      if (agentName) params.set('agent_name', agentName);
      if (modelName) params.set('model_name', modelName);
      const res = await fetch(`${this.base}/v1/telemetry/cost?${params.toString()}`);
      if (res.ok) return await res.json();
    } catch {
      // fallback if offline
    }
    return {
      total_cost_usd: 0.0,
      total_prompt_tokens: 0,
      total_completion_tokens: 0,
      total_tokens: 0,
      month_spend_usd: 0.0,
      day_spend_usd: 0.0,
      cache_hit_rate: 0.42,
      tier_split: {
        deterministic_cache_local_pct: 90.0,
        mid_tier_pct: 9.0,
        frontier_pct: 1.0,
        code_cache_calls: 0,
        mid_tier_calls: 0,
        frontier_calls: 0,
      },
      cost_per_task: [],
      breakdown: [],
      alerts: [],
    };
  }

  async getBudgetConfig(project: string = 'default'): Promise<BudgetConfig> {
    try {
      const params = new URLSearchParams({ project });
      const res = await fetch(`${this.base}/v1/telemetry/budget?${params.toString()}`);
      if (res.ok) return await res.json();
    } catch {
      // fallback
    }
    return {
      monthly_budget_usd: 100.0,
      daily_budget_usd: 10.0,
      warning_threshold_pct: 80.0,
      critical_threshold_pct: 100.0,
      project,
      alerts: [],
    };
  }

  async setBudgetConfig(payload: {
    monthly_budget_usd: number;
    daily_budget_usd: number;
    warning_threshold_pct?: number;
    critical_threshold_pct?: number;
    project?: string;
  }): Promise<BudgetConfig> {
    const res = await fetch(`${this.base}/v1/telemetry/budget`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        monthly_budget_usd: payload.monthly_budget_usd,
        daily_budget_usd: payload.daily_budget_usd,
        warning_threshold_pct: payload.warning_threshold_pct ?? 80.0,
        critical_threshold_pct: payload.critical_threshold_pct ?? 100.0,
        project: payload.project || 'default',
      }),
    });
    if (!res.ok) {
      throw new Error(`Failed to update budget configuration: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async recordCostMetric(payload: {
    agent_name: string;
    model_name: string;
    prompt_tokens: number;
    completion_tokens: number;
    cost_usd?: number;
    task_id?: string;
    success?: boolean;
    project?: string;
  }): Promise<{ id: number; success: boolean }> {
    const res = await fetch(`${this.base}/v1/telemetry/cost/record`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(`Failed to record spend: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async listDistillationCandidates(): Promise<DistillationCandidate[]> {
    try {
      const res = await fetch(`${this.base}/v1/telemetry/distillation-candidates`);
      if (res.ok) return await res.json();
    } catch {
      // fallback
    }
    return [];
  }

  async triggerDistillation(
    candidateId: string,
    targetStudentModel?: string
  ): Promise<{ success: boolean; message: string }> {
    const res = await fetch(`${this.base}/v1/telemetry/distill`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        candidate_id: candidateId,
        target_student_model: targetStudentModel,
      }),
    });
    if (!res.ok) {
      throw new Error(`Failed to trigger distillation: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getTelemetry(): Promise<any> {
    try {
      const res = await fetch(`${this.base}/v1/telemetry`);
      if (res.ok) {
        return await res.json();
      }
    } catch {
      // fallback
    }
    return {
      cpu_usage_percent: 24.5,
      ram_used_percent: 65.2,
      ram_total_gb: 14.6,
      ram_available_gb: 5.1,
      primary_provider: 'local',
      active_model: 'qwen2.5-coder',
      ollama_active: true,
      llamacpp_active: false,
      indexed_memory_documents: 0,
      gpu_detected: true,
      gpu_model: 'AMD Radeon Vega Series',
      vram_used_percent: 85.0,
      vram_warning: false,
      tokens_per_second: 0.0,
    };
  }

  async getHardwareTelemetry(): Promise<HardwareTelemetry> {
    try {
      const res = await fetch(`${this.base}/v1/telemetry/hardware`);
      if (res.ok) {
        return await res.json();
      }
    } catch {
      // offline dev fallback
    }
    return {
      cpu_usage_percent: 24.5,
      cpu_cores_logical: 8,
      cpu_cores_physical: 4,
      ram_used_percent: 65.2,
      ram_used_gb: 9.5,
      ram_total_gb: 14.6,
      ram_available_gb: 5.1,
      gpu_detected: true,
      gpu_model: 'AMD Radeon Vega Series / Raven Ridge (APU)',
      gpu_vendor: 'amd',
      vram_used_percent: 85.0,
      vram_used_gb: 0.85,
      vram_total_gb: 1.0,
      vram_free_gb: 0.15,
      vram_warning: false,
      vram_warning_threshold: 95.0,
      tokens_per_second: 0.0,
      recent_inference_runtime: undefined,
      recent_inference_model: undefined,
      ollama_active: false,
      llamacpp_active: false,
      local_runtime_active: false,
      timestamp: new Date().toISOString(),
    };
  }

  async recordInferenceSpeed(payload: SpeedRecordPayload): Promise<{
    status: string;
    tokens_per_second: number;
    tokens: number;
    elapsed_seconds: number;
  }> {
    const res = await fetch(`${this.base}/v1/telemetry/record-speed`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      throw new Error(`Failed to record inference speed: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getAppSettings(): Promise<AppSettings> {
    try {
      const res = await fetch(`${this.base}/v1/settings/config`, {
        headers: this.getHeaders(),
      });
      if (res.ok) {
        return await res.json();
      }
    } catch (err) {
      console.error('Failed to get app settings:', err);
    }
    return {
      models: {
        default_tier: 'instant',
        fallback_tier: 'swarm',
        temperature: 0.7,
        max_context_tokens: 4000,
        hard_ceiling_tokens: 32000,
        bypass_cache: false,
      },
      local_runtime: {
        ollama_base_url: 'http://localhost:11434',
        llamacpp_base_url: 'http://localhost:8080',
        gpu_layers: 33,
        cpu_threads: 4,
        context_length: 8192,
        auto_detect_gpu: true,
      },
      adapters: {
        mcp_enabled: true,
        claude_code_adapter: true,
        codex_adapter: false,
        openclaw_adapter: false,
        goose_adapter: false,
        cursor_adapter: false,
      },
      channels: {
        slack_enabled: false,
        slack_webhook_url: null,
        teams_enabled: false,
        teams_app_id: null,
        teams_webhook_url: null,
        discord_enabled: false,
        discord_webhook_url: null,
        mattermost_enabled: false,
        mattermost_url: null,
        telegram_enabled: false,
        telegram_bot_token: null,
        whatsapp_enabled: false,
      },
      storage: {
        database_backend: 'sqlite',
        sqlite_path: 'data/agent_engine.db',
        postgres_url: null,
        chroma_path: 'data/chroma',
        retention_days: 90,
      },
      security: {
        zero_trust_eval: 'strict',
        approval_timeout_seconds: 60,
        ipc_token_enabled: true,
        sandbox_mode: 'standard',
        keychain_backend: 'auto',
      },
      appearance: {
        theme: 'dark',
        font_size: 'base',
        ui_density: 'comfortable',
        code_font_family: 'monospace',
      },
      version: '1.0.0',
      updated_at: new Date().toISOString(),
    };
  }

  async saveAppSettings(settings: Partial<AppSettings>): Promise<AppSettings> {
    const res = await fetch(`${this.base}/v1/settings/config`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify(settings),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(err.detail || `Failed to save app settings: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async exportDiagnostics(format: 'zip' | 'json' = 'zip'): Promise<Blob | DiagnosticsBundle> {
    const res = await fetch(`${this.base}/v1/diagnostics/export?format=${format}`, {
      headers: this.getHeaders(),
    });
    if (!res.ok) {
      throw new Error(`Failed to export diagnostics: HTTP ${res.status}`);
    }
    if (format === 'zip') {
      return await res.blob();
    }
    return await res.json();
  }

  async getAdapters(includeHealth: boolean = false): Promise<AdapterMetadata[]> {
    try {
      const res = await fetch(`${this.base}/v1/adapters?include_health=${includeHealth}`, {
        headers: this.getHeaders(),
      });
      if (res.ok) {
        return await res.json();
      }
    } catch (err) {
      console.error('Failed to get adapters:', err);
    }
    return [];
  }

  async getAdapter(id: string): Promise<AdapterMetadata | null> {
    try {
      const res = await fetch(`${this.base}/v1/adapters/${id}`, {
        headers: this.getHeaders(),
      });
      if (res.ok) {
        return await res.json();
      }
    } catch (err) {
      console.error(`Failed to get adapter ${id}:`, err);
    }
    return null;
  }

  async executeAdapter(id: string, req: AdapterExecutionRequest): Promise<AdapterExecutionResponse | null> {
    try {
      const res = await fetch(`${this.base}/v1/adapters/${id}/execute`, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify(req),
      });
      if (res.ok) {
        return await res.json();
      }
    } catch (err) {
      console.error(`Failed to execute adapter ${id}:`, err);
    }
    return null;
  }

  async testAdapter(id: string): Promise<AdapterHealth> {
    try {
      const res = await fetch(`${this.base}/v1/adapters/${id}/test`, {
        method: 'POST',
        headers: this.getHeaders(),
      });
      if (res.ok) {
        return await res.json();
      }
    } catch (err) {
      console.error(`Failed to test adapter ${id}:`, err);
    }
    return {
      status: 'unavailable',
      message: 'Network or client error probing adapter',
      latency_ms: 0,
    };
  }

  async sendSlackEvent(payload: Record<string, any>): Promise<any> {
    try {
      const res = await fetch(`${this.base}/v1/channels/slack/events`, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify(payload),
      });
      if (res.ok) return await res.json();
    } catch (err) {
      console.error('Failed to send Slack event:', err);
    }
    return null;
  }

  async sendTeamsActivity(payload: Record<string, any>): Promise<any> {
    try {
      const res = await fetch(`${this.base}/v1/channels/teams/activities`, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify(payload),
      });
      if (res.ok) return await res.json();
    } catch (err) {
      console.error('Failed to send Teams activity:', err);
    }
    return null;
  }

  async sendDiscordInteraction(payload: Record<string, any>): Promise<any> {
    try {
      const res = await fetch(`${this.base}/v1/channels/discord/interactions`, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify(payload),
      });
      if (res.ok) return await res.json();
    } catch (err) {
      console.error('Failed to send Discord interaction:', err);
    }
    return null;
  }

  async sendMattermostHook(payload: Record<string, any>): Promise<any> {
    try {
      const res = await fetch(`${this.base}/v1/channels/mattermost/hooks`, {
        method: 'POST',
        headers: this.getHeaders(),
        body: JSON.stringify(payload),
      });
      if (res.ok) return await res.json();
    } catch (err) {
      console.error('Failed to send Mattermost hook:', err);
    }
    return null;
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

  // Collaborative Rooms (Phase 5B - Milestone M4)
  async createRoom(payload: CreateRoomPayload): Promise<CollaborativeRoom> {
    const res = await fetch(`${this.base}/v1/rooms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to create room: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async listRooms(projectId?: string, status?: string): Promise<CollaborativeRoom[]> {
    const params = new URLSearchParams();
    if (projectId) params.append('project_id', projectId);
    if (status) params.append('status', status);
    const query = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`${this.base}/v1/rooms${query}`);
    if (!res.ok) {
      throw new Error(`Failed to list rooms: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getRoom(roomId: string): Promise<CollaborativeRoom> {
    const res = await fetch(`${this.base}/v1/rooms/${roomId}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to get room: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async updateRoom(roomId: string, updates: Partial<CreateRoomPayload & { status: string }>): Promise<CollaborativeRoom> {
    const res = await fetch(`${this.base}/v1/rooms/${roomId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to update room: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async deleteRoom(roomId: string): Promise<boolean> {
    const res = await fetch(`${this.base}/v1/rooms/${roomId}`, {
      method: 'DELETE',
    });
    return res.ok;
  }

  async getRoomContext(roomId: string, prompt: string = '', projectInstructions: string = ''): Promise<Record<string, any>> {
    const params = new URLSearchParams();
    if (prompt) params.append('prompt', prompt);
    if (projectInstructions) params.append('project_instructions', projectInstructions);
    const res = await fetch(`${this.base}/v1/rooms/${roomId}/context?${params.toString()}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to get room context: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async addRoomParticipant(roomId: string, payload: AddRoomParticipantPayload): Promise<RoomParticipant> {
    const res = await fetch(`${this.base}/v1/rooms/${roomId}/participants`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to add room participant: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async listRoomParticipants(roomId: string): Promise<RoomParticipant[]> {
    const res = await fetch(`${this.base}/v1/rooms/${roomId}/participants`);
    if (!res.ok) {
      throw new Error(`Failed to list room participants: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async removeRoomParticipant(roomId: string, participantId: string, requestedBy?: string): Promise<boolean> {
    const query = requestedBy ? `?requested_by=${encodeURIComponent(requestedBy)}` : '';
    const res = await fetch(`${this.base}/v1/rooms/${roomId}/participants/${participantId}${query}`, {
      method: 'DELETE',
    });
    return res.ok;
  }

  async createRoomTask(roomId: string, payload: CreateRoomTaskPayload): Promise<RoomTask> {
    const res = await fetch(`${this.base}/v1/rooms/${roomId}/tasks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to create room task: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async listRoomTasks(roomId: string, status?: string, assignedTo?: string): Promise<RoomTask[]> {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (assignedTo) params.append('assigned_to', assignedTo);
    const query = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`${this.base}/v1/rooms/${roomId}/tasks${query}`);
    if (!res.ok) {
      throw new Error(`Failed to list room tasks: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getRoomTask(roomId: string, taskId: string): Promise<RoomTask> {
    const res = await fetch(`${this.base}/v1/rooms/${roomId}/tasks/${taskId}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to get room task: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async claimRoomTask(roomId: string, taskId: string, participantId: string, adapterType?: string): Promise<RoomTask> {
    const res = await fetch(`${this.base}/v1/rooms/${roomId}/tasks/${taskId}/claim`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ participant_id: participantId, adapter_type: adapterType }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to claim room task: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async updateRoomTask(
    roomId: string,
    taskId: string,
    payload: { status?: string; result?: Record<string, any>; updated_by?: string }
  ): Promise<RoomTask> {
    const res = await fetch(`${this.base}/v1/rooms/${roomId}/tasks/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to update room task: HTTP ${res.status}`);
    }
    return await res.json();
  }

  // Swarm Multi-Agent Execution (Phase 7 - Task 7.4)
  async listSwarmCases(): Promise<SwarmCase[]> {
    try {
      const res = await fetch(`${this.base}/v1/swarm/cases`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async estimateSwarmCost(params: {
    case_id?: string;
    agents?: any[];
    model_tier?: string;
  }): Promise<{ estimated_cost_usd: number; agent_count: number; model_tier: string }> {
    try {
      const res = await fetch(`${this.base}/v1/swarm/estimate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      if (!res.ok) return { estimated_cost_usd: 0.04, agent_count: 4, model_tier: params.model_tier || 'instant' };
      return await res.json();
    } catch {
      return { estimated_cost_usd: 0.04, agent_count: 4, model_tier: params.model_tier || 'instant' };
    }
  }

  async runSwarm(payload: {
    prompt: string;
    case_id?: string;
    agents?: any[];
    model_tier?: string;
  }): Promise<SwarmRunResult> {
    const res = await fetch(`${this.base}/v1/swarm/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to run swarm: HTTP ${res.status}`);
    }
    return await res.json();
  }

  // Workflow Engine (Phase 7 - Milestone M5)
  async listWorkflows(tag?: string): Promise<WorkflowDefinition[]> {
    try {
      const url = tag ? `${this.base}/v1/workflows?tag=${encodeURIComponent(tag)}` : `${this.base}/v1/workflows`;
      const res = await fetch(url, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async getWorkflow(id: string): Promise<WorkflowDefinition> {
    const res = await fetch(`${this.base}/v1/workflows/${encodeURIComponent(id)}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch workflow: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async saveWorkflow(wf: WorkflowDefinition): Promise<WorkflowDefinition> {
    const res = await fetch(`${this.base}/v1/workflows`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(wf),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to save workflow: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async updateWorkflow(id: string, wf: WorkflowDefinition): Promise<WorkflowDefinition> {
    const res = await fetch(`${this.base}/v1/workflows/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(wf),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to update workflow: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async deleteWorkflow(id: string): Promise<{ deleted: boolean }> {
    const res = await fetch(`${this.base}/v1/workflows/${encodeURIComponent(id)}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to delete workflow: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async validateWorkflow(payload: { definition_yaml?: string; definition_json?: any }): Promise<WorkflowValidationResult> {
    const res = await fetch(`${this.base}/v1/workflows/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Validation failed: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async dryRunWorkflow(id: string, inputs: Record<string, any> = {}): Promise<WorkflowRun> {
    const res = await fetch(`${this.base}/v1/workflows/${encodeURIComponent(id)}/dry-run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Dry run failed: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async runWorkflow(id: string, inputs: Record<string, any> = {}): Promise<WorkflowRun> {
    const res = await fetch(`${this.base}/v1/workflows/${encodeURIComponent(id)}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs, dry_run: false }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Execution failed: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async listWorkflowRuns(id: string): Promise<WorkflowRun[]> {
    try {
      const res = await fetch(`${this.base}/v1/workflows/${encodeURIComponent(id)}/runs`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async getWorkflowRun(id: string, runId: string): Promise<WorkflowRun> {
    const res = await fetch(`${this.base}/v1/workflows/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}`, {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch run: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async listPendingGates(): Promise<PendingGateInfo[]> {
    try {
      const res = await fetch(`${this.base}/v1/workflows/gates/pending`, {
        method: 'GET',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) return [];
      return await res.json();
    } catch {
      return [];
    }
  }

  async approveWorkflowGate(id: string, runId: string, reviewer: string = 'operator', inputOverrides?: Record<string, any>): Promise<WorkflowRun> {
    const res = await fetch(`${this.base}/v1/workflows/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reviewer, input_overrides: inputOverrides }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to approve gate: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async rejectWorkflowGate(id: string, runId: string, reviewer: string = 'operator', reason?: string): Promise<WorkflowRun> {
    const res = await fetch(`${this.base}/v1/workflows/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reviewer, reason }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to reject gate: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async redirectWorkflowGate(id: string, runId: string, targetNodeId: string, reviewer: string = 'operator', inputOverrides?: Record<string, any>): Promise<WorkflowRun> {
    const res = await fetch(`${this.base}/v1/workflows/${encodeURIComponent(id)}/runs/${encodeURIComponent(runId)}/redirect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_node_id: targetNodeId, reviewer, input_overrides: inputOverrides }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to redirect gate: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getRecommendedLocalModels(
    params?: Partial<TaskRequirements>
  ): Promise<LocalRecommendationResponse> {
    const searchParams = new URLSearchParams();
    if (params) {
      if (params.task_type) searchParams.set('task_type', params.task_type);
      if (params.coding !== undefined) searchParams.set('coding', String(params.coding));
      if (params.reasoning !== undefined) searchParams.set('reasoning', String(params.reasoning));
      if (params.vision !== undefined) searchParams.set('vision', String(params.vision));
      if (params.tools !== undefined) searchParams.set('tools', String(params.tools));
      if (params.structured_output !== undefined) searchParams.set('structured_output', String(params.structured_output));
      if (params.min_context_tokens !== undefined) searchParams.set('min_context_tokens', String(params.min_context_tokens));
      if (params.require_local_only !== undefined) searchParams.set('require_local_only', String(params.require_local_only));
      if (params.required_accelerator) searchParams.set('required_accelerator', params.required_accelerator);
    }
    const query = searchParams.toString();
    const url = `${this.base}/v1/models/recommendations${query ? `?${query}` : ''}`;
    const res = await fetch(url, {
      method: 'GET',
      headers: this.getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch model recommendations: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getLocalModelCatalog(): Promise<CatalogModelEntry[]> {
    const res = await fetch(`${this.base}/v1/models/catalog`, {
      method: 'GET',
      headers: this.getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch local model catalog: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async startModelDownload(
    modelId: string,
    providerId: string = 'llamacpp'
  ): Promise<DownloadStatus> {
    const res = await fetch(`${this.base}/v1/models/downloads`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ model_id: modelId, provider_id: providerId }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to start model download: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getModelDownloads(): Promise<DownloadStatus[]> {
    const res = await fetch(`${this.base}/v1/models/downloads`, {
      method: 'GET',
      headers: this.getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch model downloads: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getModelDownloadStatus(artifactId: string): Promise<DownloadStatus> {
    const res = await fetch(`${this.base}/v1/models/downloads/${encodeURIComponent(artifactId)}`, {
      method: 'GET',
      headers: this.getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch download status: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async cancelModelDownload(
    artifactId: string
  ): Promise<{ artifact_id: string; cancelled: boolean }> {
    const res = await fetch(
      `${this.base}/v1/models/downloads/${encodeURIComponent(artifactId)}/cancel`,
      {
        method: 'POST',
        headers: this.getHeaders(),
      }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to cancel model download: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getInstalledModels(): Promise<DownloadStatus[]> {
    const res = await fetch(`${this.base}/v1/models/installed`, {
      method: 'GET',
      headers: this.getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch installed models: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async getModelEconomics(filters?: {
    taskFamily?: string;
    providerId?: string;
    modelId?: string;
    evidenceSource?: string;
    evaluatorVersion?: string;
    effectivePrivacyClass?: string;
  }): Promise<ModelEconomicsSummary[]> {
    const params = new URLSearchParams();
    if (filters?.taskFamily) params.append('task_family', filters.taskFamily);
    if (filters?.providerId) params.append('provider_id', filters.providerId);
    if (filters?.modelId) params.append('model_id', filters.modelId);
    if (filters?.evidenceSource) params.append('evidence_source', filters.evidenceSource);
    if (filters?.evaluatorVersion) params.append('evaluator_version', filters.evaluatorVersion);
    if (filters?.effectivePrivacyClass) params.append('effective_privacy_class', filters.effectivePrivacyClass);
    const qs = params.toString();
    const url = `${this.base}/v1/models/economics${qs ? `?${qs}` : ''}`;
    const res = await fetch(url, {
      method: 'GET',
      headers: this.getHeaders(),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Failed to fetch model economics: HTTP ${res.status}`);
    }
    return await res.json();
  }

  async verifyProvider(
    providerId: string,
    modelId?: string,
    timeout?: number
  ): Promise<ProviderConnectionVerification> {
    const res = await fetch(`${this.base}/v1/providers/${encodeURIComponent(providerId)}/verify`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({ model_id: modelId, timeout: timeout ?? 5.0 }),
    });
    if (!res.ok) {
      return {
        provider_id: providerId,
        status: 'PROVIDER_ERROR',
        last_verified_at: Date.now() / 1000,
        latency_ms: 0,
        failure_class: 'HTTP_ERROR',
        sanitized_error: `HTTP ${res.status}: ${res.statusText}`,
        verification_version: 'v1',
        verification_method_version: 'v1_canary',
        probe_type: 'real_completion_canary',
        is_fresh: false,
        display_state: 'Verification failed',
        details: {},
      };
    }
    return await res.json();
  }

  async getProviderVerification(providerId: string): Promise<ProviderConnectionVerification> {
    const res = await fetch(`${this.base}/v1/providers/${encodeURIComponent(providerId)}/verification`, {
      headers: this.getHeaders(),
    });
    if (!res.ok) {
      return {
        provider_id: providerId,
        status: 'NOT_CONFIGURED',
        last_verified_at: 0,
        latency_ms: 0,
        failure_class: 'NOT_FOUND',
        sanitized_error: `HTTP ${res.status}`,
        verification_version: 'v1',
        verification_method_version: 'v1_canary',
        probe_type: 'real_completion_canary',
        is_fresh: false,
        display_state: 'Not configured',
        details: {},
      };
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


