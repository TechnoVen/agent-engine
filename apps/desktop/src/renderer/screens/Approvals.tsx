import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  RefreshCw,
  Check,
  X,
  History,
  AlertTriangle,
  Terminal,
} from 'lucide-react';
import { sidecarClient } from '../api/client';
import { PendingOperation, AuditLogEntry } from '../types';

export const Approvals: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'queue' | 'audit'>('queue');
  const [pendingOps, setPendingOps] = useState<PendingOperation[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const loadData = async (showRefresh = false) => {
    if (showRefresh) setIsRefreshing(true);
    else setIsLoading(true);
    setActionError(null);

    try {
      const [ops, logsPage] = await Promise.all([
        sidecarClient.listPendingOperations().catch(() => []),
        sidecarClient.getSafetyAuditLogsPage({ limit: 30 }).catch(() => ({ items: [] })),
      ]);
      setPendingOps(ops || []);
      setAuditLogs(Array.isArray(logsPage) ? logsPage : ((logsPage as any)?.items || []));
    } catch {
      setPendingOps([]);
      setAuditLogs([]);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleApprove = async (opId: string) => {
    try {
      await sidecarClient.approveOperation(opId);
      await loadData(true);
    } catch (err: any) {
      setActionError(`Approval failed: ${err?.message || 'Operation error'}`);
    }
  };

  const handleReject = async (opId: string) => {
    try {
      await sidecarClient.rejectOperation(opId, 'Rejected by operator in Approvals Console');
      await loadData(true);
    } catch (err: any) {
      setActionError(`Rejection failed: ${err?.message || 'Operation error'}`);
    }
  };

  const getRiskBadge = (level: string, score: number) => {
    if (level === 'critical' || score >= 0.8) {
      return 'bg-red-500/10 text-red-400 border-red-500/20';
    }
    if (level === 'high' || score >= 0.5) {
      return 'bg-amber-500/10 text-amber-400 border-amber-500/20';
    }
    return 'bg-blue-500/10 text-blue-400 border-blue-500/20';
  };

  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden" data-testid="approvals-screen">
      {/* Header */}
      <div className="h-12 border-b border-border-subtle bg-bg-elevated px-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <ShieldCheck className="w-4 h-4 text-accent" />
          <h1 className="text-sm font-semibold tracking-tight text-text-primary">Approvals Queue</h1>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-text-tertiary uppercase">
            R2 High-Risk Tool Operations
          </span>
        </div>

        <button
          type="button"
          onClick={() => loadData(true)}
          disabled={isRefreshing}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Action Error Banner */}
      {actionError && (
        <div className="px-4 py-2 bg-red-500/10 border-b border-red-500/20 text-xs text-red-400 flex items-center justify-between">
          <span>{actionError}</span>
          <button type="button" onClick={() => setActionError(null)} className="text-red-400 hover:text-red-300">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="px-4 py-2 border-b border-border-subtle bg-bg-elevated/50 flex items-center gap-1 text-xs">
        <button
          type="button"
          onClick={() => setActiveTab('queue')}
          className={`flex items-center gap-1.5 px-3 py-1 rounded font-medium transition-colors ${
            activeTab === 'queue'
              ? 'bg-bg-elevated text-text-primary shadow-xs border border-border-subtle'
              : 'text-text-tertiary hover:text-text-secondary'
          }`}
        >
          <AlertTriangle className="w-3.5 h-3.5 text-warning" />
          <span>Pending Approvals ({pendingOps.length})</span>
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
          <History className="w-3.5 h-3.5" />
          <span>Resolved Audit Log ({auditLogs.length})</span>
        </button>
      </div>

      {/* Main Content */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6">
        {activeTab === 'queue' && (
          <div className="space-y-4 max-w-4xl">
            {isLoading ? (
              <div className="py-16 text-center text-xs text-text-tertiary">
                <RefreshCw className="w-5 h-5 mx-auto animate-spin mb-2 text-accent" />
                Querying pending operation queue...
              </div>
            ) : pendingOps.length === 0 ? (
              <div className="py-16 text-center border border-border-subtle rounded-lg bg-bg-elevated/30 text-xs" data-testid="approvals-empty-state">
                <ShieldCheck className="w-10 h-10 mx-auto text-emerald-400/80 mb-2" />
                <div className="font-semibold text-text-primary text-sm">No approvals waiting.</div>
                <p className="text-text-tertiary text-[11px] mt-1 max-w-sm mx-auto">
                  All high-risk file modifications and tool executions are up to date.
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {pendingOps.map((op) => (
                  <div
                    key={op.operation_id}
                    className="p-4 rounded-lg bg-bg-elevated border border-border-subtle hover:border-border-strong transition-all space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Terminal className="w-4 h-4 text-accent" />
                        <span className="font-semibold text-sm text-text-primary font-mono">
                          {op.tool_name}
                        </span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-mono border uppercase ${getRiskBadge(
                            op.risk_level,
                            op.risk_score
                          )}`}
                        >
                          {op.risk_level} · Risk {op.risk_score.toFixed(2)}
                        </span>
                      </div>
                      <span className="text-[11px] font-mono text-text-tertiary">
                        ID: {op.operation_id.slice(0, 10)}...
                      </span>
                    </div>

                    <div className="text-xs text-text-secondary leading-relaxed bg-bg-base/60 p-2.5 rounded border border-border-subtle/50">
                      <span className="text-text-tertiary font-medium block text-[10px] uppercase mb-0.5">
                        Trigger Rationale
                      </span>
                      {op.reason || 'High-risk mutation requires operator zero-trust token.'}
                    </div>

                    {/* Affected Resources / Tool Args */}
                    {op.tool_args && Object.keys(op.tool_args).length > 0 && (
                      <div className="space-y-1">
                        <span className="text-[10px] font-semibold uppercase text-text-tertiary">
                          Affected Arguments & Resources
                        </span>
                        <pre className="p-2.5 rounded bg-bg-base border border-border-subtle text-[11px] font-mono text-text-secondary overflow-x-auto">
                          {JSON.stringify(op.tool_args, null, 2)}
                        </pre>
                      </div>
                    )}

                    {/* Decision Actions */}
                    <div className="flex items-center justify-end gap-2 pt-2 border-t border-border-subtle/50">
                      <button
                        type="button"
                        onClick={() => handleReject(op.operation_id)}
                        className="px-3 py-1.5 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-red-400 hover:text-red-300 font-medium transition-colors flex items-center gap-1.5"
                      >
                        <X className="w-3.5 h-3.5" />
                        <span>Reject</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => handleApprove(op.operation_id)}
                        className="px-3 py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium transition-colors flex items-center gap-1.5"
                      >
                        <Check className="w-3.5 h-3.5" />
                        <span>Approve Once</span>
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'audit' && (
          <div className="space-y-3 max-w-4xl">
            <div className="text-xs font-semibold text-text-primary">
              Immutable Safety Audit Ledger ({auditLogs.length} events)
            </div>
            {auditLogs.length === 0 ? (
              <div className="py-12 text-center text-xs text-text-tertiary">
                No resolved audit ledger records yet.
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
                      <div className="text-[11px] text-text-tertiary">{log.reason || 'Operator evaluated'}</div>
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
