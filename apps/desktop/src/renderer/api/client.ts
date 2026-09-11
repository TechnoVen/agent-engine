import { SidecarHealth } from '../types';

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
}

export const sidecarClient = new SidecarClient();
