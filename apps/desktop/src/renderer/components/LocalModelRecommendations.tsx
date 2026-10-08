import React, { useState, useEffect, useCallback } from 'react';
import {
  Cpu,
  Sparkles,
  Zap,
  Scale,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Loader2,
} from 'lucide-react';
import {
  LocalRecommendationResponse,
  LocalModelRecommendation,
  NumericFactProvenance,
} from '../types';
import { sidecarClient } from '../api/client';

export interface LocalModelRecommendationsProps {
  className?: string;
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GiB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function getProvenanceBadgeColor(prov: NumericFactProvenance): string {
  switch (prov) {
    case 'declared_fact':
      return 'bg-blue-500/10 text-blue-400 border-blue-500/20';
    case 'measured_fact':
      return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
    case 'inspected_fact':
      return 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20';
    case 'curated_policy':
      return 'bg-purple-500/10 text-purple-400 border-purple-500/20';
    case 'curated_heuristic':
      return 'bg-amber-500/10 text-amber-400 border-amber-500/20';
    case 'derived_estimate':
      return 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20';
    default:
      return 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20';
  }
}

function formatProvenanceLabel(prov: NumericFactProvenance): string {
  switch (prov) {
    case 'declared_fact':
      return 'Declared Fact';
    case 'measured_fact':
      return 'Measured Fact';
    case 'inspected_fact':
      return 'Inspected Fact';
    case 'curated_policy':
      return 'Curated Policy';
    case 'curated_heuristic':
      return 'Curated Heuristic';
    case 'derived_estimate':
      return 'Derived Estimate';
    default:
      return 'Unknown';
  }
}

interface TierCardProps {
  tierName: string;
  icon: React.ReactNode;
  badgeBg: string;
  badgeText: string;
  rec: LocalModelRecommendation | null | undefined;
}

const TierCard: React.FC<TierCardProps> = ({
  tierName,
  icon,
  badgeBg,
  badgeText,
  rec,
}) => {
  const [expanded, setExpanded] = useState(false);

  if (!rec) {
    return (
      <div className="p-5 rounded-xl bg-bg-surface border border-border-subtle flex flex-col justify-between opacity-70">
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              {icon}
              <span className="text-xs font-bold uppercase tracking-wider text-text-primary">
                {tierName}
              </span>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-zinc-500/10 text-zinc-400 border border-zinc-500/20">
              Not Available
            </span>
          </div>
          <p className="text-xs text-text-tertiary">
            No local model in the catalog safely satisfies the headroom requirements for this tier on current hardware.
          </p>
        </div>
      </div>
    );
  }

  const { model_entry, fit_result } = rec;
  const headroomPct = Math.round(fit_result.ram_headroom_ratio * 100);

  return (
    <div className="p-5 rounded-xl bg-bg-surface border border-border-subtle flex flex-col justify-between space-y-4 hover:border-border-default transition-colors">
      <div>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            {icon}
            <span className="text-xs font-bold uppercase tracking-wider text-text-primary">
              {tierName}
            </span>
          </div>
          <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${badgeBg} ${badgeText}`}>
            {fit_result.state === 'fits' ? 'Comfortable Fit' : 'Fits with Limits'}
          </span>
        </div>

        <div className="space-y-1">
          <h4 className="text-sm font-bold text-text-primary">
            {model_entry.model_identity.model_id}
          </h4>
          <p className="text-xs text-text-secondary">{rec.reason}</p>
        </div>

        {/* Key Metrics Grid */}
        <div className="grid grid-cols-2 gap-2 mt-4 text-[11px]">
          <div className="p-2 rounded-lg bg-bg-base border border-border-subtle space-y-0.5">
            <span className="text-text-tertiary block">RAM Headroom</span>
            <span className="text-text-primary font-mono font-semibold">
              {headroomPct}% ({formatBytes(fit_result.ram_headroom_bytes)})
            </span>
          </div>
          <div className="p-2 rounded-lg bg-bg-base border border-border-subtle space-y-0.5">
            <span className="text-text-tertiary block">Required Memory</span>
            <span className="text-text-primary font-mono font-semibold">
              {formatBytes(fit_result.required_ram_bytes)}
            </span>
          </div>
          <div className="p-2 rounded-lg bg-bg-base border border-border-subtle space-y-0.5">
            <span className="text-text-tertiary block">Model Artifact</span>
            <span className="text-text-primary font-mono font-semibold">
              {formatBytes(model_entry.artifact_size_bytes)} ({model_entry.quantization})
            </span>
          </div>
          <div className="p-2 rounded-lg bg-bg-base border border-border-subtle space-y-0.5">
            <span className="text-text-tertiary block">KV Cache Overhead</span>
            <span className="text-text-primary font-mono font-semibold">
              {formatBytes(fit_result.kv_context_bytes)}
            </span>
          </div>
        </div>

        {/* Fact Provenance Metadata Chips */}
        <div className="flex flex-wrap gap-1.5 mt-3">
          <span
            className={`px-2 py-0.5 rounded text-[10px] font-medium border ${getProvenanceBadgeColor(
              model_entry.quality_rank_provenance
            )}`}
            title={`Source: ${model_entry.quality_rank_source}`}
          >
            Rank #{model_entry.quality_rank} ({formatProvenanceLabel(model_entry.quality_rank_provenance)})
          </span>
          <span
            className={`px-2 py-0.5 rounded text-[10px] font-medium border ${getProvenanceBadgeColor(
              model_entry.artifact_size_provenance
            )}`}
            title={`Source: ${model_entry.artifact_size_source}`}
          >
            Artifact ({formatProvenanceLabel(model_entry.artifact_size_provenance)})
          </span>
          <span
            className={`px-2 py-0.5 rounded text-[10px] font-medium border ${getProvenanceBadgeColor(
              fit_result.kv_context_provenance
            )}`}
          >
            KV Cache ({formatProvenanceLabel(fit_result.kv_context_provenance)})
          </span>
        </div>
      </div>

      {/* Expandable Technical Details */}
      <div className="border-t border-border-subtle pt-3">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center justify-between w-full text-[11px] font-medium text-text-secondary hover:text-text-primary transition-colors"
        >
          <span>Audit & Provenance Details</span>
          {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>

        {expanded && (
          <div className="mt-3 space-y-2 text-[10px] font-mono bg-bg-base p-3 rounded-lg border border-border-subtle text-text-secondary overflow-x-auto">
            <div className="flex justify-between">
              <span className="text-text-tertiary">Usable RAM (Denominator):</span>
              <span className="text-text-primary">{formatBytes(fit_result.usable_before_model_bytes)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-tertiary">Min Resident RAM:</span>
              <span className="text-text-primary">{formatBytes(model_entry.min_ram_bytes)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-tertiary">Recommended RAM:</span>
              <span className="text-text-primary">{formatBytes(model_entry.recommended_ram_bytes)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-tertiary">Backend Evaluated:</span>
              <span className="text-text-primary uppercase">{fit_result.backend_used}</span>
            </div>
            {model_entry.kv_metadata && (
              <div className="flex justify-between">
                <span className="text-text-tertiary">KV Architecture:</span>
                <span className="text-text-primary">
                  {model_entry.kv_metadata.num_layers}L / {model_entry.kv_metadata.num_kv_heads}H / {model_entry.kv_metadata.head_dim}D
                </span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-text-tertiary">Catalog Version:</span>
              <span className="text-text-primary">{model_entry.catalog_version}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-tertiary">Catalog Updated:</span>
              <span className="text-text-primary">{model_entry.updated_at}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export const LocalModelRecommendations: React.FC<LocalModelRecommendationsProps> = ({ className = '' }) => {
  const [data, setData] = useState<LocalRecommendationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRecommendations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await sidecarClient.getRecommendedLocalModels({
        min_context_tokens: 4096,
        require_local_only: true,
      });
      setData(res);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch recommendations');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRecommendations();
  }, [fetchRecommendations]);

  const hasAnyRecommendation = data && (data.fast || data.balanced || data.best_local);

  return (
    <div className={`p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-5 ${className}`}>
      {/* Header and Telemetry Status Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border-subtle pb-4">
        <div>
          <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
            <Cpu className="w-4 h-4 text-accent" />
            Hardware-Fit Local Model Recommendations
          </h2>
          <p className="text-xs text-text-secondary mt-0.5">
            Deterministic recommendations calculated purely from host hardware telemetry and curated model metadata. Side-effect-free.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Freshness Badge */}
          {data && (
            <div
              className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1.5 border ${
                data.resource_stale || data.stale_telemetry
                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                  : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  data.resource_stale || data.stale_telemetry ? 'bg-amber-400' : 'bg-emerald-400 animate-pulse'
                }`}
              />
              {data.resource_stale || data.stale_telemetry ? 'Stale Telemetry' : 'Fresh Telemetry'}
              {data.resource_captured_at > 0 && (
                <span className="text-[10px] text-text-tertiary">
                  ({Math.max(0, Math.round(Date.now() / 1000 - data.resource_captured_at))}s ago)
                </span>
              )}
            </div>
          )}

          <button
            onClick={fetchRecommendations}
            disabled={loading}
            className="p-1.5 rounded-lg bg-bg-surface hover:bg-bg-base border border-border-subtle text-text-secondary hover:text-text-primary transition-colors disabled:opacity-50"
            title="Refresh Recommendations"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Warning Banner (if snapshot stale or refresh failed) */}
      {data?.warning && (
        <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-start gap-2.5 text-xs">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <div>
            <span className="font-semibold">Telemetry Notice: </span>
            {data.warning}
          </div>
        </div>
      )}

      {/* Error State */}
      {error && (
        <div className="p-4 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 flex items-center gap-3 text-xs">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <div>
            <span className="font-semibold">Recommendation Error: </span>
            {error}
          </div>
        </div>
      )}

      {/* Loading State */}
      {loading && !data && (
        <div className="py-12 flex flex-col items-center justify-center gap-3 text-text-tertiary">
          <Loader2 className="w-6 h-6 animate-spin text-accent" />
          <span className="text-xs">Evaluating hardware fit against local catalog...</span>
        </div>
      )}

      {/* No Safe Models State */}
      {data && !hasAnyRecommendation && (
        <div className="p-5 rounded-xl bg-bg-surface border border-border-subtle text-center space-y-3">
          <div className="w-10 h-10 rounded-full bg-amber-500/15 border border-amber-500/30 flex items-center justify-center mx-auto text-amber-400">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div className="space-y-1">
            <h3 className="text-sm font-bold text-text-primary">No Safe Local Models Fit Current Hardware</h3>
            <p className="text-xs text-text-secondary max-w-md mx-auto">
              After reserving memory for the operating system, Agent Engine, and runtime services,
              none of the models in the curated catalog satisfy safe execution headroom.
            </p>
          </div>
          {Object.keys(data.rejection_summary || {}).length > 0 && (
            <div className="text-left max-w-md mx-auto mt-3 p-3 rounded-lg bg-bg-base border border-border-subtle text-[11px] text-text-tertiary font-mono space-y-1">
              <span className="font-semibold text-text-secondary block">Evaluated Exclusions:</span>
              {Object.entries(data.rejection_summary).map(([modelId, reasons]) => (
                <div key={modelId}>
                  <span className="text-text-primary">{modelId}:</span> {reasons.join(', ')}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Three Tier Cards: Fast, Balanced, Best Local */}
      {data && hasAnyRecommendation && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <TierCard
            tierName="Fast"
            icon={<Zap className="w-4 h-4 text-emerald-400" />}
            badgeBg="bg-emerald-500/10 border-emerald-500/20"
            badgeText="text-emerald-400"
            rec={data.fast}
          />
          <TierCard
            tierName="Balanced"
            icon={<Scale className="w-4 h-4 text-blue-400" />}
            badgeBg="bg-blue-500/10 border-blue-500/20"
            badgeText="text-blue-400"
            rec={data.balanced}
          />
          <TierCard
            tierName="Best Local"
            icon={<Sparkles className="w-4 h-4 text-purple-400" />}
            badgeBg="bg-purple-500/10 border-purple-500/20"
            badgeText="text-purple-400"
            rec={data.best_local}
          />
        </div>
      )}
    </div>
  );
};
export default LocalModelRecommendations;
