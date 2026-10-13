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
  DownloadStatus,
  ManagedRuntimeStatus,
  CatalogModelEntry,
} from '../types';
import { sidecarClient } from '../api/client';

export interface LocalModelRecommendationsProps {
  className?: string;
  onStateChange?: () => void;
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
  installedModels: DownloadStatus[];
  downloads: DownloadStatus[];
  runtimeStatus: ManagedRuntimeStatus | null;
  onInstall: (modelId: string) => Promise<void>;
  onCancel: (artifactId: string) => Promise<void>;
  onStart: (modelId: string) => Promise<void>;
  onStop: () => Promise<void>;
  onRetry: (modelId: string) => Promise<void>;
  actionBusyModel: string | null;
}

const TierCard: React.FC<TierCardProps> = ({
  tierName,
  icon,
  badgeBg,
  badgeText,
  rec,
  installedModels,
  downloads,
  runtimeStatus,
  onInstall,
  onCancel,
  onStart,
  onStop,
  onRetry,
  actionBusyModel,
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

  const modelId = model_entry.model_identity.model_id;
  const artifactId = `${modelId}.gguf`;

  const downloadItem = downloads.find(
    (d) =>
      d.artifact_id === artifactId ||
      d.model_identity?.model_id === modelId ||
      d.artifact_id.includes(modelId)
  );
  const installedItem = installedModels.find(
    (d) =>
      d.artifact_id === artifactId ||
      d.model_identity?.model_id === modelId ||
      d.artifact_id.includes(modelId)
  );

  const isInstalled = !!installedItem || downloadItem?.state === 'verified';
  const downloadState = downloadItem?.state || (isInstalled ? 'verified' : 'not_present');
  const progressPct = downloadItem ? Math.round((downloadItem.progress_ratio || 0) * 100) : 0;

  const isModelActive =
    !!runtimeStatus?.is_ready &&
    runtimeStatus?.state === 'ready' &&
    (runtimeStatus.model_loaded === modelId ||
      runtimeStatus.model_loaded === artifactId ||
      !runtimeStatus.model_loaded);

  const isModelStarting =
    (runtimeStatus?.state === 'starting' &&
      (runtimeStatus.model_loaded === modelId || !runtimeStatus.model_loaded)) ||
    actionBusyModel === `start-${modelId}`;

  const isDownloading = downloadState === 'downloading';
  const isVerifying = downloadState === 'verifying';
  const isDownloadFailed = downloadState === 'failed';

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

      {/* Contextual Action Flow */}
      <div className="pt-3 border-t border-border-subtle">
        <div className="flex items-center justify-between gap-2 min-h-[32px]">
          {/* Status Badge / State Indicator */}
          <div className="flex items-center gap-1.5 text-xs">
            {isDownloading && (
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-[11px] font-mono text-accent">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  <span>Downloading {progressPct}%</span>
                </div>
                <div className="w-24 h-1.5 bg-bg-base rounded-full overflow-hidden border border-border-subtle">
                  <div
                    className="h-full bg-accent transition-all duration-300 rounded-full"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
              </div>
            )}
            {isVerifying && (
              <div className="flex items-center gap-1.5 text-[11px] font-mono text-amber-400">
                <Loader2 className="w-3 h-3 animate-spin" />
                <span>Verifying…</span>
              </div>
            )}
            {isDownloadFailed && (
              <div className="flex items-center gap-1.5 text-[11px] font-mono text-rose-400">
                <AlertTriangle className="w-3 h-3" />
                <span>Failed</span>
              </div>
            )}
            {!isDownloading && !isVerifying && !isDownloadFailed && isInstalled && isModelActive && (
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Ready
              </span>
            )}
            {!isDownloading && !isVerifying && !isDownloadFailed && isInstalled && isModelStarting && (
              <span className="px-2 py-0.5 rounded text-[10px] font-mono text-amber-400 bg-amber-500/10 border border-amber-500/20 flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                Starting…
              </span>
            )}
            {!isDownloading && !isVerifying && !isDownloadFailed && isInstalled && !isModelActive && !isModelStarting && (
              fit_result.state === 'does_not_fit' ? (
                <div className="flex flex-col gap-0.5">
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 w-fit">
                    Installed · Verified
                  </span>
                  <span className="text-[10px] text-amber-400 font-mono">
                    Cannot start now — insufficient available memory
                  </span>
                </div>
              ) : (
                <span className="text-[11px] text-text-tertiary font-mono">
                  Installed (Stopped)
                </span>
              )
            )}
            {!isDownloading && !isVerifying && !isDownloadFailed && !isInstalled && (
              <span className="text-[11px] text-text-tertiary font-mono">
                Not Installed
              </span>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-2">
            {isDownloading && (
              <button
                type="button"
                onClick={() => onCancel(artifactId)}
                disabled={actionBusyModel !== null}
                className="px-2.5 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary hover:text-text-primary transition-colors"
              >
                Cancel
              </button>
            )}
            {isVerifying && (
              <button
                type="button"
                disabled
                className="px-2.5 py-1 rounded bg-bg-base border border-border-subtle text-xs text-text-tertiary cursor-not-allowed"
              >
                Verifying…
              </button>
            )}
            {isDownloadFailed && (
              <>
                <button
                  type="button"
                  onClick={() => onRetry(modelId)}
                  disabled={actionBusyModel !== null}
                  className="px-2.5 py-1 rounded bg-accent/15 hover:bg-accent/25 border border-accent/30 text-xs font-medium text-accent transition-colors"
                >
                  Retry
                </button>
                <button
                  type="button"
                  onClick={() => setExpanded(true)}
                  className="px-2 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-tertiary hover:text-text-secondary transition-colors"
                >
                  Details
                </button>
              </>
            )}
            {!isDownloading && !isVerifying && !isDownloadFailed && !isInstalled && (
              <button
                type="button"
                onClick={() => onInstall(modelId)}
                disabled={actionBusyModel !== null}
                className="px-3 py-1 rounded bg-accent text-accent-contrast font-medium text-xs hover:opacity-90 transition-opacity disabled:opacity-50"
              >
                Install
              </button>
            )}
            {!isDownloading && !isVerifying && !isDownloadFailed && isInstalled && !isModelActive && !isModelStarting && (
              fit_result.state === 'does_not_fit' ? (
                <button
                  type="button"
                  disabled
                  title="Cannot start now — insufficient available memory"
                  className="px-3 py-1 rounded bg-bg-base border border-border-subtle text-text-tertiary font-medium text-xs cursor-not-allowed opacity-50"
                >
                  Start
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => onStart(modelId)}
                  disabled={actionBusyModel !== null}
                  className="px-3 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium text-xs transition-colors disabled:opacity-50"
                >
                  Start
                </button>
              )
            )}
            {!isDownloading && !isVerifying && !isDownloadFailed && isInstalled && isModelActive && (
              <button
                type="button"
                onClick={onStop}
                disabled={actionBusyModel !== null}
                className="px-2.5 py-1 rounded bg-rose-500/15 hover:bg-rose-500/25 border border-rose-500/30 text-xs font-medium text-rose-400 transition-colors disabled:opacity-50"
              >
                Stop
              </button>
            )}
          </div>
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
            {downloadItem?.error_message && (
              <div className="flex flex-col gap-0.5 text-rose-400 pb-2 border-b border-border-subtle">
                <span className="font-semibold text-rose-300">Failure Diagnostics:</span>
                <span className="break-all">{downloadItem.error_message}</span>
              </div>
            )}
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

export const LocalModelRecommendations: React.FC<LocalModelRecommendationsProps> = ({
  className = '',
  onStateChange,
}) => {
  const [data, setData] = useState<LocalRecommendationResponse | null>(null);
  const [catalog, setCatalog] = useState<CatalogModelEntry[]>([]);
  const [installedModels, setInstalledModels] = useState<DownloadStatus[]>([]);
  const [downloads, setDownloads] = useState<DownloadStatus[]>([]);
  const [runtimeStatus, setRuntimeStatus] = useState<ManagedRuntimeStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [is401, setIs401] = useState(false);
  const [actionBusyModel, setActionBusyModel] = useState<string | null>(null);

  const refreshStatuses = useCallback(async () => {
    try {
      const [installed, dls, rStatus] = await Promise.all([
        sidecarClient.getInstalledModels().catch((e: any) => {
          if (e?.message?.includes('401') || e?.message?.toLowerCase().includes('unauthorized')) {
            setIs401(true);
          }
          return [];
        }),
        sidecarClient.getModelDownloads().catch(() => []),
        sidecarClient.getManagedRuntimeStatus().catch(() => null),
      ]);
      setInstalledModels(installed || []);
      setDownloads(dls || []);
      setRuntimeStatus(rStatus);
      if (onStateChange) onStateChange();
    } catch {
      // offline fallback
    }
  }, [onStateChange]);

  const fetchRecommendations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [res, cat] = await Promise.all([
        sidecarClient.getRecommendedLocalModels({
          min_context_tokens: 4096,
          require_local_only: true,
        }),
        sidecarClient.getLocalModelCatalog().catch(() => []),
      ]);
      setData(res);
      setCatalog(cat || []);
      await refreshStatuses();
    } catch (err: any) {
      if (err?.message?.includes('401') || err?.message?.toLowerCase().includes('unauthorized')) {
        setIs401(true);
      } else {
        setError(err.message || 'Failed to fetch recommendations');
      }
    } finally {
      setLoading(false);
    }
  }, [refreshStatuses]);

  useEffect(() => {
    fetchRecommendations();
  }, [fetchRecommendations]);

  // Subscribe to 401 desktop connection required state
  useEffect(() => {
    return sidecarClient.onDesktopConnectionRequiredChange((req) => {
      if (req) setIs401(true);
    });
  }, []);

  // Polling during active downloading / verifying / runtime transitions
  // Cadence: 1.5s for downloads, 2s for runtime transitions.
  // Suspended on document.hidden, in-flight, or when desktopConnectionRequired is active.
  useEffect(() => {
    let inFlight = false;
    const hasActiveDownloads = downloads.some((d) => d.state === 'downloading' || d.state === 'verifying');
    const hasRuntimeTransition =
      runtimeStatus?.state === 'starting' || runtimeStatus?.state === 'stopping';

    if (!hasActiveDownloads && !hasRuntimeTransition) return;

    const poll = async () => {
      if (inFlight || document.hidden || sidecarClient.isDesktopConnectionRequired()) return;
      inFlight = true;
      try {
        await refreshStatuses();
      } finally {
        inFlight = false;
      }
    };

    const intervalMs = hasActiveDownloads ? 1500 : 2000;
    const timer = setInterval(poll, intervalMs);

    const handleVisibilityChange = () => {
      if (!document.hidden && !sidecarClient.isDesktopConnectionRequired()) {
        poll();
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [downloads, runtimeStatus, refreshStatuses]);

  const handleInstall = async (modelId: string) => {
    setActionBusyModel(`install-${modelId}`);
    try {
      await sidecarClient.startModelDownload(modelId, 'llamacpp');
      await refreshStatuses();
    } catch (err: any) {
      if (err?.message?.includes('401') || err?.message?.toLowerCase().includes('unauthorized')) {
        setIs401(true);
      } else {
        setError(err.message || 'Failed to start download');
      }
    } finally {
      setActionBusyModel(null);
    }
  };

  const handleCancel = async (artifactId: string) => {
    setActionBusyModel(`cancel-${artifactId}`);
    try {
      await sidecarClient.cancelModelDownload(artifactId);
      await refreshStatuses();
    } catch (err: any) {
      setError(err.message || 'Failed to cancel download');
    } finally {
      setActionBusyModel(null);
    }
  };

  const handleStart = async (modelId: string) => {
    setActionBusyModel(`start-${modelId}`);
    try {
      const res = await sidecarClient.startManagedRuntime(modelId);
      setRuntimeStatus(res);
      await refreshStatuses();
    } catch (err: any) {
      if (err?.message?.includes('401') || err?.message?.toLowerCase().includes('unauthorized')) {
        setIs401(true);
      } else {
        setError(err.message || 'Failed to start managed runtime');
      }
    } finally {
      setActionBusyModel(null);
    }
  };

  const handleStop = async () => {
    setActionBusyModel('stop');
    try {
      const res = await sidecarClient.stopManagedRuntime();
      setRuntimeStatus(res);
      await refreshStatuses();
    } catch (err: any) {
      if (err?.message?.includes('401') || err?.message?.toLowerCase().includes('unauthorized')) {
        setIs401(true);
      } else {
        setError(err.message || 'Failed to stop managed runtime');
      }
    } finally {
      setActionBusyModel(null);
    }
  };

  const handleRetry = async (modelId: string) => {
    await handleInstall(modelId);
  };

  const handleRetryConnection = async () => {
    setIs401(false);
    await sidecarClient.retryConnection();
    await fetchRecommendations();
  };

  if (is401 || sidecarClient.isDesktopConnectionRequired()) {
    return (
      <div
        className={`p-8 rounded-xl bg-bg-elevated border border-border-subtle text-center space-y-3 ${className}`}
        data-testid="browser-401-notice"
      >
        <div className="text-sm font-semibold text-text-primary">Desktop connection required</div>
        <p className="text-xs text-text-secondary max-w-sm mx-auto">
          Open Agent Engine in the native desktop app to manage local models.
        </p>
        <button
          type="button"
          onClick={handleRetryConnection}
          className="px-3 py-1.5 rounded bg-accent text-accent-contrast text-xs font-medium hover:opacity-90 transition-opacity"
        >
          Retry Connection
        </button>
      </div>
    );
  }

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
        <div className="space-y-4">
          <div className="p-5 rounded-xl bg-bg-surface border border-border-subtle text-center space-y-3">
            <div className="w-10 h-10 rounded-full bg-amber-500/15 border border-amber-500/30 flex items-center justify-center mx-auto text-amber-400">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <div className="space-y-1">
              <h3 className="text-sm font-bold text-text-primary">No models can safely run with current memory headroom.</h3>
              <p className="text-xs text-text-secondary max-w-md mx-auto">
                You can still install a model for later use.
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

          {/* Curated Catalog Entries */}
          {catalog.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary">
                  Curated Catalog ({catalog.length} Models)
                </h4>
                <span className="text-[11px] text-text-tertiary">
                  Installable regardless of current memory headroom
                </span>
              </div>

              <div className="grid grid-cols-1 gap-3">
                {catalog.map((entry) => {
                  const modelId = entry.model_identity.model_id;
                  const artifactId = `${modelId}.gguf`;
                  const downloadItem = downloads.find(
                    (d) =>
                      d.artifact_id === artifactId ||
                      d.model_identity?.model_id === modelId ||
                      d.artifact_id.includes(modelId)
                  );
                  const installedItem = installedModels.find(
                    (d) =>
                      d.artifact_id === artifactId ||
                      d.model_identity?.model_id === modelId ||
                      d.artifact_id.includes(modelId)
                  );
                  const isInstalled = !!installedItem || downloadItem?.state === 'verified';
                  const downloadState = downloadItem?.state || (isInstalled ? 'verified' : 'not_present');
                  const isDownloading = downloadState === 'downloading';
                  const isVerifying = downloadState === 'verifying';
                  const isDownloadFailed = downloadState === 'failed';
                  const progressPct = downloadItem ? Math.round((downloadItem.progress_ratio || 0) * 100) : 0;

                  // Parse memory requirements and current deficit
                  const reasons = data.rejection_summary?.[modelId] || [];
                  const ramReason = reasons.find((r) => r.includes('Insufficient safe RAM') || r.includes('deficit'));
                  let requiredMemStr = formatBytes(entry.min_ram_bytes);
                  let deficitStr = '—';
                  if (ramReason) {
                    const reqMatch = ramReason.match(/required\s+([\d.]+\s*(?:GiB|MiB|B))/i);
                    if (reqMatch) requiredMemStr = reqMatch[1];
                    const defMatch = ramReason.match(/deficit:\s*([^)]+)/i);
                    if (defMatch) deficitStr = defMatch[1].trim();
                  }

                  return (
                    <div
                      key={modelId}
                      className="p-4 rounded-xl bg-bg-surface border border-border-subtle flex flex-col md:flex-row md:items-center justify-between gap-4 hover:border-border-default transition-colors"
                    >
                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-bold text-text-primary">{modelId}</span>
                          <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-bg-base border border-border-subtle text-text-tertiary">
                            {entry.quantization}
                          </span>
                          {isInstalled && (
                            <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                              Installed · Verified
                            </span>
                          )}
                        </div>

                        {/* Metric details: Model, Quantization, Artifact size, Required memory, Current deficit */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px] font-mono">
                          <div className="p-1.5 rounded bg-bg-base border border-border-subtle space-y-0.5">
                            <span className="text-text-tertiary block text-[10px]">Quantization</span>
                            <span className="text-text-primary font-semibold">{entry.quantization}</span>
                          </div>
                          <div className="p-1.5 rounded bg-bg-base border border-border-subtle space-y-0.5">
                            <span className="text-text-tertiary block text-[10px]">Artifact Size</span>
                            <span className="text-text-primary font-semibold">{formatBytes(entry.artifact_size_bytes)}</span>
                          </div>
                          <div className="p-1.5 rounded bg-bg-base border border-border-subtle space-y-0.5">
                            <span className="text-text-tertiary block text-[10px]">Required Memory</span>
                            <span className="text-text-primary font-semibold">{requiredMemStr}</span>
                          </div>
                          <div className="p-1.5 rounded bg-bg-base border border-border-subtle space-y-0.5">
                            <span className="text-text-tertiary block text-[10px]">Current Deficit</span>
                            <span className="text-amber-400 font-semibold">{deficitStr}</span>
                          </div>
                        </div>
                      </div>

                      {/* Action Area */}
                      <div className="flex items-center gap-3 flex-shrink-0 self-end md:self-center">
                        {isDownloading && (
                          <div className="flex items-center gap-2">
                            <div className="flex items-center gap-1.5 text-[11px] font-mono text-accent">
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                              <span>Downloading {progressPct}%</span>
                            </div>
                            <button
                              type="button"
                              onClick={() => handleCancel(downloadItem?.artifact_id || artifactId)}
                              disabled={actionBusyModel !== null}
                              className="px-2.5 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary"
                            >
                              Cancel
                            </button>
                          </div>
                        )}
                        {isVerifying && (
                          <div className="flex items-center gap-1.5 text-[11px] font-mono text-amber-400">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            <span>Verifying…</span>
                          </div>
                        )}
                        {isDownloadFailed && (
                          <button
                            type="button"
                            onClick={() => handleInstall(modelId)}
                            disabled={actionBusyModel !== null}
                            className="px-2.5 py-1 rounded bg-accent/15 hover:bg-accent/25 border border-accent/30 text-xs font-medium text-accent"
                          >
                            Retry
                          </button>
                        )}
                        {!isDownloading && !isVerifying && !isDownloadFailed && !isInstalled && (
                          <button
                            type="button"
                            onClick={() => handleInstall(modelId)}
                            disabled={actionBusyModel !== null}
                            className="px-3 py-1.5 rounded bg-accent text-accent-contrast font-medium text-xs hover:opacity-90 transition-opacity disabled:opacity-50"
                          >
                            Install
                          </button>
                        )}
                        {!isDownloading && !isVerifying && !isDownloadFailed && isInstalled && (
                          <div className="flex items-center gap-3">
                            <span className="text-xs text-amber-400 font-mono">
                              Cannot start now — insufficient available memory
                            </span>
                            <button
                              type="button"
                              disabled
                              title="Cannot start now — insufficient available memory"
                              className="px-3 py-1.5 rounded bg-bg-base border border-border-subtle text-text-tertiary font-medium text-xs cursor-not-allowed opacity-50"
                            >
                              Start
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
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
            installedModels={installedModels}
            downloads={downloads}
            runtimeStatus={runtimeStatus}
            onInstall={handleInstall}
            onCancel={handleCancel}
            onStart={handleStart}
            onStop={handleStop}
            onRetry={handleRetry}
            actionBusyModel={actionBusyModel}
          />
          <TierCard
            tierName="Balanced"
            icon={<Scale className="w-4 h-4 text-blue-400" />}
            badgeBg="bg-blue-500/10 border-blue-500/20"
            badgeText="text-blue-400"
            rec={data.balanced}
            installedModels={installedModels}
            downloads={downloads}
            runtimeStatus={runtimeStatus}
            onInstall={handleInstall}
            onCancel={handleCancel}
            onStart={handleStart}
            onStop={handleStop}
            onRetry={handleRetry}
            actionBusyModel={actionBusyModel}
          />
          <TierCard
            tierName="Best Local"
            icon={<Sparkles className="w-4 h-4 text-purple-400" />}
            badgeBg="bg-purple-500/10 border-purple-500/20"
            badgeText="text-purple-400"
            rec={data.best_local}
            installedModels={installedModels}
            downloads={downloads}
            runtimeStatus={runtimeStatus}
            onInstall={handleInstall}
            onCancel={handleCancel}
            onStart={handleStart}
            onStop={handleStop}
            onRetry={handleRetry}
            actionBusyModel={actionBusyModel}
          />
        </div>
      )}
    </div>
  );
};

export default LocalModelRecommendations;
