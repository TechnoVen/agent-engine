import React, { useState, useEffect, useMemo } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Clock,
  RefreshCw,
  Search,
  Terminal,
  FileCode,
  Database,
  Cog,
  Check,
  X,
  Edit3,
  Key,
  ListOrdered,
  FileText,
} from 'lucide-react';
import {
  Mode,
  ModelTier,
  RiskLevel,
  PendingOperation,
  SafetyPolicyRuleInfo,
  AuditLogEntry,
} from '../types';
import { sidecarClient } from '../api/client';

export interface PoliciesScreenProps {
  onSelectMode: (mode: Mode) => void;
  activeModel?: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
}

type TabType = 'queue' | 'policies' | 'audit';

export const Policies: React.FC<PoliciesScreenProps> = () => {
  const [activeTab, setActiveTab] = useState<TabType>('queue');
  const [operations, setOperations] = useState<PendingOperation[]>([]);
  const [policies, setPolicies] = useState<SafetyPolicyRuleInfo[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(Date.now() / 1000);

  // Selection for batch actions
  const [selectedOpIds, setSelectedOpIds] = useState<string[]>([]);
  const [batchActionRunning, setBatchActionRunning] = useState<boolean>(false);

  // Rejection dialog state
  const [rejectDialogOpId, setRejectDialogOpId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<string>('');

  // Editing parameters state
  const [editingOpId, setEditingOpId] = useState<string | null>(null);
  const [editParamsText, setEditParamsText] = useState<string>('');
  const [editParamsError, setEditParamsError] = useState<string | null>(null);

  // Filter states
  const [queueFilter, setQueueFilter] = useState<string>('all'); // all | pending | approved | rejected | expired
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [auditFilter, setAuditFilter] = useState<string>('all');

  // Fetch all data
  const fetchData = async (showRefreshIndicator = false) => {
    if (showRefreshIndicator) setRefreshing(true);
    try {
      const [ops, pols, audits] = await Promise.all([
        sidecarClient.listPendingOperations(),
        sidecarClient.listSafetyPolicies(),
        sidecarClient.getSafetyAuditLogs(100),
      ]);
      setOperations(ops);
      setPolicies(pols);
      setAuditLogs(audits);
    } catch (err) {
      console.error('Failed to fetch policies or operations', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  // Initial load and periodic refresh
  useEffect(() => {
    fetchData();
    const timer = setInterval(() => {
      fetchData();
    }, 4000);
    return () => clearInterval(timer);
  }, []);

  // Update current time every second for countdown timers
  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(Date.now() / 1000);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const pendingCount = useMemo(() => {
    return operations.filter(
      (op) => op.status === 'pending' && op.expires_at > currentTime
    ).length;
  }, [operations, currentTime]);

  const filteredOperations = useMemo(() => {
    return operations.filter((op) => {
      const isPendingValid = op.status === 'pending' && op.expires_at > currentTime;
      const isExpired = op.status === 'expired' || (op.status === 'pending' && op.expires_at <= currentTime);

      if (queueFilter === 'pending' && !isPendingValid) return false;
      if (queueFilter === 'expired' && !isExpired) return false;
      if (queueFilter === 'approved' && op.status !== 'approved' && op.status !== 'consumed') return false;
      if (queueFilter === 'rejected' && op.status !== 'rejected') return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchName = op.tool_name.toLowerCase().includes(q);
        const matchId = op.operation_id.toLowerCase().includes(q);
        const matchReason = (op.reason || '').toLowerCase().includes(q);
        if (!matchName && !matchId && !matchReason) return false;
      }
      return true;
    });
  }, [operations, queueFilter, searchQuery, currentTime]);

  const filteredPolicies = useMemo(() => {
    if (!searchQuery.trim()) return policies;
    const q = searchQuery.toLowerCase();
    return policies.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.rule_id.toLowerCase().includes(q) ||
        p.description.toLowerCase().includes(q) ||
        (p.tool_pattern || '').toLowerCase().includes(q)
    );
  }, [policies, searchQuery]);

  const filteredAuditLogs = useMemo(() => {
    return auditLogs.filter((log) => {
      if (auditFilter !== 'all' && !log.decision.toLowerCase().includes(auditFilter.toLowerCase())) {
        return false;
      }
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchTool = log.tool_name.toLowerCase().includes(q);
        const matchReason = (log.reason || '').toLowerCase().includes(q);
        const matchPolicy = (log.policy_id || '').toLowerCase().includes(q);
        if (!matchTool && !matchReason && !matchPolicy) return false;
      }
      return true;
    });
  }, [auditLogs, auditFilter, searchQuery]);

  // Single Approve
  const handleApprove = async (op: PendingOperation, modifiedArgs?: Record<string, any>) => {
    try {
      await sidecarClient.approveOperation(op.operation_id, 'operator', modifiedArgs);
      setEditingOpId(null);
      await fetchData();
    } catch (err: any) {
      alert(`Approval failed: ${err?.message || err}`);
    }
  };

  // Single Reject
  const handleRejectConfirm = async () => {
    if (!rejectDialogOpId) return;
    try {
      await sidecarClient.rejectOperation(
        rejectDialogOpId,
        'operator',
        rejectReason.trim() || 'Rejected by human operator'
      );
      setRejectDialogOpId(null);
      setRejectReason('');
      await fetchData();
    } catch (err: any) {
      alert(`Rejection failed: ${err?.message || err}`);
    }
  };

  // Batch actions
  const handleBatchAction = async (action: 'approve' | 'reject') => {
    if (selectedOpIds.length === 0) return;
    setBatchActionRunning(true);
    try {
      await sidecarClient.batchOperations(
        selectedOpIds,
        action,
        'operator',
        action === 'reject' ? 'Batch rejected by human operator' : undefined
      );
      setSelectedOpIds([]);
      await fetchData();
    } catch (err: any) {
      alert(`Batch action failed: ${err?.message || err}`);
    } finally {
      setBatchActionRunning(false);
    }
  };

  const toggleSelectOp = (id: string) => {
    setSelectedOpIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const handleSelectAll = () => {
    const pendingIds = filteredOperations
      .filter((op) => op.status === 'pending' && op.expires_at > currentTime)
      .map((op) => op.operation_id);
    setSelectedOpIds(pendingIds);
  };

  const handleDeselectAll = () => {
    setSelectedOpIds([]);
  };

  // Risk styling helper
  const getRiskBadge = (level: RiskLevel, score: number) => {
    switch (level) {
      case 'critical':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-danger/15 border border-danger/40 text-danger">
            <ShieldAlert className="w-3.5 h-3.5" />
            CRITICAL ({Math.round(score * 100)}%)
          </span>
        );
      case 'high':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-warning/15 border border-warning/40 text-warning">
            <AlertTriangle className="w-3.5 h-3.5" />
            HIGH ({Math.round(score * 100)}%)
          </span>
        );
      case 'medium':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-amber-400/15 border border-amber-400/30 text-amber-400">
            <AlertCircle className="w-3.5 h-3.5" />
            MEDIUM ({Math.round(score * 100)}%)
          </span>
        );
      case 'low':
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-success/15 border border-success/30 text-success">
            <ShieldCheck className="w-3.5 h-3.5" />
            LOW ({Math.round(score * 100)}%)
          </span>
        );
    }
  };

  const getToolIcon = (name: string) => {
    const lower = name.toLowerCase();
    if (lower.includes('bash') || lower.includes('shell') || lower.includes('cmd') || lower.includes('terminal')) {
      return <Terminal className="w-4 h-4 text-accent" />;
    }
    if (lower.includes('file') || lower.includes('write') || lower.includes('patch')) {
      return <FileCode className="w-4 h-4 text-warning" />;
    }
    if (lower.includes('sql') || lower.includes('db') || lower.includes('database')) {
      return <Database className="w-4 h-4 text-accent" />;
    }
    return <Cog className="w-4 h-4 text-text-secondary" />;
  };

  return (
    <div className="h-full flex flex-col bg-bg-base overflow-hidden select-none">
      {/* Header Bar */}
      <div className="p-4 border-b border-border-subtle bg-bg-elevated/40 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold text-text-primary">Policies & Approvals</h1>
                {pendingCount > 0 ? (
                  <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-danger/20 border border-danger/40 text-danger animate-pulse">
                    {pendingCount} Pending Approval
                  </span>
                ) : (
                  <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-success/15 border border-success/30 text-success flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" /> Zero-Trust Gate Active
                  </span>
                )}
              </div>
              <p className="text-xs text-text-secondary mt-0.5">
                Centralized Zero-Trust boundary • Single-use execution tokens • Fail-closed safety gate
              </p>
            </div>
          </div>
        </div>

        {/* Tab Selector & Refresh */}
        <div className="flex items-center gap-2">
          <div className="flex bg-bg-base border border-border-subtle rounded-lg p-1">
            <button
              onClick={() => setActiveTab('queue')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                activeTab === 'queue'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <ListOrdered className="w-3.5 h-3.5" />
              Approval Queue
              {pendingCount > 0 && (
                <span className="w-4 h-4 rounded-full bg-white/20 text-white text-[10px] flex items-center justify-center font-bold">
                  {pendingCount}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab('policies')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                activeTab === 'policies'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              Active Policies ({policies.length})
            </button>
            <button
              onClick={() => setActiveTab('audit')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                activeTab === 'audit'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              Audit Trail ({auditLogs.length})
            </button>
          </div>

          <button
            onClick={() => fetchData(true)}
            disabled={refreshing}
            className="p-2 rounded-lg bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-text-secondary hover:text-text-primary transition-all disabled:opacity-50"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-accent' : ''}`} />
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-4 max-w-6xl w-full mx-auto space-y-4">
        {/* Search & Filter Bar */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-bg-elevated/40 p-3 rounded-xl border border-border-subtle">
          <div className="relative flex-1 w-full">
            <Search className="w-4 h-4 absolute left-3 top-2.5 text-text-tertiary" />
            <input
              type="text"
              placeholder={`Search ${activeTab}...`}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
            />
          </div>

          {activeTab === 'queue' && (
            <div className="flex items-center gap-2 w-full sm:w-auto">
              <select
                value={queueFilter}
                onChange={(e) => setQueueFilter(e.target.value)}
                aria-label="Filter queue by status"
                className="bg-bg-base border border-border-subtle rounded-lg px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent"
              >
                <option value="all">All States</option>
                <option value="pending">Pending Only</option>
                <option value="approved">Approved</option>
                <option value="rejected">Rejected</option>
                <option value="expired">Expired</option>
              </select>

              {pendingCount > 0 && (
                <div className="flex items-center gap-1">
                  <button
                    onClick={handleSelectAll}
                    className="px-2.5 py-1.5 bg-bg-base hover:bg-bg-hover border border-border-subtle rounded-lg text-xs text-text-secondary hover:text-text-primary font-medium"
                  >
                    Select All
                  </button>
                  {selectedOpIds.length > 0 && (
                    <>
                      <button
                        onClick={handleDeselectAll}
                        className="px-2.5 py-1.5 bg-bg-base hover:bg-bg-hover border border-border-subtle rounded-lg text-xs text-text-secondary hover:text-text-primary"
                      >
                        Clear ({selectedOpIds.length})
                      </button>
                      <button
                        onClick={() => handleBatchAction('approve')}
                        disabled={batchActionRunning}
                        className="px-3 py-1.5 bg-success/20 hover:bg-success/30 border border-success/40 text-success rounded-lg text-xs font-semibold flex items-center gap-1 transition-all"
                      >
                        <Check className="w-3.5 h-3.5" /> Approve ({selectedOpIds.length})
                      </button>
                      <button
                        onClick={() => handleBatchAction('reject')}
                        disabled={batchActionRunning}
                        className="px-3 py-1.5 bg-danger/20 hover:bg-danger/30 border border-danger/40 text-danger rounded-lg text-xs font-semibold flex items-center gap-1 transition-all"
                      >
                        <X className="w-3.5 h-3.5" /> Reject ({selectedOpIds.length})
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          {activeTab === 'audit' && (
            <select
              value={auditFilter}
              onChange={(e) => setAuditFilter(e.target.value)}
              aria-label="Filter audit logs by decision"
              className="bg-bg-base border border-border-subtle rounded-lg px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent w-full sm:w-auto"
            >
              <option value="all">All Decisions</option>
              <option value="allow">Allow</option>
              <option value="block">Block / Deny</option>
              <option value="operator_approved">Operator Approved</option>
              <option value="operator_rejected">Operator Rejected</option>
            </select>
          )}
        </div>

        {/* TAB 1: PENDING QUEUE */}
        {activeTab === 'queue' && (
          <div className="space-y-3">
            {loading ? (
              <div className="p-12 text-center text-text-secondary text-sm">
                <RefreshCw className="w-5 h-5 animate-spin text-accent mx-auto mb-2" />
                Loading pending queue...
              </div>
            ) : filteredOperations.length === 0 ? (
              <div className="p-12 text-center bg-bg-elevated/20 border border-border-subtle rounded-2xl">
                <div className="w-12 h-12 rounded-2xl bg-success/15 border border-success/30 text-success flex items-center justify-center mx-auto mb-3">
                  <ShieldCheck className="w-6 h-6" />
                </div>
                <h3 className="text-base font-semibold text-text-primary">Approval Queue Clear</h3>
                <p className="text-xs text-text-secondary max-w-md mx-auto mt-1">
                  No high-risk operations are currently awaiting manual approval. All staged actions, file modifications, and critical system calls will appear here before execution tokens are granted.
                </p>
              </div>
            ) : (
              filteredOperations.map((op) => {
                const isPending = op.status === 'pending' && op.expires_at > currentTime;
                const isExpired = op.status === 'expired' || (op.status === 'pending' && op.expires_at <= currentTime);
                const secondsLeft = Math.max(0, Math.round(op.expires_at - currentTime));
                const isSelected = selectedOpIds.includes(op.operation_id);

                return (
                  <div
                    key={op.operation_id}
                    className={`p-4 rounded-xl border transition-all ${
                      isPending
                        ? 'bg-bg-elevated/70 border-warning/30 shadow-sm'
                        : isExpired
                        ? 'bg-bg-elevated/30 border-border-subtle opacity-75'
                        : op.status === 'approved' || op.status === 'consumed'
                        ? 'bg-bg-elevated/40 border-success/30'
                        : 'bg-bg-elevated/40 border-danger/30'
                    }`}
                  >
                    {/* Top Row: Select, Risk Badge, Tool Name, TTL */}
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-border-subtle/50">
                      <div className="flex items-center gap-2.5">
                        {isPending && (
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelectOp(op.operation_id)}
                            className="w-4 h-4 rounded border-border-strong text-accent focus:ring-accent"
                          />
                        )}
                        {getRiskBadge(op.risk_level, op.risk_score)}
                        <div className="flex items-center gap-1.5 font-mono text-sm font-semibold text-text-primary">
                          {getToolIcon(op.tool_name)}
                          <span>{op.tool_name}</span>
                        </div>
                      </div>

                      <div className="flex items-center gap-3">
                        {isPending ? (
                          <div
                            className={`flex items-center gap-1 text-xs font-mono font-semibold px-2 py-0.5 rounded border ${
                              secondsLeft < 15
                                ? 'bg-danger/20 border-danger/40 text-danger animate-pulse'
                                : 'bg-warning/10 border-warning/30 text-warning'
                            }`}
                          >
                            <Clock className="w-3.5 h-3.5" />
                            <span>Expires in {secondsLeft}s</span>
                          </div>
                        ) : isExpired ? (
                          <span className="text-xs font-mono px-2 py-0.5 rounded bg-bg-base border border-border-subtle text-text-tertiary">
                            Expired (&gt;60s)
                          </span>
                        ) : op.status === 'approved' || op.status === 'consumed' ? (
                          <span className="text-xs font-mono px-2 py-0.5 rounded bg-success/15 border border-success/30 text-success flex items-center gap-1">
                            <Check className="w-3 h-3" /> {op.status === 'consumed' ? 'Consumed' : 'Approved'}
                          </span>
                        ) : (
                          <span className="text-xs font-mono px-2 py-0.5 rounded bg-danger/15 border border-danger/30 text-danger flex items-center gap-1">
                            <X className="w-3 h-3" /> Rejected
                          </span>
                        )}

                        <span className="text-xs font-mono text-text-tertiary">
                          {op.operation_id}
                        </span>
                      </div>
                    </div>

                    {/* Middle Row: Reason and Parameter details */}
                    <div className="py-3 space-y-2">
                      {op.reason && (
                        <div className="text-xs text-text-primary bg-bg-base/60 p-2.5 rounded-lg border border-border-subtle">
                          <span className="font-semibold text-text-secondary">Trigger Reason: </span>
                          {op.reason}
                        </div>
                      )}

                      {/* Tool Arguments View / Edit */}
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
                            Bound Tool Arguments (SHA-256 Digest: {op.args_hash.slice(0, 12)}...)
                          </span>
                          {isPending && (
                            <button
                              onClick={() => {
                                if (editingOpId === op.operation_id) {
                                  setEditingOpId(null);
                                } else {
                                  setEditingOpId(op.operation_id);
                                  setEditParamsText(JSON.stringify(op.tool_args, null, 2));
                                  setEditParamsError(null);
                                }
                              }}
                              className="text-xs text-accent hover:underline flex items-center gap-1"
                            >
                              <Edit3 className="w-3 h-3" />
                              {editingOpId === op.operation_id ? 'Cancel Edit' : 'Edit Parameters'}
                            </button>
                          )}
                        </div>

                        {editingOpId === op.operation_id ? (
                          <div className="space-y-2">
                            <textarea
                              value={editParamsText}
                              onChange={(e) => {
                                setEditParamsText(e.target.value);
                                setEditParamsError(null);
                              }}
                              rows={5}
                              className="w-full p-2.5 bg-bg-base border border-accent/40 rounded-lg font-mono text-xs text-text-primary focus:outline-none focus:border-accent"
                            />
                            {editParamsError && (
                              <div className="text-xs text-danger">{editParamsError}</div>
                            )}
                            <div className="flex justify-end gap-2">
                              <button
                                onClick={() => setEditingOpId(null)}
                                className="px-2.5 py-1 text-xs text-text-secondary hover:text-text-primary"
                              >
                                Cancel
                              </button>
                              <button
                                onClick={() => {
                                  try {
                                    const parsed = JSON.parse(editParamsText);
                                    handleApprove(op, parsed);
                                  } catch (e: any) {
                                    setEditParamsError(`Invalid JSON: ${e?.message}`);
                                  }
                                }}
                                className="px-3 py-1 bg-accent hover:bg-accent-hover text-white text-xs font-semibold rounded-md shadow-sm"
                              >
                                Approve with Edited Params
                              </button>
                            </div>
                          </div>
                        ) : (
                          <pre className="p-2.5 bg-bg-base/70 rounded-lg border border-border-subtle font-mono text-xs text-text-secondary overflow-x-auto max-h-36">
                            {JSON.stringify(op.tool_args, null, 2)}
                          </pre>
                        )}
                      </div>

                      {/* Approval Token Information if Approved */}
                      {op.approval_token && (
                        <div className="flex items-center gap-2 p-2 bg-success/10 border border-success/20 rounded-lg text-xs text-success font-mono">
                          <Key className="w-3.5 h-3.5 flex-shrink-0" />
                          <span className="font-semibold">Single-Use Token:</span>
                          <span className="select-all text-[11px] truncate">{op.approval_token}</span>
                        </div>
                      )}

                      {/* Rejection reason if Rejected */}
                      {op.decision_reason && op.status === 'rejected' && (
                        <div className="p-2 bg-danger/10 border border-danger/20 rounded-lg text-xs text-danger">
                          <span className="font-semibold">Rejection Reason: </span>
                          {op.decision_reason}
                        </div>
                      )}
                    </div>

                    {/* Bottom Action Buttons (Only for Pending operations) */}
                    {isPending && (
                      <div className="pt-2 border-t border-border-subtle/50 flex items-center justify-end gap-2">
                        <button
                          onClick={() => {
                            setRejectDialogOpId(op.operation_id);
                            setRejectReason('Rejected by human operator');
                          }}
                          className="px-3 py-1.5 rounded-lg border border-danger/40 hover:bg-danger/10 text-danger text-xs font-semibold flex items-center gap-1 transition-all"
                        >
                          <X className="w-3.5 h-3.5" /> Reject
                        </button>
                        <button
                          onClick={() => handleApprove(op)}
                          className="px-4 py-1.5 rounded-lg bg-success hover:bg-success-hover text-white text-xs font-bold flex items-center gap-1.5 shadow-sm transition-all"
                        >
                          <Check className="w-3.5 h-3.5" /> Approve & Issue Token
                        </button>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        )}

        {/* TAB 2: ACTIVE POLICIES */}
        {activeTab === 'policies' && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {filteredPolicies.map((rule) => {
                const isBlock = rule.action === 'block' || rule.action === 'deny';
                return (
                  <div
                    key={rule.rule_id}
                    className="p-4 rounded-xl bg-bg-elevated/40 border border-border-subtle flex flex-col justify-between gap-3"
                  >
                    <div>
                      <div className="flex items-center justify-between gap-2 mb-1.5">
                        <span className="font-mono text-xs font-bold text-text-primary">
                          {rule.name}
                        </span>
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded uppercase ${
                            isBlock
                              ? 'bg-danger/20 border border-danger/40 text-danger'
                              : rule.action === 'stage'
                              ? 'bg-warning/20 border border-warning/40 text-warning'
                              : 'bg-accent/20 border border-accent/40 text-accent'
                          }`}
                        >
                          {rule.action}
                        </span>
                      </div>
                      <p className="text-xs text-text-secondary leading-relaxed">
                        {rule.description}
                      </p>
                    </div>

                    <div className="pt-2 border-t border-border-subtle/50 flex items-center justify-between text-[11px] font-mono text-text-tertiary">
                      <span>Pattern: {rule.tool_pattern || '*'}</span>
                      <span className="capitalize text-text-secondary">Severity: {rule.severity}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* TAB 3: AUDIT LOG */}
        {activeTab === 'audit' && (
          <div className="bg-bg-elevated/40 border border-border-subtle rounded-xl overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-bg-base/80 border-b border-border-subtle text-text-tertiary font-mono uppercase tracking-wider">
                  <tr>
                    <th className="p-3">Timestamp</th>
                    <th className="p-3">Tool Name</th>
                    <th className="p-3">Decision</th>
                    <th className="p-3">Risk</th>
                    <th className="p-3">Policy / Reason</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle/50 font-mono">
                  {filteredAuditLogs.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="p-6 text-center text-text-tertiary font-sans">
                        No audit log records found matching query.
                      </td>
                    </tr>
                  ) : (
                    filteredAuditLogs.map((log) => {
                      const isDeny = log.decision.includes('block') || log.decision.includes('deny') || log.decision.includes('reject');
                      const isApprove = log.decision.includes('approve') || log.decision.includes('allow');
                      return (
                        <tr key={log.id} className="hover:bg-bg-hover/50 transition-colors">
                          <td className="p-3 text-text-tertiary text-[11px] whitespace-nowrap">
                            {new Date(log.timestamp).toLocaleTimeString()}
                          </td>
                          <td className="p-3 font-semibold text-text-primary whitespace-nowrap">
                            {log.tool_name}
                          </td>
                          <td className="p-3">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                                isDeny
                                  ? 'bg-danger/15 text-danger border border-danger/30'
                                  : isApprove
                                  ? 'bg-success/15 text-success border border-success/30'
                                  : 'bg-warning/15 text-warning border border-warning/30'
                              }`}
                            >
                              {log.decision}
                            </span>
                          </td>
                          <td className="p-3">
                            <span className="text-text-secondary">
                              {Math.round(log.risk_score * 100)}%
                            </span>
                          </td>
                          <td className="p-3 font-sans text-text-secondary max-w-xs truncate">
                            {log.reason || log.policy_id || '—'}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Reject Reason Modal Dialog */}
      {rejectDialogOpId && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
          <div className="bg-bg-elevated border border-border-subtle rounded-xl max-w-md w-full p-4 shadow-xl space-y-3 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-text-primary flex items-center gap-1.5">
                <XCircle className="w-4 h-4 text-danger" /> Reject Operation
              </h3>
              <button
                onClick={() => setRejectDialogOpId(null)}
                className="text-text-tertiary hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <p className="text-xs text-text-secondary">
              Provide an explicit reason for rejecting this operation. This explanation will be returned to the calling agent so it can adjust its execution plan.
            </p>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="e.g., Security policy forbids destructive disk modifications..."
              rows={3}
              className="w-full p-2.5 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary focus:outline-none focus:border-danger"
            />
            <div className="flex justify-end gap-2 pt-2 border-t border-border-subtle">
              <button
                onClick={() => setRejectDialogOpId(null)}
                className="px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                onClick={handleRejectConfirm}
                className="px-3 py-1.5 bg-danger hover:bg-danger-hover text-white text-xs font-bold rounded-lg shadow-sm"
              >
                Confirm Rejection
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
