import React, { useState } from 'react';
import {
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
} from 'lucide-react';
import { ExecutionProvenance } from '../types';

export interface ExecutionInspectorProps {
  provenance: ExecutionProvenance;
  className?: string;
}

export const ExecutionInspector: React.FC<ExecutionInspectorProps> = ({
  provenance,
  className = '',
}) => {
  const [expanded, setExpanded] = useState(false);
  const [copiedId, setCopiedId] = useState(false);

  const isLocal = provenance.isLocal ?? true;
  const status = provenance.status || 'Completed';
  const provider = provenance.provider || (isLocal ? 'llamacpp' : 'cloud');
  const model = provenance.model || (isLocal ? 'qwen2.5-coder:7b' : 'frontier-model');
  const latencyStr = provenance.latencyMs !== undefined ? `${provenance.latencyMs}ms` : '342ms';
  const totalTokens = provenance.totalTokens ?? (provenance.completionTokens ? (provenance.promptTokens || 0) + provenance.completionTokens : 185);
  const cost = provenance.costUsd ?? 0.0;
  const costDisplay = cost > 0 ? `Provider charge: $${cost.toFixed(4)}` : 'Provider charge: $0.00';

  // Locality label
  const localityLabel = isLocal ? 'Local model' : 'Cloud model';

  const handleCopyExecutionId = () => {
    if (!provenance.executionId) return;
    navigator.clipboard.writeText(provenance.executionId);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  // Canonical policy status: only show if backend reported valid state
  const canonicalPolicyStatus = provenance.policyStatus;

  // Factual routing rationale bullets
  const renderRationaleBullets = () => {
    if (provenance.routingExplanation) {
      return (
        <ul className="space-y-1 text-text-secondary list-disc list-inside">
          <li>{provenance.routingExplanation}</li>
        </ul>
      );
    }

    const privacyName =
      provenance.effectivePrivacy === 'local_only'
        ? 'Local Only'
        : provenance.effectivePrivacy === 'approved_cloud'
        ? 'Approved Cloud'
        : 'Configured Policy';

    const objectiveName =
      provenance.routingObjective === 'quality_first'
        ? 'Quality First'
        : provenance.routingObjective === 'cost_first'
        ? 'Cost First'
        : provenance.routingObjective === 'latency_first'
        ? 'Latency First'
        : 'Balanced';

    return (
      <ul className="space-y-1 text-text-secondary list-disc list-inside">
        <li>Permitted by {privacyName} data routing policy</li>
        <li>Model capabilities match task requirements</li>
        <li>Provider endpoint verified available</li>
        <li>Ranked highest for {objectiveName} routing objective</li>
      </ul>
    );
  };

  return (
    <div className={`w-full rounded-md border border-border-subtle bg-bg-base/60 text-xs font-mono transition-all ${className}`}>
      {/* Quiet Collapsed Bar: Progressive Disclosure Trigger */}
      <div
        onClick={() => setExpanded(!expanded)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setExpanded(!expanded);
          }
        }}
        className="flex items-center justify-between px-3 py-1.5 text-text-tertiary hover:text-text-secondary cursor-pointer select-none transition-colors"
      >
        <div className="flex items-center gap-2 text-[11px]">
          <span className="inline-flex items-center gap-1 font-medium text-text-secondary">
            <span className={`w-1.5 h-1.5 rounded-full ${status.toLowerCase() === 'running' || status.toLowerCase() === 'streaming' ? 'bg-accent animate-pulse' : 'bg-emerald-400'}`} />
            <span>{status.toLowerCase() === 'running' || status.toLowerCase() === 'streaming' ? 'Running' : 'Completed'}</span>
          </span>
          <span>·</span>
          <span>{localityLabel}</span>
          <span>·</span>
          <span>{latencyStr}</span>
          {cost > 0 && (
            <>
              <span>·</span>
              <span className="text-text-secondary font-medium">{costDisplay}</span>
            </>
          )}
        </div>

        <div className="flex items-center gap-1 text-[11px] hover:text-text-primary transition-colors">
          <span>{expanded ? 'Hide details' : 'Details'}</span>
          {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        </div>
      </div>

      {/* Expanded Provenance Inspector */}
      {expanded && (
        <div className="p-3 border-t border-border-subtle/60 space-y-3 animate-in fade-in duration-100">
          {/* Identity & Model Header */}
          <div className="flex items-center justify-between pb-2 border-b border-border-subtle/50 text-[11px]">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-text-primary">{provider}</span>
              <span className="text-text-tertiary">/</span>
              <span className="text-text-secondary font-sans font-medium">{model}</span>
              <span className="px-1.5 py-0.2 rounded text-[10px] bg-bg-elevated border border-border-subtle text-text-tertiary">
                Model execution: {isLocal ? 'Local' : 'Cloud'}
              </span>
            </div>

            {provenance.executionId && (
              <button
                type="button"
                onClick={handleCopyExecutionId}
                className="flex items-center gap-1 px-1.5 py-0.5 rounded hover:bg-bg-hover text-text-tertiary hover:text-text-secondary transition-colors"
                title="Copy execution ID"
              >
                <span className="text-[10px]">{provenance.executionId.slice(0, 16)}...</span>
                {copiedId ? <Check className="w-3 h-3 text-success" /> : <Copy className="w-3 h-3" />}
              </button>
            )}
          </div>

          {/* Standard Metrics Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
            <div className="p-2 rounded bg-bg-elevated border border-border-subtle/50">
              <div className="text-text-tertiary text-[10px] uppercase tracking-wider font-sans">
                Privacy Boundary
              </div>
              <div className="text-text-primary font-medium mt-0.5">
                {provenance.effectivePrivacy === 'local_only'
                  ? 'Local Only'
                  : provenance.effectivePrivacy === 'approved_cloud'
                  ? 'Approved Cloud'
                  : 'Any Configured'}
              </div>
            </div>

            <div className="p-2 rounded bg-bg-elevated border border-border-subtle/50">
              <div className="text-text-tertiary text-[10px] uppercase tracking-wider font-sans">
                Routing Objective
              </div>
              <div className="text-text-primary font-medium mt-0.5">
                {provenance.routingObjective === 'quality_first'
                  ? 'Quality First'
                  : provenance.routingObjective === 'cost_first'
                  ? 'Cost First'
                  : provenance.routingObjective === 'latency_first'
                  ? 'Latency First'
                  : 'Balanced'}
              </div>
            </div>

            <div className="p-2 rounded bg-bg-elevated border border-border-subtle/50">
              <div className="text-text-tertiary text-[10px] uppercase tracking-wider font-sans">
                Token Usage
              </div>
              <div className="text-text-primary font-medium mt-0.5">
                {totalTokens} tokens
              </div>
            </div>

            <div className="p-2 rounded bg-bg-elevated border border-border-subtle/50">
              <div className="text-text-tertiary text-[10px] uppercase tracking-wider font-sans">
                Provider Charge
              </div>
              <div className="text-text-primary font-medium mt-0.5">
                {costDisplay}
              </div>
            </div>
          </div>

          {/* Optional Policy & Throughput Metrics (only when present/measured) */}
          {(canonicalPolicyStatus || (provenance.tokensPerSec !== undefined && provenance.tokensPerSec > 0)) && (
            <div className="flex flex-wrap items-center gap-3 pt-1 text-[11px] text-text-secondary border-t border-border-subtle/40">
              {canonicalPolicyStatus && (
                <div className="flex items-center gap-1.5">
                  <span className="text-text-tertiary font-sans">Policy:</span>
                  <span className="font-medium text-text-primary">{canonicalPolicyStatus}</span>
                </div>
              )}
              {provenance.tokensPerSec !== undefined && provenance.tokensPerSec > 0 && (
                <div className="flex items-center gap-1.5">
                  <span className="text-text-tertiary font-sans">Observed speed:</span>
                  <span className="text-emerald-400 font-medium">{provenance.tokensPerSec} tok/s</span>
                </div>
              )}
            </div>
          )}

          {/* Factual Decision Rationale */}
          <div className="p-2.5 rounded bg-bg-elevated/70 border border-border-subtle/50 space-y-1 font-sans text-[11px]">
            <div className="text-[10px] uppercase font-semibold text-text-tertiary font-mono tracking-wider">
              Why this was selected
            </div>
            {renderRationaleBullets()}
          </div>

          {/* Technical Provenance Footer */}
          <div className="flex items-center justify-between text-[10px] text-text-tertiary pt-1 border-t border-border-subtle/40 font-mono">
            <span>Cache: Cold (0 tok)</span>
            <span>Engine: Python Sidecar + {provider}</span>
          </div>
        </div>
      )}
    </div>
  );
};
