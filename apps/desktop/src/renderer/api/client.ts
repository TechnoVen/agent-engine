import {
  CredentialDetail,
  CredentialItem,
  CredentialTestResult,
  SetCredentialPayload,
  SidecarHealth,
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
}

export const sidecarClient = new SidecarClient();

