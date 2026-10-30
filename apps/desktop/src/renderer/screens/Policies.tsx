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
  FileText,
  Play,
  Save,
  Download,
  Code2,
  Sliders,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  Mode,
  ModelTier,
  RiskLevel,
  PendingOperation,
  SafetyPolicyRuleInfo,
  AuditLogEntry,
  DryRunResult,
} from '../types';
import { sidecarClient } from '../api/client';

export interface PoliciesScreenProps {
  onSelectMode: (mode: Mode) => void;
  activeModel?: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
}

export type TabType = 'queue' | 'policies' | 'editor' | 'playground' | 'audit';

const POLICY_PRESETS = [
  {
    id: 'current',
    name: 'Current Server Policy',
  },
  {
    id: 'strict',
    name: 'Strict Lockdown (Zero-Tolerance)',
    yaml: `# Strict Zero-Tolerance Guardrail Policy
version: "1.0.0"
name: "Strict Enterprise Lockdown"
description: "Blocks all destructive system, filesystem, database, and repository modifications."

rules:
  - id: "block_all_deletes"
    name: "Universal Destructive Deletion Shield"
    description: "Blocks any command matching delete or rm."
    match_type: "regex"
    pattern: "(?i)(?:rm\s+-[a-zA-Z]*r|kubectl\s+delete|drop\s+database|truncate\s+table)"
    action: "block"
    risk_level: "critical"
    reason: "Strict policy prohibits all destructive delete operations."
    suggestion: "Use staging sandbox or read-only replica."

  - id: "block_secret_access"
    name: "Strict Credential Protection"
    description: "Blocks access to secrets, keys, and tokens."
    match_type: "glob"
    pattern: "**/{.env*,*.pem,*.key,id_rsa,credentials}"
    action: "block"
    risk_level: "critical"
    reason: "Credential inspection is strictly forbidden."
    suggestion: "Use KMS or secret reference placeholder."
`,
  },
  {
    id: 'dev',
    name: 'Development Staging Sandbox (Conflict C6)',
    yaml: `# Development Staging Sandbox Policy
version: "1.0.0"
name: "Development Guardrails (Conflict C6)"
description: "Stages system modifications for operator approval while allowing safe developer actions."

rules:
  - id: "dev_staging_packages"
    name: "System Package Staging"
    description: "Stages apt/yum/pip installs for operator review."
    match_type: "regex"
    pattern: "(?i)(?:apt-get|yum|pacman|pip)\s+install"
    action: "stage"
    risk_level: "high"
    reason: "Package installation modifies environment; operator confirmation required."
    suggestion: "Confirm package requirements and verify isolation."

  - id: "dev_root_rm_shield"
    name: "Filesystem Root Protection"
    description: "Blocks dangerous recursive deletes on system roots."
    match_type: "regex"
    pattern: "(?i)rm\s+-[a-zA-Z]*r[a-zA-Z]*f?\s+(?:/|/\*)"
    action: "block"
    risk_level: "critical"
    reason: "Root directory deletion causes irrecoverable system damage."
`,
  },
];

const PLAYGROUND_PRESETS = [
  {
    label: 'Root Deletion (Critical Block)',
    tool: 'bash:execute',
    args: { cmd: 'rm -rf /' },
  },
  {
    label: 'Drop Production DB (Critical Block)',
    tool: 'sql:execute',
    args: { query: 'DROP DATABASE prod_customers;' },
  },
  {
    label: 'Read Secret .env File (High Block)',
    tool: 'filesystem:read',
    args: { path: '/home/user/.env.production' },
  },
  {
    label: 'Git Force Push (High Block)',
    tool: 'git:push',
    args: { command: 'git push --force origin main' },
  },
  {
    label: 'Apt Package Install (High Stage)',
    tool: 'bash:execute',
    args: { cmd: 'sudo apt-get install nginx' },
  },
  {
    label: 'Safe Select Query (Allow)',
    tool: 'sql:execute',
    args: { query: 'SELECT count(*) FROM users WHERE active = 1;' },
  },
];

export const Policies: React.FC<PoliciesScreenProps> = () => {
  const [activeTab, setActiveTab] = useState<TabType>('queue');
  const [operations, setOperations] = useState<PendingOperation[]>([]);
  const [policies, setPolicies] = useState<SafetyPolicyRuleInfo[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(Date.now() / 1000);

  // Selection for batch actions (Queue Tab)
  const [selectedOpIds, setSelectedOpIds] = useState<string[]>([]);
  const [batchActionRunning, setBatchActionRunning] = useState<boolean>(false);

  // Rejection dialog state (Queue Tab)
  const [rejectDialogOpId, setRejectDialogOpId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState<string>('');

  // Editing parameters state (Queue Tab)
  const [editingOpId, setEditingOpId] = useState<string | null>(null);
  const [editParamsText, setEditParamsText] = useState<string>('');
  const [editParamsError, setEditParamsError] = useState<string | null>(null);

  // Filter states (Queue Tab)
  const [queueFilter, setQueueFilter] = useState<string>('all'); // all | pending | approved | rejected | expired
  const [searchQuery, setSearchQuery] = useState<string>('');

  // YAML Editor State (Editor Tab)
  const [yamlContent, setYamlContent] = useState<string>('');
  const [yamlSaving, setYamlSaving] = useState<boolean>(false);
  const [yamlStatusMessage, setYamlStatusMessage] = useState<string | null>(null);
  const [yamlErrorMessage, setYamlErrorMessage] = useState<string | null>(null);

  // Dry-Run Playground State (Playground Tab)
  const [dryRunTool, setDryRunTool] = useState<string>('bash:execute');
  const [dryRunArgsText, setDryRunArgsText] = useState<string>('{\n  "cmd": "rm -rf /"\n}');
  const [dryRunAllowHighRisk, setDryRunAllowHighRisk] = useState<boolean>(false);
  const [dryRunRunning, setDryRunRunning] = useState<boolean>(false);
  const [dryRunResult, setDryRunResult] = useState<DryRunResult | null>(null);
  const [dryRunError, setDryRunError] = useState<string | null>(null);

  // Audit Logs State (Audit Tab)
  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([]);
  const [auditTotal, setAuditTotal] = useState<number>(0);
  const [auditPage, setAuditPage] = useState<number>(1);
  const [auditPageSize, setAuditPageSize] = useState<number>(25);
  const [auditRiskFilter, setAuditRiskFilter] = useState<string>('all');
  const [auditDecisionFilter, setAuditDecisionFilter] = useState<string>('all');
  const [auditToolQuery, setAuditToolQuery] = useState<string>('');
  const [auditLoading, setAuditLoading] = useState<boolean>(false);
  const [expandedLogId, setExpandedLogId] = useState<number | null>(null);
  const [exportStatus, setExportStatus] = useState<string | null>(null);

  // Fetch queue & policy list
  const fetchData = async (showRefreshIndicator = false) => {
    if (showRefreshIndicator) setRefreshing(true);
    try {
      const [ops, pols] = await Promise.all([
        sidecarClient.listPendingOperations(),
        sidecarClient.listSafetyPolicies(),
      ]);
      setOperations(ops);
      setPolicies(pols);
    } catch (err) {
      console.error('Failed to fetch policies or operations', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  // Fetch YAML content for Editor
  const fetchYaml = async () => {
    try {
      const res = await sidecarClient.getPolicyYaml();
      setYamlContent(res.yaml_content);
    } catch (err) {
      console.error('Failed to fetch YAML', err);
    }
  };

  // Fetch Paginated Audit Logs
  const fetchAuditLogs = async () => {
    setAuditLoading(true);
    try {
      const offset = (auditPage - 1) * auditPageSize;
      const res = await sidecarClient.getSafetyAuditLogsPage({
        limit: auditPageSize,
        offset,
        riskLevel: auditRiskFilter,
        decision: auditDecisionFilter,
        toolName: auditToolQuery.trim() || undefined,
      });
      setAuditLogs(res.items);
      setAuditTotal(res.total);
    } catch (err) {
      console.error('Failed to fetch audit logs', err);
    } finally {
      setAuditLoading(false);
    }
  };

  // Initial load and periodic refresh for queue
  useEffect(() => {
    fetchData();
    fetchYaml();
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

  // Fetch audit logs when tab, page, or filters change
  useEffect(() => {
    if (activeTab === 'audit') {
      fetchAuditLogs();
    }
  }, [activeTab, auditPage, auditPageSize, auditRiskFilter, auditDecisionFilter, auditToolQuery]);

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

  // Batch Action
  const handleBatchAction = async (action: 'approve' | 'reject') => {
    if (selectedOpIds.length === 0) return;
    setBatchActionRunning(true);
    try {
      await sidecarClient.batchOperations(
        selectedOpIds,
        action,
        'operator',
        action === 'reject' ? 'Batch rejected by operator' : undefined
      );
      setSelectedOpIds([]);
      await fetchData();
    } catch (err: any) {
      alert(`Batch ${action} failed: ${err?.message || err}`);
    } finally {
      setBatchActionRunning(false);
    }
  };

  // Toggle selection for an operation
  const toggleSelectOp = (id: string) => {
    setSelectedOpIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  // Select all visible pending operations
  const selectAllPending = () => {
    const pendingIds = filteredOperations
      .filter((op) => op.status === 'pending' && op.expires_at > currentTime)
      .map((op) => op.operation_id);
    setSelectedOpIds(pendingIds);
  };

  // Handle Save YAML
  const handleSaveYaml = async () => {
    setYamlSaving(true);
    setYamlStatusMessage(null);
    setYamlErrorMessage(null);
    try {
      const res = await sidecarClient.updatePolicyYaml(yamlContent);
      setYamlStatusMessage(res.message || 'Policies updated and hot-reloaded successfully!');
      await fetchData(); // refresh active policy list
    } catch (err: any) {
      setYamlErrorMessage(err.message || 'Failed to save YAML policy');
    } finally {
      setYamlSaving(false);
    }
  };

  // Handle Preset Select for YAML
  const handleSelectPreset = (presetId: string) => {
    if (presetId === 'current') {
      fetchYaml();
      return;
    }
    const found = POLICY_PRESETS.find((p) => p.id === presetId);
    if (found && found.yaml) {
      setYamlContent(found.yaml);
      setYamlStatusMessage(`Loaded preset: ${found.name}`);
      setYamlErrorMessage(null);
    }
  };

  // Handle Dry Run Simulation
  const handleRunSimulation = async () => {
    setDryRunRunning(true);
    setDryRunError(null);
    setDryRunResult(null);
    try {
      let parsedArgs = {};
      if (dryRunArgsText.trim()) {
        try {
          parsedArgs = JSON.parse(dryRunArgsText);
        } catch {
          throw new Error('Arguments must be valid JSON.');
        }
      }
      const res = await sidecarClient.dryRunPolicy({
        tool_name: dryRunTool.trim(),
        tool_args: parsedArgs,
        context: { allow_high_risk: dryRunAllowHighRisk },
      });
      setDryRunResult(res);
    } catch (err: any) {
      setDryRunError(err.message || 'Simulation failed');
    } finally {
      setDryRunRunning(false);
    }
  };

  // Handle Export Audit Logs
  const handleExportAudit = async (format: 'csv' | 'json') => {
    setExportStatus(`Exporting ${format.toUpperCase()}...`);
    try {
      const result = await sidecarClient.exportSafetyAuditLogs(format, {
        riskLevel: auditRiskFilter,
        decision: auditDecisionFilter,
        toolName: auditToolQuery.trim() || undefined,
        limit: 1000,
      });

      const content = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
      const mimeType = format === 'csv' ? 'text/csv' : 'application/json';
      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `safety_audit_logs_${Date.now()}.${format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      setExportStatus(`Exported ${format.toUpperCase()} successfully!`);
      setTimeout(() => setExportStatus(null), 3000);
    } catch (err: any) {
      setExportStatus(`Export failed: ${err.message || err}`);
    }
  };

  // Render Tool Icon helper
  const renderToolIcon = (toolName: string) => {
    if (toolName.includes('bash') || toolName.includes('command')) {
      return <Terminal className="w-4 h-4 text-accent" />;
    }
    if (toolName.includes('sql') || toolName.includes('db')) {
      return <Database className="w-4 h-4 text-warning" />;
    }
    if (toolName.includes('file') || toolName.includes('write')) {
      return <FileCode className="w-4 h-4 text-success" />;
    }
    return <Cog className="w-4 h-4 text-text-tertiary" />;
  };

  // Render Risk Badge helper
  const renderRiskBadge = (level: RiskLevel, score: number) => {
    const pct = Math.round(score * 100);
    switch (level) {
      case 'critical':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-danger/20 text-danger border border-danger/40 flex items-center gap-1">
            <ShieldAlert className="w-3 h-3" /> Critical ({pct}%)
          </span>
        );
      case 'high':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-danger/15 text-danger border border-danger/30 flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" /> High ({pct}%)
          </span>
        );
      case 'medium':
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-warning/15 text-warning border border-warning/30 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" /> Medium ({pct}%)
          </span>
        );
      case 'low':
      default:
        return (
          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-success/15 text-success border border-success/30 flex items-center gap-1">
            <ShieldCheck className="w-3 h-3" /> Low ({pct}%)
          </span>
        );
    }
  };

  return (
    <div className="h-full flex flex-col bg-bg-base overflow-hidden select-none">
      {/* Top Header */}
      <div className="p-4 border-b border-border-subtle bg-bg-elevated/40 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-danger/15 border border-danger/30 flex items-center justify-center text-danger">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-text-primary">Policies & Approvals — Safety Control Center</h1>
              <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-danger/15 border border-danger/30 text-danger flex items-center gap-1">
                <ShieldCheck className="w-3 h-3" /> Zero-Trust Fail-Closed
              </span>
            </div>
            <p className="text-xs text-text-secondary mt-0.5">
              Live Approval Queue • YAML Policy Editor • Dry-Run Playground • Immutable Audit Log
            </p>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center bg-bg-base border border-border-subtle rounded-lg p-1 gap-1">
            <button
              onClick={() => setActiveTab('queue')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                activeTab === 'queue'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <Clock className="w-3.5 h-3.5" />
              Approval Queue
              {pendingCount > 0 && (
                <span className="px-1.5 py-0.2 rounded-full text-[10px] font-bold bg-danger text-white ml-1">
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
              onClick={() => setActiveTab('editor')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                activeTab === 'editor'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <Code2 className="w-3.5 h-3.5" />
              YAML Editor
            </button>
            <button
              onClick={() => setActiveTab('playground')}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                activeTab === 'playground'
                  ? 'bg-accent text-white shadow-sm'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <Play className="w-3.5 h-3.5" />
              Dry-Run Simulator
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
              Audit Trail ({auditTotal})
            </button>
          </div>

          <button
            onClick={() => {
              fetchData(true);
              if (activeTab === 'editor') fetchYaml();
              if (activeTab === 'audit') fetchAuditLogs();
            }}
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
        {/* Search & Filter Bar (Shown on Queue & Policies tabs) */}
        {(activeTab === 'queue' || activeTab === 'policies') && (
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
                      onClick={selectAllPending}
                      className="px-2.5 py-1.5 bg-bg-base hover:bg-bg-hover border border-border-subtle rounded-lg text-xs font-medium text-text-secondary transition-all"
                    >
                      Select All ({pendingCount})
                    </button>
                    {selectedOpIds.length > 0 && (
                      <>
                        <button
                          onClick={() => handleBatchAction('approve')}
                          disabled={batchActionRunning}
                          className="px-2.5 py-1.5 bg-success hover:bg-success-hover text-white rounded-lg text-xs font-semibold flex items-center gap-1 transition-all disabled:opacity-50"
                        >
                          <Check className="w-3.5 h-3.5" /> Approve ({selectedOpIds.length})
                        </button>
                        <button
                          onClick={() => handleBatchAction('reject')}
                          disabled={batchActionRunning}
                          className="px-2.5 py-1.5 bg-danger hover:bg-danger-hover text-white rounded-lg text-xs font-semibold flex items-center gap-1 transition-all disabled:opacity-50"
                        >
                          <X className="w-3.5 h-3.5" /> Reject ({selectedOpIds.length})
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* TAB 1: QUEUE */}
        {activeTab === 'queue' && (
          <div className="space-y-3">
            {loading ? (
              <div className="p-8 text-center text-text-tertiary">
                <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-accent" />
                Loading pending safety queue...
              </div>
            ) : filteredOperations.length === 0 ? (
              <div className="p-12 text-center bg-bg-elevated/20 rounded-2xl border border-dashed border-border-subtle flex flex-col items-center justify-center">
                <CheckCircle2 className="w-10 h-10 text-success mb-2 opacity-80" />
                <h3 className="text-sm font-bold text-text-primary">Safety Approval Queue Clean</h3>
                <p className="text-xs text-text-tertiary max-w-sm mt-1">
                  No high-risk operations currently pending manual authorization.
                </p>
              </div>
            ) : (
              filteredOperations.map((op) => {
                const isPending = op.status === 'pending' && op.expires_at > currentTime;
                const isExpired = op.status === 'expired' || (op.status === 'pending' && op.expires_at <= currentTime);
                const secondsLeft = Math.max(0, Math.floor(op.expires_at - currentTime));
                const isSelected = selectedOpIds.includes(op.operation_id);
                const isEditing = editingOpId === op.operation_id;

                return (
                  <div
                    key={op.operation_id}
                    className={`p-4 rounded-xl border transition-all ${
                      isPending
                        ? 'bg-bg-elevated border-accent/40 shadow-sm'
                        : isExpired
                        ? 'bg-bg-elevated/20 border-border-subtle opacity-60'
                        : op.status === 'approved' || op.status === 'consumed'
                        ? 'bg-success/5 border-success/30'
                        : 'bg-danger/5 border-danger/30'
                    } flex flex-col gap-3`}
                  >
                    {/* Operation Header */}
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        {isPending && (
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelectOp(op.operation_id)}
                            className="rounded border-border-subtle bg-bg-base text-accent focus:ring-0 w-4 h-4 cursor-pointer"
                          />
                        )}
                        <div className="p-1.5 rounded-lg bg-bg-base border border-border-subtle">
                          {renderToolIcon(op.tool_name)}
                        </div>
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-bold text-text-primary">
                              {op.tool_name}
                            </span>
                            <span className="text-[11px] font-mono text-text-tertiary">
                              #{op.operation_id}
                            </span>
                          </div>
                          <p className="text-xs text-text-secondary mt-0.5">
                            {op.reason || 'High-risk tool call requiring explicit human confirmation.'}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 flex-wrap sm:flex-nowrap">
                        {renderRiskBadge(op.risk_level, op.risk_score)}

                        {isPending && (
                          <div
                            className={`flex items-center gap-1 font-mono text-xs font-bold px-2 py-0.5 rounded border ${
                              secondsLeft <= 10
                                ? 'bg-danger/20 text-danger border-danger/40 animate-pulse'
                                : 'bg-warning/20 text-warning border-warning/40'
                            }`}
                          >
                            <Clock className="w-3 h-3" />
                            {secondsLeft}s
                          </div>
                        )}

                        {!isPending && (
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border ${
                              op.status === 'approved' || op.status === 'consumed'
                                ? 'bg-success/20 text-success border-success/40'
                                : isExpired
                                ? 'bg-bg-hover text-text-tertiary border-border-subtle'
                                : 'bg-danger/20 text-danger border-danger/40'
                            }`}
                          >
                            {op.status === 'consumed' ? 'consumed (executed)' : op.status}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Parameters View or Inline Editor */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-xs text-text-tertiary">
                        <span className="font-mono">SHA-256 Signature Binding:</span>
                        {isPending && !isEditing && (
                          <button
                            onClick={() => {
                              setEditingOpId(op.operation_id);
                              setEditParamsText(JSON.stringify(op.tool_args, null, 2));
                              setEditParamsError(null);
                            }}
                            className="text-accent hover:text-accent-hover flex items-center gap-1 font-medium"
                          >
                            <Edit3 className="w-3 h-3" /> Edit Arguments
                          </button>
                        )}
                      </div>
                      <div className="font-mono text-[11px] text-text-tertiary bg-bg-base/50 p-1.5 rounded border border-border-subtle truncate select-all">
                        {op.args_hash}
                      </div>

                      {/* Tool Arguments View or Editor */}
                      <div className="relative">
                        {isEditing ? (
                          <div className="space-y-2">
                            <textarea
                              value={editParamsText}
                              onChange={(e) => {
                                setEditParamsText(e.target.value);
                                setEditParamsError(null);
                              }}
                              rows={5}
                              className="w-full p-2.5 bg-bg-base border border-accent rounded-lg font-mono text-xs text-text-primary focus:outline-none"
                            />
                            {editParamsError && (
                              <p className="text-xs text-danger font-mono">{editParamsError}</p>
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
                                  } catch (err: any) {
                                    setEditParamsError(`Invalid JSON: ${err.message}`);
                                  }
                                }}
                                className="px-3 py-1 bg-accent hover:bg-accent-hover text-white rounded text-xs font-semibold"
                              >
                                Save & Authorize
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

        {/* TAB 3: YAML POLICY EDITOR */}
        {activeTab === 'editor' && (
          <div className="space-y-4">
            <div className="p-4 bg-bg-elevated/40 border border-border-subtle rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <Code2 className="w-5 h-5 text-accent" />
                <div>
                  <h2 className="text-sm font-bold text-text-primary">Declarative YAML Guardrail Editor</h2>
                  <p className="text-xs text-text-secondary">
                    Edit safety rules in YAML syntax. Hot-reloads across sidecar runtimes without server restart.
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <select
                  onChange={(e) => handleSelectPreset(e.target.value)}
                  className="bg-bg-base border border-border-subtle rounded-lg px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent"
                >
                  {POLICY_PRESETS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>

                <button
                  onClick={fetchYaml}
                  className="px-3 py-1.5 rounded-lg bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary transition-all"
                >
                  Reload
                </button>

                <button
                  onClick={handleSaveYaml}
                  disabled={yamlSaving}
                  className="px-4 py-1.5 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-bold flex items-center gap-1.5 shadow-sm transition-all disabled:opacity-50"
                >
                  <Save className="w-3.5 h-3.5" />
                  {yamlSaving ? 'Validating & Saving...' : 'Save & Hot-Reload'}
                </button>
              </div>
            </div>

            {yamlStatusMessage && (
              <div className="p-3 rounded-lg bg-success/10 border border-success/30 text-success text-xs flex items-center gap-2 animate-in fade-in">
                <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
                <span>{yamlStatusMessage}</span>
              </div>
            )}

            {yamlErrorMessage && (
              <div className="p-3 rounded-lg bg-danger/10 border border-danger/30 text-danger text-xs flex items-center gap-2 animate-in fade-in">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                <span className="font-mono">{yamlErrorMessage}</span>
              </div>
            )}

            <div className="relative rounded-xl border border-border-subtle overflow-hidden bg-[#0d0d0d]">
              <div className="flex items-center justify-between px-4 py-2 bg-bg-base/80 border-b border-border-subtle text-[11px] font-mono text-text-tertiary">
                <span>policies/default.yaml</span>
                <span>{yamlContent.split('\n').length} lines</span>
              </div>
              <textarea
                value={yamlContent}
                onChange={(e) => setYamlContent(e.target.value)}
                rows={22}
                spellCheck={false}
                className="w-full p-4 bg-transparent font-mono text-xs text-text-primary leading-relaxed focus:outline-none resize-y selection:bg-accent/30"
              />
            </div>
          </div>
        )}

        {/* TAB 4: DRY-RUN SIMULATOR */}
        {activeTab === 'playground' && (
          <div className="space-y-4">
            <div className="p-4 bg-bg-elevated/40 border border-border-subtle rounded-xl flex items-center justify-between">
              <div>
                <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                  <Play className="w-4 h-4 text-accent" /> Rule Dry-Run Playground
                </h2>
                <p className="text-xs text-text-secondary mt-0.5">
                  Simulate prospective tool calls against active policies without executing or logging to audit trail.
                </p>
              </div>
              <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-accent/15 border border-accent/30 text-accent">
                Safe Simulator
              </span>
            </div>

            {/* Quick Preset Buttons */}
            <div className="flex items-center gap-2 overflow-x-auto pb-1">
              <span className="text-xs text-text-tertiary font-mono whitespace-nowrap">Presets:</span>
              {PLAYGROUND_PRESETS.map((preset, idx) => (
                <button
                  key={idx}
                  onClick={() => {
                    setDryRunTool(preset.tool);
                    setDryRunArgsText(JSON.stringify(preset.args, null, 2));
                    setDryRunResult(null);
                    setDryRunError(null);
                  }}
                  className="px-2.5 py-1 rounded-lg bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary hover:text-text-primary whitespace-nowrap transition-all"
                >
                  {preset.label}
                </button>
              ))}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Simulator Input Column */}
              <div className="p-4 bg-bg-elevated/40 border border-border-subtle rounded-xl space-y-3">
                <h3 className="text-xs font-bold text-text-primary font-mono uppercase tracking-wider">
                  Test Tool Call Parameters
                </h3>

                <div>
                  <label className="text-xs text-text-tertiary block mb-1 font-mono">Tool Name:</label>
                  <input
                    type="text"
                    value={dryRunTool}
                    onChange={(e) => setDryRunTool(e.target.value)}
                    placeholder="e.g., bash:execute, sql:execute"
                    className="w-full px-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs font-mono text-text-primary focus:outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="text-xs text-text-tertiary block mb-1 font-mono">Tool Arguments (JSON):</label>
                  <textarea
                    value={dryRunArgsText}
                    onChange={(e) => setDryRunArgsText(e.target.value)}
                    rows={7}
                    spellCheck={false}
                    className="w-full p-2.5 bg-bg-base border border-border-subtle rounded-lg text-xs font-mono text-text-primary focus:outline-none focus:border-accent"
                  />
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    id="dryRunHighRisk"
                    checked={dryRunAllowHighRisk}
                    onChange={(e) => setDryRunAllowHighRisk(e.target.checked)}
                    className="rounded border-border-subtle bg-bg-base text-accent w-4 h-4 cursor-pointer"
                  />
                  <label htmlFor="dryRunHighRisk" className="text-xs text-text-secondary cursor-pointer">
                    Simulate with <span className="font-mono">allow_high_risk: true</span> context
                  </label>
                </div>

                <button
                  onClick={handleRunSimulation}
                  disabled={dryRunRunning}
                  className="w-full py-2 bg-accent hover:bg-accent-hover text-white text-xs font-bold rounded-lg flex items-center justify-center gap-2 shadow-sm transition-all disabled:opacity-50"
                >
                  <Play className="w-3.5 h-3.5" />
                  {dryRunRunning ? 'Evaluating Guardrails...' : 'Run Simulation'}
                </button>

                {dryRunError && (
                  <p className="text-xs text-danger font-mono bg-danger/10 p-2 rounded border border-danger/20">
                    {dryRunError}
                  </p>
                )}
              </div>

              {/* Simulation Result Column */}
              <div className="p-4 bg-bg-elevated/40 border border-border-subtle rounded-xl flex flex-col justify-between space-y-3">
                <h3 className="text-xs font-bold text-text-primary font-mono uppercase tracking-wider">
                  Simulation Outcome
                </h3>

                {!dryRunResult ? (
                  <div className="h-56 flex flex-col items-center justify-center text-center text-text-tertiary">
                    <Sliders className="w-8 h-8 opacity-40 mb-2" />
                    <p className="text-xs">Select a preset or enter tool arguments to evaluate.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {/* Final Decision Card */}
                    <div
                      className={`p-3 rounded-xl border flex items-center justify-between ${
                        dryRunResult.decision === 'block'
                          ? 'bg-danger/15 border-danger/40 text-danger'
                          : dryRunResult.decision === 'stage'
                          ? 'bg-warning/15 border-warning/40 text-warning'
                          : 'bg-success/15 border-success/40 text-success'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {dryRunResult.decision === 'block' ? (
                          <XCircle className="w-5 h-5" />
                        ) : dryRunResult.decision === 'stage' ? (
                          <AlertTriangle className="w-5 h-5" />
                        ) : (
                          <CheckCircle2 className="w-5 h-5" />
                        )}
                        <div>
                          <span className="font-mono text-sm font-bold uppercase">
                            Decision: {dryRunResult.decision}
                          </span>
                          <p className="text-[11px] text-text-secondary mt-0.5">
                            {dryRunResult.reason || 'No violation detected.'}
                          </p>
                        </div>
                      </div>

                      <span className="font-mono text-xs font-bold px-2 py-1 bg-bg-base/70 rounded border border-border-subtle">
                        Risk: {Math.round(dryRunResult.risk_score * 100)}% ({dryRunResult.risk_level})
                      </span>
                    </div>

                    {/* Violating Rules Breakdown */}
                    {dryRunResult.violating_rules.length > 0 && (
                      <div className="space-y-2">
                        <span className="text-xs font-mono font-bold text-text-secondary">
                          Matched Guardrail Rules ({dryRunResult.violating_rules.length}):
                        </span>
                        {dryRunResult.violating_rules.map((rule) => (
                          <div
                            key={rule.id}
                            className="p-2.5 bg-bg-base/60 border border-border-subtle rounded-lg text-xs space-y-1"
                          >
                            <div className="flex items-center justify-between font-mono font-bold text-text-primary">
                              <span>{rule.name}</span>
                              <span className="text-danger uppercase text-[10px]">{rule.action}</span>
                            </div>
                            <div className="text-[11px] text-text-secondary font-mono">
                              Pattern: {rule.pattern}
                            </div>
                            {rule.reason && (
                              <p className="text-text-tertiary text-[11px]">{rule.reason}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Remediation Suggestion */}
                    {dryRunResult.suggestion && (
                      <div className="p-2.5 bg-accent/10 border border-accent/20 rounded-lg text-xs text-accent">
                        <span className="font-bold">Safe Alternative / Remediation: </span>
                        {dryRunResult.suggestion}
                      </div>
                    )}
                  </div>
                )}

                <div className="pt-2 border-t border-border-subtle text-[11px] text-text-tertiary font-mono">
                  Dry-run engine: simulated against in-memory rule table (0 audit footprint).
                </div>
              </div>
            </div>
          </div>
        )}

        {/* TAB 5: IMMUTABLE AUDIT LOG */}
        {activeTab === 'audit' && (
          <div className="space-y-3">
            {/* Audit Filter & Export Controls */}
            <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-bg-elevated/40 p-3 rounded-xl border border-border-subtle">
              <div className="flex items-center gap-2 flex-1 w-full sm:w-auto flex-wrap sm:flex-nowrap">
                <input
                  type="text"
                  placeholder="Filter by tool name..."
                  value={auditToolQuery}
                  onChange={(e) => {
                    setAuditToolQuery(e.target.value);
                    setAuditPage(1);
                  }}
                  className="px-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary font-mono focus:outline-none focus:border-accent w-44"
                />

                <select
                  value={auditRiskFilter}
                  onChange={(e) => {
                    setAuditRiskFilter(e.target.value);
                    setAuditPage(1);
                  }}
                  className="bg-bg-base border border-border-subtle rounded-lg px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent"
                >
                  <option value="all">All Risk Levels</option>
                  <option value="critical">Critical Only</option>
                  <option value="high">High Only</option>
                  <option value="medium">Medium Only</option>
                  <option value="low">Low Only</option>
                </select>

                <select
                  value={auditDecisionFilter}
                  onChange={(e) => {
                    setAuditDecisionFilter(e.target.value);
                    setAuditPage(1);
                  }}
                  className="bg-bg-base border border-border-subtle rounded-lg px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent"
                >
                  <option value="all">All Decisions</option>
                  <option value="allow">Allow / Approved</option>
                  <option value="block">Block / Denied</option>
                  <option value="stage">Staged</option>
                </select>
              </div>

              <div className="flex items-center gap-2">
                {exportStatus && (
                  <span className="text-xs text-accent font-medium animate-in fade-in">
                    {exportStatus}
                  </span>
                )}
                <button
                  onClick={() => handleExportAudit('csv')}
                  className="px-2.5 py-1.5 rounded-lg bg-bg-base hover:bg-bg-hover border border-border-subtle text-text-secondary hover:text-text-primary text-xs font-medium flex items-center gap-1.5 transition-all"
                  title="Export CSV"
                >
                  <Download className="w-3.5 h-3.5" /> Export CSV
                </button>
                <button
                  onClick={() => handleExportAudit('json')}
                  className="px-2.5 py-1.5 rounded-lg bg-bg-base hover:bg-bg-hover border border-border-subtle text-text-secondary hover:text-text-primary text-xs font-medium flex items-center gap-1.5 transition-all"
                  title="Export JSON"
                >
                  <Download className="w-3.5 h-3.5" /> Export JSON
                </button>
              </div>
            </div>

            {/* Audit Log Table */}
            <div className="bg-bg-elevated/40 border border-border-subtle rounded-xl overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-bg-base/80 border-b border-border-subtle text-text-tertiary font-mono uppercase tracking-wider">
                    <tr>
                      <th className="p-3 w-12">#</th>
                      <th className="p-3">Timestamp</th>
                      <th className="p-3">Tool Name</th>
                      <th className="p-3">Decision</th>
                      <th className="p-3">Risk Level</th>
                      <th className="p-3">Policy / Reason</th>
                      <th className="p-3 text-right">Details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-subtle/50 font-mono">
                    {auditLoading ? (
                      <tr>
                        <td colSpan={7} className="p-8 text-center text-text-tertiary font-sans">
                          <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2 text-accent" />
                          Loading audit records...
                        </td>
                      </tr>
                    ) : auditLogs.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="p-8 text-center text-text-tertiary font-sans">
                          No audit log records found matching query criteria.
                        </td>
                      </tr>
                    ) : (
                      auditLogs.map((log) => {
                        const isDeny = log.decision.includes('block') || log.decision.includes('deny') || log.decision.includes('reject');
                        const isApprove = log.decision.includes('approve') || log.decision.includes('allow');
                        const isExpanded = expandedLogId === log.id;

                        return (
                          <React.Fragment key={log.id}>
                            <tr
                              onClick={() => setExpandedLogId(isExpanded ? null : log.id)}
                              className="hover:bg-bg-hover/50 transition-colors cursor-pointer"
                            >
                              <td className="p-3 text-text-tertiary">{log.id}</td>
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
                                  {Math.round(log.risk_score * 100)}% ({log.risk_level})
                                </span>
                              </td>
                              <td className="p-3 font-sans text-text-secondary max-w-xs truncate">
                                {log.reason || log.policy_id || '—'}
                              </td>
                              <td className="p-3 text-right">
                                {isExpanded ? (
                                  <ChevronUp className="w-4 h-4 inline text-text-tertiary" />
                                ) : (
                                  <ChevronDown className="w-4 h-4 inline text-text-tertiary" />
                                )}
                              </td>
                            </tr>

                            {/* Expanded Record View */}
                            {isExpanded && (
                              <tr className="bg-bg-base/80">
                                <td colSpan={7} className="p-4 space-y-3 font-sans">
                                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                                    <div>
                                      <span className="font-bold text-text-tertiary font-mono block mb-1">
                                        Parsed Tool Arguments:
                                      </span>
                                      <pre className="p-2.5 bg-bg-elevated rounded border border-border-subtle font-mono text-[11px] text-text-secondary overflow-x-auto max-h-40">
                                        {JSON.stringify(log.tool_args, null, 2)}
                                      </pre>
                                    </div>
                                    <div className="space-y-2">
                                      <div>
                                        <span className="font-bold text-text-tertiary font-mono block">
                                          Enforcement Reason:
                                        </span>
                                        <p className="text-text-secondary mt-0.5">{log.reason || '—'}</p>
                                      </div>
                                      {log.suggestion && (
                                        <div>
                                          <span className="font-bold text-accent font-mono block">
                                            Remediation Suggestion:
                                          </span>
                                          <p className="text-text-secondary mt-0.5">{log.suggestion}</p>
                                        </div>
                                      )}
                                      {log.session_id && (
                                        <div className="text-[11px] text-text-tertiary font-mono">
                                          Session ID: {log.session_id}
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination Footer */}
              <div className="p-3 border-t border-border-subtle bg-bg-base/60 flex items-center justify-between text-xs text-text-tertiary">
                <div className="flex items-center gap-2">
                  <span>Page size:</span>
                  <select
                    value={auditPageSize}
                    onChange={(e) => {
                      setAuditPageSize(Number(e.target.value));
                      setAuditPage(1);
                    }}
                    className="bg-bg-base border border-border-subtle rounded-lg px-2 py-1 text-text-primary focus:outline-none focus:border-accent"
                  >
                    <option value={10}>10</option>
                    <option value={25}>25</option>
                    <option value={50}>50</option>
                    <option value={100}>100</option>
                  </select>
                  <span>
                    Showing {Math.min(auditTotal, (auditPage - 1) * auditPageSize + 1)} to{' '}
                    {Math.min(auditTotal, auditPage * auditPageSize)} of {auditTotal} entries
                  </span>
                </div>

                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setAuditPage((p) => Math.max(1, p - 1))}
                    disabled={auditPage <= 1}
                    className="p-1.5 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle disabled:opacity-30"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <span className="px-2 font-mono text-text-secondary">
                    {auditPage} / {Math.max(1, Math.ceil(auditTotal / auditPageSize))}
                  </span>
                  <button
                    onClick={() => setAuditPage((p) => p + 1)}
                    disabled={auditPage >= Math.ceil(auditTotal / auditPageSize)}
                    className="p-1.5 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle disabled:opacity-30"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
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
