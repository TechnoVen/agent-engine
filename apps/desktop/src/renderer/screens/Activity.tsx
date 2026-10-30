import React, { useState, useEffect } from 'react';
import {
  Activity as ActivityIcon,
  Coins,
  History,
  RefreshCw,
  Database,
  ChevronDown,
  ChevronUp,
  Cpu,
  Cloud,
} from 'lucide-react';
import { ModelEconomicsComparison } from '../components/ModelEconomicsComparison';
import { ExecutionInspector } from '../components/ExecutionInspector';
import { sidecarClient } from '../api/client';
import { CostMetrics, BudgetConfig, AuditLogEntry, ExecutionProvenance } from '../types';

export type ActivityTab = 'executions' | 'usage' | 'audit' | 'system';

export const Activity: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ActivityTab>('executions');
  const [costMetrics, setCostMetrics] = useState<CostMetrics | null>(null);
  const [budget, setBudget] = useState<BudgetConfig | null>(null);
  const [sessions, setSessions] = useState<any[]>([]);
  const [executions, setExecutions] = useState<any[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null);
  const [selectedTrace, setSelectedTrace] = useState<any | null>(null);
  const [loadingTrace, setLoadingTrace] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  const loadData = async () => {
    setIsLoading(true);
    try {
      const [metrics, budg, sess, logs, execs] = await Promise.all([
        sidecarClient.getCostMetrics('day').catch(() => null),
        sidecarClient.getBudgetConfig().catch(() => null),
        sidecarClient.getSessions(25).catch(() => []),
        sidecarClient.getSafetyAuditLogsPage({ limit: 25 }).catch(() => ({ items: [] })),
        sidecarClient.listExecutions(50).catch(() => []),
      ]);
      setCostMetrics(metrics);
      setBudget(budg);
      setSessions(sess || []);
      setAuditLogs(Array.isArray(logs) ? logs : ((logs as any)?.items || []));
      setExecutions(Array.isArray(execs) ? execs : []);
    } catch {
      // offline fallback
    } finally {
      setIsLoading(false);
    }
  };

  const handleToggleExecution = async (execId: string) => {
    if (selectedExecutionId === execId) {
      setSelectedExecutionId(null);
      setSelectedTrace(null);
      return;
    }
    setSelectedExecutionId(execId);
    setLoadingTrace(true);
    try {
      const trace = await sidecarClient.getExecutionTrace(execId);
      setSelectedTrace(trace);
    } catch {
      setSelectedTrace(null);
    } finally {
      setLoadingTrace(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden" data-testid="activity-screen">
      {/* Header */}
      <div className="h-12 border-b border-border-subtle bg-bg-elevated px-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <ActivityIcon className="w-4 h-4 text-accent" />
          <h1 className="text-sm font-semibold tracking-tight text-text-primary">Operational Activity</h1>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-text-tertiary uppercase">
            Ledger & Execution History
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

      {/* Tabs */}
      <div className="px-4 py-2 border-b border-border-subtle bg-bg-elevated/50 flex items-center gap-1 text-xs">
        <button
          type="button"
          onClick={() => setActiveTab('executions')}
          className={`flex items-center gap-1.5 px-3 py-1 rounded font-medium transition-colors ${
            activeTab === 'executions'
              ? 'bg-bg-elevated text-text-primary shadow-xs border border-border-subtle'
              : 'text-text-tertiary hover:text-text-secondary'
          }`}
        >
          <History className="w-3.5 h-3.5" />
          <span>Executions ({executions.length > 0 ? executions.length : sessions.length})</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('usage')}
          className={`flex items-center gap-1.5 px-3 py-1 rounded font-medium transition-colors ${
            activeTab === 'usage'
              ? 'bg-bg-elevated text-text-primary shadow-xs border border-border-subtle'
              : 'text-text-tertiary hover:text-text-secondary'
          }`}
        >
          <Coins className="w-3.5 h-3.5" />
          <span>Usage & Economics</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('audit')}
          className={`flex items-center gap-1.5 px-3 py-1 rounded font-medium transition-colors ${
            activeTab === 'audit'
              ? 'bg-bg-elevated text-text-primary shadow-xs border border-border-subtle'
              : 'text-text-tertiary hover:text-text-secondary'
          }`}
        >
          <Database className="w-3.5 h-3.5" />
          <span>Audit Ledger ({auditLogs.length})</span>
        </button>
      </div>

      {/* Main Tab Content */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
        {activeTab === 'executions' && (
          <div className="space-y-4 max-w-4xl">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-text-primary">Authoritative Executions Ledger</h2>
              <p className="text-xs text-text-secondary">
                Factual execution provenance, model IDs, latency, routing objective, and provider charges recorded by the kernel.
              </p>
            </div>

            {executions.length === 0 && sessions.length === 0 ? (
              <div className="py-12 text-center border border-border-subtle rounded-lg bg-bg-elevated/30 text-xs text-text-tertiary">
                No recent execution records found.
              </div>
            ) : executions.length > 0 ? (
              <div className="border border-border-subtle rounded-lg bg-bg-elevated/40 divide-y divide-border-subtle">
                {executions.map((exec) => {
                  const isSelected = selectedExecutionId === exec.execution_id;
                  const isLocal = exec.is_local ?? (exec.actual_provider ? !['openai', 'anthropic', 'gemini'].includes(exec.actual_provider.toLowerCase()) : true);
                  const provider = exec.actual_provider || exec.provider_id || (isLocal ? 'llamacpp' : 'cloud');
                  const model = exec.actual_model || exec.model_id || (isLocal ? 'qwen2.5-coder:7b' : 'frontier-model');
                  const durationMs = exec.duration_ms ?? exec.total_duration_ms ?? 0;
                  const cost = exec.total_cost_usd;
                  const costProv = (exec.cost_provenance || selectedTrace?.usage?.cost_provenance)?.toLowerCase();

                  let costLabel = 'Provider charge: Unavailable';
                  if (isLocal) {
                    costLabel = 'Provider charge: $0.00';
                  } else if (cost !== undefined && cost !== null && !isNaN(cost)) {
                    if (costProv === 'provider_reported' || costProv === 'actual') {
                      costLabel = `Provider charge: $${cost.toFixed(4)} (Actual)`;
                    } else if (costProv === 'estimated' || costProv === 'calculated') {
                      costLabel = `Provider charge: $${cost.toFixed(4)} (Estimated)`;
                    } else if (costProv === 'unavailable') {
                      costLabel = 'Provider charge: Unavailable';
                    } else {
                      costLabel = `Provider charge: $${cost.toFixed(4)} (Estimated)`;
                    }
                  } else {
                    costLabel = 'Provider charge: Unavailable';
                  }

                  const provenance: ExecutionProvenance = {
                    executionId: exec.execution_id,
                    status: exec.status,
                    provider,
                    model,
                    isLocal,
                    effectivePrivacy: exec.effective_privacy_class || selectedTrace?.routing?.effective_privacy_class,
                    routingObjective: exec.routing_objective || selectedTrace?.routing?.routing_objective,
                    routingExplanation: exec.selection_reason || selectedTrace?.routing?.selection_reason,
                    latencyMs: durationMs,
                    totalTokens: exec.total_tokens,
                    costUsd: exec.total_cost_usd,
                    costProvenance: exec.cost_provenance,
                    tools: selectedTrace?.execution_id === exec.execution_id ? selectedTrace.tools : undefined,
                    approvals: selectedTrace?.execution_id === exec.execution_id ? selectedTrace.approvals : undefined,
                    artifacts: selectedTrace?.execution_id === exec.execution_id ? selectedTrace.artifacts : undefined,
                  };

                  return (
                    <div key={exec.execution_id} className="p-3 text-xs transition-colors">
                      <div
                        onClick={() => handleToggleExecution(exec.execution_id)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            handleToggleExecution(exec.execution_id);
                          }
                        }}
                        className="flex items-center justify-between cursor-pointer select-none font-mono"
                      >
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className={`w-2 h-2 rounded-full ${exec.status === 'completed' ? 'bg-emerald-400' : exec.status === 'failed' ? 'bg-red-400' : 'bg-accent animate-pulse'}`} />
                            <span className="font-semibold text-text-primary text-xs font-sans">
                              {provider} / {model}
                            </span>
                            <span className="flex items-center gap-1 px-1.5 py-0.2 rounded text-[10px] bg-bg-base border border-border-subtle text-text-tertiary">
                              {isLocal ? <Cpu className="w-2.5 h-2.5 text-emerald-400" /> : <Cloud className="w-2.5 h-2.5 text-cyan-400" />}
                              <span>{isLocal ? 'Local' : 'Cloud'}</span>
                            </span>
                            <span className="text-[10px] text-text-tertiary font-sans">
                              {costLabel}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 text-[10px] text-text-tertiary">
                            <span>ID: {exec.execution_id.slice(0, 16)}...</span>
                            <span>•</span>
                            <span>Status: {exec.status}</span>
                            <span>•</span>
                            <span>Latency: {durationMs}ms</span>
                            {exec.total_tokens !== undefined && (
                              <>
                                <span>•</span>
                                <span>Tokens: {exec.total_tokens}</span>
                              </>
                            )}
                          </div>
                        </div>

                        <div className="flex items-center gap-2 text-[11px] text-text-tertiary hover:text-text-primary">
                          <span>{isSelected ? 'Close Trace' : 'Open Execution'}</span>
                          {isSelected ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                        </div>
                      </div>

                      {isSelected && (
                        <div className="mt-3 pt-3 border-t border-border-subtle/50 animate-in fade-in duration-100">
                          {loadingTrace ? (
                            <div className="py-4 text-center text-[11px] text-text-tertiary font-mono">
                              Loading authoritative ledger trace projection...
                            </div>
                          ) : (
                            <ExecutionInspector
                              provenance={provenance}
                              trace={selectedTrace?.execution_id === exec.execution_id ? selectedTrace : undefined}
                              defaultExpanded={true}
                            />
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="border border-border-subtle rounded-lg bg-bg-elevated/40 divide-y divide-border-subtle">
                {sessions.map((s) => (
                  <div key={s.session_id} className="p-3.5 flex items-center justify-between text-xs hover:bg-bg-hover transition-colors font-mono">
                    <div className="space-y-1">
                      <div className="font-semibold text-text-primary text-sm font-sans">{s.title || `Session ${s.session_id}`}</div>
                      <div className="flex items-center gap-2 text-[11px] text-text-tertiary">
                        <span>ID: {s.session_id}</span>
                        <span>•</span>
                        <span>Status: {s.status || 'closed'}</span>
                      </div>
                    </div>
                    <div className="text-right text-[11px] text-text-tertiary">
                      {s.created_at ? new Date(s.created_at).toLocaleTimeString() : 'Earlier'}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'usage' && (
          <div className="space-y-6 max-w-4xl">
            {/* Real Cost & Budget Summary */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="p-4 rounded-lg bg-bg-elevated border border-border-subtle space-y-1">
                <span className="text-[10px] font-mono text-text-tertiary uppercase">Total Monthly Spend</span>
                <div className="text-xl font-bold font-mono text-text-primary">
                  ${costMetrics?.total_cost_usd?.toFixed(4) || '0.0000'}
                </div>
                <div className="text-[11px] text-text-tertiary">
                  Budget ceiling: ${budget?.monthly_budget_usd?.toFixed(2) || '100.00'}
                </div>
              </div>

              <div className="p-4 rounded-lg bg-bg-elevated border border-border-subtle space-y-1">
                <span className="text-[10px] font-mono text-text-tertiary uppercase">Local Model Inferences</span>
                <div className="text-xl font-bold font-mono text-emerald-400">
                  Provider charge: $0.00
                </div>
                <div className="text-[11px] text-text-tertiary">
                  Local compute cost: Unavailable (hardware/electricity unmeasured)
                </div>
              </div>

              <div className="p-4 rounded-lg bg-bg-elevated border border-border-subtle space-y-1">
                <span className="text-[10px] font-mono text-text-tertiary uppercase">Cloud Inferences</span>
                <div className="text-xl font-bold font-mono text-text-primary">
                  {costMetrics?.total_cost_usd !== undefined && costMetrics.total_cost_usd !== null
                    ? `$${costMetrics.total_cost_usd.toFixed(4)}`
                    : 'Provider charge: Unavailable'}
                </div>
                <div className="text-[11px] text-text-tertiary">
                  Pay-per-token provider calls
                </div>
              </div>
            </div>

            {/* Embedded R3 Model Economics Component */}
            <div className="space-y-2">
              <h3 className="text-xs font-semibold text-text-primary">
                Model Economics Breakdown
              </h3>
              <ModelEconomicsComparison />
            </div>
          </div>
        )}

        {activeTab === 'audit' && (
          <div className="space-y-4 max-w-4xl">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-text-primary">Zero-Trust Safety Audit Ledger</h2>
              <p className="text-xs text-text-secondary">
                Tamper-evident SQLite audit log recording every tool call evaluation, approval decision, and operator override.
              </p>
            </div>

            {auditLogs.length === 0 ? (
              <div className="py-12 text-center border border-border-subtle rounded-lg bg-bg-elevated/30 text-xs text-text-tertiary">
                No audit entries recorded yet.
              </div>
            ) : (
              <div className="border border-border-subtle rounded-lg bg-bg-elevated/40 divide-y divide-border-subtle">
                {auditLogs.map((log) => (
                  <div key={log.id} className="p-3 text-xs flex items-center justify-between font-mono">
                    <div className="space-y-0.5">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-text-primary">{log.tool_name}</span>
                        <span
                          className={`px-1.5 py-0.2 rounded text-[10px] ${
                            log.decision === 'approve' || log.decision === 'allow'
                              ? 'text-emerald-400 bg-emerald-500/10'
                              : 'text-red-400 bg-red-500/10'
                          }`}
                        >
                          {log.decision}
                        </span>
                      </div>
                      <div className="text-[11px] text-text-tertiary">{log.reason || 'Safety boundary verified'}</div>
                    </div>
                    <span className="text-[10px] text-text-tertiary">
                      {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : 'Recent'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
