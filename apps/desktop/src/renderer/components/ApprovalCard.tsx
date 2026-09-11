import React, { useState } from 'react';
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  AlertCircle,
  Check,
  X,
  Edit3,
  Terminal,
  FileCode,
  Database,
  Cog,
  Clock,
  Coins,
  CheckCircle2,
  XCircle,
} from 'lucide-react';
import { ApprovalRequest, RiskLevel, ToolCallDiff, DiffLine } from '../types';

export interface ApprovalCardProps {
  request: ApprovalRequest;
  onApprove: (id: string) => Promise<void> | void;
  onReject: (id: string, reason?: string) => Promise<void> | void;
  onEdit: (id: string, modifiedArgs: Record<string, any>) => Promise<void> | void;
  readOnly?: boolean;
  className?: string;
}

export const ApprovalCard: React.FC<ApprovalCardProps> = ({
  request,
  onApprove,
  onReject,
  onEdit,
  readOnly = false,
  className = '',
}) => {
  const [isEditing, setIsEditing] = useState(false);
  const [isRejecting, setIsRejecting] = useState(false);
  const [rejectReason, setRejectReason] = useState('');
  const [isResolving, setIsResolving] = useState(false);
  const [activeTab, setActiveTab] = useState<'diff' | 'raw'>('diff');
  const [rawArgsText, setRawArgsText] = useState(() =>
    JSON.stringify(request.toolArgs, null, 2)
  );

  // Parse risk configuration
  const getRiskBadge = (level: RiskLevel, score: number) => {
    switch (level) {
      case 'critical':
        return {
          icon: <ShieldAlert className="w-3.5 h-3.5 text-danger" />,
          label: 'Critical Risk',
          scoreText: `${Math.round(score * 100)}%`,
          badgeClass: 'bg-danger/15 border-danger/30 text-danger',
          borderClass: 'border-danger/40',
        };
      case 'high':
        return {
          icon: <AlertTriangle className="w-3.5 h-3.5 text-warning" />,
          label: 'High Risk',
          scoreText: `${Math.round(score * 100)}%`,
          badgeClass: 'bg-warning/15 border-warning/30 text-warning',
          borderClass: 'border-warning/40',
        };
      case 'medium':
        return {
          icon: <AlertCircle className="w-3.5 h-3.5 text-amber-400" />,
          label: 'Medium Risk',
          scoreText: `${Math.round(score * 100)}%`,
          badgeClass: 'bg-amber-400/15 border-amber-400/30 text-amber-400',
          borderClass: 'border-amber-400/30',
        };
      case 'low':
      default:
        return {
          icon: <ShieldCheck className="w-3.5 h-3.5 text-success" />,
          label: 'Low Risk',
          scoreText: `${Math.round(score * 100)}%`,
          badgeClass: 'bg-success/15 border-success/30 text-success',
          borderClass: 'border-success/30',
        };
    }
  };

  // Get tool icon
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

  const riskInfo = getRiskBadge(request.riskLevel, request.riskScore);
  const isPending = request.status === 'pending';
  const isApproved = request.status === 'approved';
  const isRejected = request.status === 'rejected';
  const isEdited = request.status === 'edited';

  const handleApproveClick = async () => {
    if (isResolving) return;
    setIsResolving(true);
    try {
      await onApprove(request.id);
    } finally {
      setIsResolving(false);
    }
  };

  const handleRejectConfirm = async () => {
    if (isResolving) return;
    setIsResolving(true);
    try {
      await onReject(request.id, rejectReason.trim() || 'Rejected by operator');
      setIsRejecting(false);
    } finally {
      setIsResolving(false);
    }
  };

  const handleSaveEdit = async () => {
    if (isResolving) return;
    try {
      const parsed = JSON.parse(rawArgsText);
      setIsResolving(true);
      await onEdit(request.id, parsed);
      setIsEditing(false);
    } catch {
      alert('Invalid JSON in modified tool arguments.');
    } finally {
      setIsResolving(false);
    }
  };

  // Render Diff Preview
  const renderDiffViewer = (diff?: ToolCallDiff) => {
    if (!diff) {
      return (
        <div className="p-3 bg-bg-base/60 rounded border border-border-subtle font-mono text-xs text-text-secondary overflow-x-auto">
          <pre>{JSON.stringify(request.toolArgs, null, 2)}</pre>
        </div>
      );
    }

    if (diff.type === 'command') {
      return (
        <div className="space-y-2">
          <div className="p-3 bg-black/50 border border-border-subtle rounded-lg font-mono text-xs text-text-primary overflow-x-auto flex items-start gap-2">
            <span className="text-accent select-none font-bold">$</span>
            <span className="text-emerald-400 break-all">{diff.target}</span>
          </div>
          {diff.contextInfo && (
            <div className="flex flex-wrap gap-2 text-[11px] font-mono text-text-tertiary">
              {diff.contextInfo.cwd && (
                <span className="px-2 py-0.5 rounded bg-bg-base border border-border-subtle">
                  cwd: {diff.contextInfo.cwd}
                </span>
              )}
              {diff.contextInfo.user && (
                <span className="px-2 py-0.5 rounded bg-bg-base border border-border-subtle">
                  user: {diff.contextInfo.user}
                </span>
              )}
            </div>
          )}
        </div>
      );
    }

    if (diff.type === 'file' && diff.diffLines && diff.diffLines.length > 0) {
      return (
        <div className="rounded-lg overflow-hidden border border-border-subtle font-mono text-xs">
          {/* Target filename header */}
          <div className="px-3 py-1.5 bg-bg-base border-b border-border-subtle flex items-center justify-between text-[11px] text-text-secondary">
            <span className="font-semibold text-text-primary">{diff.target}</span>
            <span className="text-text-tertiary">
              {diff.diffLines.filter((l) => l.type === 'add').length} additions,{' '}
              {diff.diffLines.filter((l) => l.type === 'remove').length} deletions
            </span>
          </div>
          {/* Diff lines */}
          <div className="p-2 bg-black/40 overflow-x-auto max-h-64 scrollbar-thin">
            {diff.diffLines.map((line: DiffLine, idx: number) => {
              let bg = '';
              let textColor = 'text-text-secondary';
              let prefix = ' ';

              if (line.type === 'add') {
                bg = 'bg-success/10';
                textColor = 'text-success font-medium';
                prefix = '+';
              } else if (line.type === 'remove') {
                bg = 'bg-danger/10';
                textColor = 'text-danger line-through';
                prefix = '-';
              }

              return (
                <div
                  key={idx}
                  className={`flex items-start px-2 py-0.5 rounded ${bg} leading-relaxed`}
                >
                  <span className="w-4 select-none opacity-60 font-bold">{prefix}</span>
                  {line.lineNumber && (
                    <span className="w-8 select-none text-text-tertiary text-right pr-2">
                      {line.lineNumber}
                    </span>
                  )}
                  <span className={`${textColor} whitespace-pre-wrap break-all flex-1`}>
                    {line.text}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      );
    }

    if (diff.type === 'sql') {
      return (
        <div className="space-y-1.5">
          <div className="p-3 bg-black/50 border border-border-subtle rounded-lg font-mono text-xs text-text-primary overflow-x-auto">
            <span className="text-amber-400 font-semibold uppercase block mb-1">
              -- Target: {diff.target}
            </span>
            <pre className="text-emerald-300 leading-relaxed whitespace-pre-wrap">
              {diff.proposed || diff.target}
            </pre>
          </div>
        </div>
      );
    }

    // Generic diff
    return (
      <div className="p-3 bg-bg-base/60 rounded border border-border-subtle font-mono text-xs text-text-secondary overflow-x-auto">
        <pre>{JSON.stringify(request.toolArgs, null, 2)}</pre>
      </div>
    );
  };

  return (
    <div
      className={`w-full rounded-xl border bg-bg-elevated text-left shadow-lg overflow-hidden transition-all ${riskInfo.borderClass} ${className}`}
      data-testid="approval-card"
    >
      {/* Top Header Strip */}
      <div className="px-4 py-3 border-b border-border-subtle/80 flex items-center justify-between bg-bg-elevated/90 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-bg-base border border-border-strong flex items-center justify-center flex-shrink-0">
            {getToolIcon(request.toolName)}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-xs text-text-primary font-mono">
                {request.toolName}
              </span>
              <span
                className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider border ${riskInfo.badgeClass}`}
              >
                {riskInfo.icon}
                <span>{riskInfo.label}</span>
                <span className="font-mono">({riskInfo.scoreText})</span>
              </span>
            </div>
            <div className="text-[11px] text-text-tertiary flex items-center gap-2 mt-0.5">
              <span>Gate: Law 1 & Policy Shield</span>
              <span>•</span>
              <span className="flex items-center gap-0.5">
                <Clock className="w-3 h-3" />
                {request.createdAt}
              </span>
            </div>
          </div>
        </div>

        {/* Status Indicator Badge */}
        <div className="flex items-center gap-2">
          {isApproved && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-success/15 border border-success/30 text-success text-xs font-semibold">
              <CheckCircle2 className="w-3.5 h-3.5" />
              <span>Approved</span>
            </span>
          )}
          {isRejected && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-danger/15 border border-danger/30 text-danger text-xs font-semibold">
              <XCircle className="w-3.5 h-3.5" />
              <span>Rejected</span>
            </span>
          )}
          {isEdited && (
            <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-warning/15 border border-warning/30 text-warning text-xs font-semibold">
              <Edit3 className="w-3.5 h-3.5" />
              <span>Approved with Edits</span>
            </span>
          )}
          {isPending && (
            <span className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-warning/10 border border-warning/20 text-warning text-[11px] font-medium animate-pulse">
              <span>Awaiting Decision</span>
            </span>
          )}
        </div>
      </div>

      {/* Card Body */}
      <div className="p-4 space-y-3">
        {/* Reason / Policy statement */}
        <div className="text-xs text-text-secondary leading-relaxed bg-bg-base/40 p-2.5 rounded-lg border border-border-subtle/60">
          <p className="font-medium text-text-primary mb-1">
            Explicit Confirmation Required
          </p>
          <p>{request.reason}</p>
          {request.suggestion && (
            <div className="mt-2 text-[11px] text-text-tertiary">
              <strong className="text-accent">Safe Alternative:</strong>{' '}
              <code className="px-1 py-0.5 rounded bg-bg-base font-mono text-text-secondary">
                {request.suggestion}
              </code>
            </div>
          )}
        </div>

        {/* Tab Selector & Header */}
        <div className="flex items-center justify-between border-b border-border-subtle pb-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setActiveTab('diff')}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                activeTab === 'diff'
                  ? 'bg-accent/15 text-accent border border-accent/30'
                  : 'text-text-tertiary hover:text-text-secondary'
              }`}
            >
              Diff Preview
            </button>
            <button
              type="button"
              onClick={() => setActiveTab('raw')}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                activeTab === 'raw'
                  ? 'bg-accent/15 text-accent border border-accent/30'
                  : 'text-text-tertiary hover:text-text-secondary'
              }`}
            >
              Payload Arguments
            </button>
          </div>

          {/* Cost Delta Estimate */}
          {request.estCostDelta && (
            <div className="flex items-center gap-1 text-[11px] font-mono text-text-tertiary">
              <Coins className="w-3.5 h-3.5 text-success" />
              <span>Cost Delta:</span>
              <span className="text-success font-semibold">{request.estCostDelta}</span>
            </div>
          )}
        </div>

        {/* Content Viewer / Inline Editor */}
        {isEditing ? (
          /* Inline JSON argument editor */
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-text-secondary">
              <span className="font-semibold">Edit Tool Arguments (JSON):</span>
              <span className="text-[10px] text-text-tertiary">
                Modify parameters safely before execution
              </span>
            </div>
            <textarea
              value={rawArgsText}
              onChange={(e) => setRawArgsText(e.target.value)}
              rows={6}
              className="w-full p-2.5 bg-black/60 border border-accent/50 focus:border-accent rounded-lg font-mono text-xs text-text-primary outline-none scrollbar-thin resize-y"
            />
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setIsEditing(false)}
                className="px-3 py-1.5 rounded-lg border border-border-strong text-text-secondary hover:text-text-primary text-xs transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveEdit}
                disabled={isResolving}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent hover:bg-accent/90 text-white font-medium text-xs shadow-md transition-colors"
              >
                <Check className="w-3.5 h-3.5" />
                <span>Approve with Edits</span>
              </button>
            </div>
          </div>
        ) : isRejecting ? (
          /* Rejection reason form */
          <div className="space-y-2 bg-danger/5 border border-danger/20 p-3 rounded-lg">
            <span className="text-xs font-semibold text-danger block">
              Provide Rejection Reason:
            </span>
            <input
              type="text"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="e.g. Unverified target environment, potential data loss"
              className="w-full px-3 py-1.5 rounded bg-bg-base border border-danger/30 text-xs text-text-primary outline-none focus:border-danger"
            />
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                onClick={() => setIsRejecting(false)}
                className="px-3 py-1 rounded text-xs text-text-secondary hover:text-text-primary"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRejectConfirm}
                disabled={isResolving}
                className="flex items-center gap-1 px-3 py-1 rounded bg-danger hover:bg-danger/90 text-white text-xs font-semibold"
              >
                <X className="w-3.5 h-3.5" />
                <span>Confirm Rejection</span>
              </button>
            </div>
          </div>
        ) : (
          /* View Mode: Diff or Raw Payload */
          <div>
            {activeTab === 'diff' ? (
              renderDiffViewer(request.diff)
            ) : (
              <div className="p-3 bg-bg-base/60 rounded border border-border-subtle font-mono text-xs text-text-secondary overflow-x-auto max-h-56 scrollbar-thin">
                <pre>{JSON.stringify(request.modifiedArgs || request.toolArgs, null, 2)}</pre>
              </div>
            )}
          </div>
        )}

        {/* Decision Resolved Footer */}
        {!isPending && (
          <div className="pt-2 border-t border-border-subtle/60 flex items-center justify-between text-[11px] text-text-tertiary">
            <div className="flex items-center gap-2">
              <span>Decision logged to audit ledger</span>
              {request.auditId && (
                <span className="font-mono text-accent">#aud-{request.auditId}</span>
              )}
            </div>
            {request.resolvedAt && (
              <span>Resolved: {request.resolvedAt}</span>
            )}
          </div>
        )}

        {/* Action Button Trio (Pending only) */}
        {isPending && !readOnly && !isEditing && !isRejecting && (
          <div className="pt-2 border-t border-border-subtle flex items-center justify-between flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setIsEditing(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border-strong hover:border-text-secondary text-text-secondary hover:text-text-primary text-xs font-medium transition-colors"
              title="Edit parameters before approval"
            >
              <Edit3 className="w-3.5 h-3.5 text-text-tertiary" />
              <span>Edit Payload</span>
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setIsRejecting(true)}
                disabled={isResolving}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg border border-danger/40 hover:bg-danger/10 text-danger text-xs font-semibold transition-colors"
                title="Reject tool execution"
              >
                <X className="w-3.5 h-3.5" />
                <span>Reject</span>
              </button>

              <button
                type="button"
                onClick={handleApproveClick}
                disabled={isResolving}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-md shadow-emerald-950/40 transition-all hover:scale-[1.02] active:scale-[0.98]"
                title="Approve and execute immediately (<500ms)"
              >
                {isResolving ? (
                  <span className="inline-block w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                ) : (
                  <Check className="w-3.5 h-3.5" />
                )}
                <span>Approve & Execute</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
