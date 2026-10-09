import React, { useState, useEffect } from 'react';
import {
  Code2,
  Cpu,
  Server,
  RefreshCw,
  Copy,
  Activity,
  Wrench,
  Layers,
} from 'lucide-react';
import { sidecarClient } from '../api/client';
import { HardwareTelemetry } from '../types';

export type DeveloperTab = 'traces' | 'telemetry' | 'mcp' | 'dspy' | 'providers';

export const Developer: React.FC = () => {
  const [activeTab, setActiveTab] = useState<DeveloperTab>('traces');
  const [telemetry, setTelemetry] = useState<HardwareTelemetry | null>(null);
  const [pipelines, setPipelines] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [selectedTrace, setSelectedTrace] = useState<any | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const loadData = async () => {
    setIsLoading(true);
    try {
      const [telem, pipes, sess] = await Promise.all([
        sidecarClient.getHardwareTelemetry().catch(() => null),
        sidecarClient.getPipelines().catch(() => []),
        sidecarClient.getSessions(20).catch(() => []),
      ]);
      setTelemetry(telem);
      setPipelines(pipes);
      setSessions(sess);
      if (sess.length > 0 && !selectedTrace) {
        setSelectedTrace(sess[0]);
      }
    } catch (err) {
      console.error('Failed to load developer data', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden" data-testid="developer-screen">
      {/* Console Header */}
      <div className="h-12 border-b border-border-subtle bg-bg-elevated px-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Code2 className="w-4 h-4 text-accent" />
          <h1 className="text-sm font-semibold tracking-tight text-text-primary">Developer Console</h1>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-text-tertiary uppercase">
            Kernel Debug & Telemetry
          </span>
        </div>
        <button
          type="button"
          onClick={loadData}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Tab Switcher */}
      <div className="px-4 py-2 border-b border-border-subtle bg-bg-elevated/50 flex items-center gap-1 text-xs">
        {[
          { id: 'traces', label: 'Traces & Executions', icon: Activity },
          { id: 'telemetry', label: 'Hardware Telemetry', icon: Cpu },
          { id: 'mcp', label: 'MCP & Tool Protocol', icon: Wrench },
          { id: 'dspy', label: 'DSPy Pipeline', icon: Layers },
          { id: 'providers', label: 'Provider Registry', icon: Server },
        ].map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id as DeveloperTab)}
              className={`flex items-center gap-1.5 px-3 py-1 rounded transition-colors font-medium text-xs ${
                activeTab === tab.id
                  ? 'bg-bg-elevated text-text-primary shadow-xs border border-border-subtle'
                  : 'text-text-tertiary hover:text-text-secondary'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Main Tab Content */}
      <div className="flex-1 overflow-hidden p-4">
        {activeTab === 'traces' && (
          <div className="h-full flex gap-4 overflow-hidden">
            {/* Left: Execution Traces List */}
            <div className="w-80 border border-border-subtle rounded-lg bg-bg-elevated/30 overflow-y-auto divide-y divide-border-subtle">
              <div className="p-2.5 bg-bg-elevated text-[10px] font-semibold uppercase tracking-wider text-text-tertiary sticky top-0">
                Recent Sessions & Traces ({sessions.length})
              </div>
              {sessions.length === 0 ? (
                <div className="p-8 text-center text-xs text-text-tertiary">
                  No execution traces logged yet.
                </div>
              ) : (
                sessions.map((s) => (
                  <div
                    key={s.session_id}
                    onClick={() => setSelectedTrace(s)}
                    className={`p-3 text-xs cursor-pointer transition-colors ${
                      selectedTrace?.session_id === s.session_id
                        ? 'bg-accent/10 border-l-2 border-accent'
                        : 'hover:bg-bg-hover'
                    }`}
                  >
                    <div className="font-medium text-text-primary truncate mb-1">
                      {s.title || `Session ${s.session_id}`}
                    </div>
                    <div className="flex items-center justify-between text-[10px] font-mono text-text-tertiary">
                      <span>ID: {s.session_id.slice(0, 8)}...</span>
                      <span>{s.status || 'closed'}</span>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Right: Trace Event Inspector */}
            <div className="flex-1 border border-border-subtle rounded-lg bg-bg-elevated/20 p-4 flex flex-col overflow-hidden">
              <div className="text-xs font-semibold text-text-primary mb-2 flex items-center justify-between">
                <span>Execution Trace Raw JSON Payload</span>
                {selectedTrace && (
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(JSON.stringify(selectedTrace, null, 2))}
                    className="flex items-center gap-1 text-[11px] text-text-secondary hover:text-text-primary"
                  >
                    <Copy className="w-3 h-3" />
                    <span>Copy JSON</span>
                  </button>
                )}
              </div>
              <div className="flex-1 p-3 bg-bg-base border border-border-subtle rounded-md overflow-auto font-mono text-xs text-text-secondary leading-relaxed">
                {selectedTrace ? (
                  <pre>{JSON.stringify(selectedTrace, null, 2)}</pre>
                ) : (
                  <div className="text-text-tertiary text-center py-16">
                    Select a trace on the left to inspect raw execution metadata.
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'telemetry' && (
          <div className="h-full overflow-y-auto space-y-4 max-w-4xl">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="p-3.5 rounded-lg bg-bg-elevated border border-border-subtle space-y-1">
                <span className="text-[10px] font-mono text-text-tertiary uppercase">CPU Core Load</span>
                <div className="text-xl font-bold font-mono text-text-primary">
                  {telemetry?.cpu_usage_percent ?? 0}%
                </div>
                <div className="text-[11px] text-text-tertiary">
                  Cores: {telemetry?.cpu_cores_logical ?? 8} logical cores
                </div>
              </div>

              <div className="p-3.5 rounded-lg bg-bg-elevated border border-border-subtle space-y-1">
                <span className="text-[10px] font-mono text-text-tertiary uppercase">Host System RAM</span>
                <div className="text-xl font-bold font-mono text-text-primary">
                  {telemetry?.ram_used_gb?.toFixed(1) ?? '4.2'} / {telemetry?.ram_total_gb?.toFixed(1) ?? '16.0'} GB
                </div>
                <div className="text-[11px] text-text-tertiary">
                  {telemetry?.ram_used_percent ?? 28}% utilized
                </div>
              </div>

              <div className="p-3.5 rounded-lg bg-bg-elevated border border-border-subtle space-y-1">
                <span className="text-[10px] font-mono text-text-tertiary uppercase">VRAM / GPU Accelerator</span>
                <div className="text-xl font-bold font-mono text-text-primary">
                  {telemetry?.vram_used_gb ? `${telemetry.vram_used_gb.toFixed(1)} GB` : 'Unified / Host'}
                </div>
                <div className="text-[11px] text-text-tertiary">
                  GPU: {telemetry?.gpu_model || 'Host CPU / Vulkan fallback'}
                </div>
              </div>
            </div>

            {/* Inference Tok/s Observed */}
            <div className="p-4 rounded-lg bg-bg-elevated border border-border-subtle space-y-2">
              <div className="text-xs font-semibold text-text-primary">Inference Execution Benchmark</div>
              <div className="flex items-center gap-4 text-xs font-mono">
                <div>
                  <span className="text-text-tertiary block">Observed Tok/s</span>
                  <span className="text-base font-bold text-accent">
                    {telemetry?.tokens_per_second?.toFixed(1) ?? '0.0'} tok/s
                  </span>
                </div>
                <div>
                  <span className="text-text-tertiary block">Local Runtime State</span>
                  <span className={telemetry?.local_runtime_active ? 'text-emerald-400 font-semibold' : 'text-text-secondary'}>
                    {telemetry?.local_runtime_active ? 'Online · Inference Ready' : 'Standby'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'mcp' && (
          <div className="h-full overflow-y-auto space-y-4 max-w-4xl">
            <div className="p-4 rounded-lg bg-bg-elevated border border-border-subtle space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-xs font-semibold text-text-primary">Active Model Context Protocol (MCP) Servers</div>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-emerald-400">
                  Transport: stdio / JSON-RPC 2.0
                </span>
              </div>
              <div className="space-y-2 text-xs">
                {[
                  { name: 'sqlite-audit-ledger', transport: 'in-process stdio', status: 'Connected', tools: 'query_audit, log_event' },
                  { name: 'fs-workspace-sandbox', transport: 'local AST sandbox', status: 'Connected', tools: 'read_file, safe_edit, list_dir' },
                  { name: 'python-code-runner', transport: 'isolated process', status: 'Standby', tools: 'exec_code_ast' },
                ].map((s, idx) => (
                  <div key={idx} className="p-3 rounded bg-bg-base border border-border-subtle flex items-center justify-between">
                    <div>
                      <div className="font-semibold text-text-primary font-mono">{s.name}</div>
                      <div className="text-[11px] text-text-tertiary mt-0.5">Tools: {s.tools}</div>
                    </div>
                    <div className="text-right font-mono text-[11px]">
                      <span className="text-emerald-400">{s.status}</span>
                      <div className="text-text-tertiary">{s.transport}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'dspy' && (
          <div className="h-full overflow-y-auto space-y-4 max-w-4xl">
            <div className="p-4 rounded-lg bg-bg-elevated border border-border-subtle space-y-3">
              <div className="text-xs font-semibold text-text-primary">DSPy Compiled Pipelines & Optimizers</div>
              <div className="space-y-2 text-xs">
                {pipelines.length === 0 ? (
                  <div className="py-8 text-center text-text-tertiary">
                    No custom DSPy compilation traces registered in current session.
                  </div>
                ) : (
                  pipelines.map((p, idx) => (
                    <div key={idx} className="p-3 rounded bg-bg-base border border-border-subtle flex items-center justify-between font-mono">
                      <div>
                        <span className="font-semibold text-text-primary">{p.name || `Pipeline #${idx + 1}`}</span>
                        <div className="text-[11px] text-text-tertiary">{p.description || 'Deterministic prompt optimizer'}</div>
                      </div>
                      <span className="text-text-secondary text-[11px]">{p.version || 'v1.0'}</span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'providers' && (
          <div className="h-full overflow-y-auto space-y-4 max-w-4xl">
            <div className="p-4 rounded-lg bg-bg-elevated border border-border-subtle space-y-3">
              <div className="text-xs font-semibold text-text-primary">Provider Registry & Endpoints</div>
              <div className="space-y-2 text-xs">
                {[
                  { id: 'ollama', name: 'Ollama Local Daemon', endpoint: 'http://127.0.0.1:11434', protocol: 'OpenAI REST compatible' },
                  { id: 'llama.cpp', name: 'llama-server Local', endpoint: 'http://127.0.0.1:8080', protocol: 'Native llama.cpp' },
                  { id: 'openai', name: 'OpenAI Cloud API', endpoint: 'https://api.openai.com/v1', protocol: 'Bearer Key' },
                  { id: 'anthropic', name: 'Anthropic Messages API', endpoint: 'https://api.anthropic.com/v1', protocol: 'x-api-key' },
                  { id: 'gemini', name: 'Google Gemini API', endpoint: 'https://generativelanguage.googleapis.com', protocol: 'API Key' },
                ].map((prov) => (
                  <div key={prov.id} className="p-3 rounded bg-bg-base border border-border-subtle flex items-center justify-between font-mono">
                    <div>
                      <div className="font-semibold text-text-primary">{prov.name}</div>
                      <div className="text-[11px] text-text-tertiary">{prov.endpoint}</div>
                    </div>
                    <span className="text-[11px] text-text-secondary">{prov.protocol}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
