import React, { useState, useEffect, useCallback } from 'react';
import {
  TrendingUp,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
  ShieldCheck,
  Scale,
} from 'lucide-react';
import { ModelEconomicsSummary, EvidenceSufficiencyStatus } from '../types';
import { sidecarClient } from '../api/client';

export interface ModelEconomicsComparisonProps {
  className?: string;
}

function formatMicrosToUsd(micros: number): string {
  const usd = micros / 1_000_000;
  if (usd === 0) return '$0.0000';
  return `$${usd.toFixed(4)}`;
}

function getSufficiencyBadge(status: EvidenceSufficiencyStatus) {
  switch (status) {
    case 'SUFFICIENT_EVIDENCE':
      return {
        label: 'Sufficient Evidence',
        bg: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
        icon: <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />,
      };
    case 'INSUFFICIENT_EVIDENCE':
      return {
        label: 'Insufficient Evidence',
        bg: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
        icon: <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />,
      };
    case 'NO_SUCCESS_EVIDENCE':
      return {
        label: 'No Success Evidence',
        bg: 'bg-rose-500/10 text-rose-400 border-rose-500/20',
        icon: <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />,
      };
    default:
      return {
        label: 'Unknown',
        bg: 'bg-zinc-500/10 text-zinc-400 border-zinc-500/20',
        icon: <HelpCircle className="w-3.5 h-3.5 text-zinc-400" />,
      };
  }
}

export const ModelEconomicsComparison: React.FC<ModelEconomicsComparisonProps> = ({
  className = '',
}) => {
  const [summaries, setSummaries] = useState<ModelEconomicsSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTaskFamily, setSelectedTaskFamily] = useState<string>('all');

  const fetchEconomics = useCallback(async (isRefresh = false) => {
    if (isRefresh) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const data = await sidecarClient.getModelEconomics(
        selectedTaskFamily !== 'all' ? { taskFamily: selectedTaskFamily } : undefined
      );
      setSummaries(data);
    } catch (err: any) {
      console.error('Failed to load model economics:', err);
      setError(err?.message || 'Failed to load model economics metrics');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [selectedTaskFamily]);

  useEffect(() => {
    fetchEconomics();
  }, [fetchEconomics]);

  const taskFamilies = Array.from(new Set(summaries.map((s) => s.task_family))).filter(Boolean);

  const filteredSummaries =
    selectedTaskFamily === 'all'
      ? summaries
      : summaries.filter((s) => s.task_family === selectedTaskFamily);

  return (
    <div
      className={`p-5 rounded-2xl bg-bg-elevated/40 border border-border-subtle space-y-5 ${className}`}
    >
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-accent" />
            <h2 className="text-base font-bold text-text-primary">
              Model Economics & Chain-Level Cost-Per-Success
            </h2>
          </div>
          <p className="text-xs text-text-muted">
            Whole-chain economics attributing retries, fallbacks, and multi-attempt costs to initial routing decisions. Verified successes only.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          {taskFamilies.length > 0 && (
            <select
              value={selectedTaskFamily}
              onChange={(e) => setSelectedTaskFamily(e.target.value)}
              className="px-2.5 py-1.5 text-xs bg-bg-base border border-border-subtle rounded-lg text-text-primary focus:outline-none focus:border-accent"
            >
              <option value="all">All Task Families</option>
              {taskFamilies.map((tf) => (
                <option key={tf} value={tf}>
                  {tf}
                </option>
              ))}
            </select>
          )}

          <button
            onClick={() => fetchEconomics(true)}
            disabled={loading || refreshing}
            className="p-1.5 text-text-secondary hover:text-text-primary hover:bg-bg-elevated rounded-lg transition-colors border border-border-subtle disabled:opacity-50"
            title="Refresh Economics Telemetry"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin text-accent' : ''}`} />
          </button>
        </div>
      </div>

      {error && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-xl flex items-center gap-2.5 text-xs text-rose-400">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {loading ? (
        <div className="py-12 flex flex-col items-center justify-center gap-3 text-text-muted">
          <RefreshCw className="w-6 h-6 animate-spin text-accent" />
          <span className="text-xs font-medium">Aggregating chain-level economics...</span>
        </div>
      ) : filteredSummaries.length === 0 ? (
        <div className="py-10 text-center rounded-xl border border-dashed border-border-subtle bg-bg-base/30 p-6 space-y-2">
          <Scale className="w-8 h-8 text-text-muted mx-auto opacity-50" />
          <p className="text-sm font-semibold text-text-secondary">No Empirical Economics Recorded Yet</p>
          <p className="text-xs text-text-muted max-w-md mx-auto">
            Run executions through the router with outcome verification or evaluate golden fixtures to populate empirical cost-per-success profiles.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-border-subtle text-[11px] font-bold text-text-muted uppercase tracking-wider">
                <th className="pb-2.5 pr-4">Model & Provider</th>
                <th className="pb-2.5 px-3">Cohort Context</th>
                <th className="pb-2.5 px-3 text-right">Tasks / Attempts</th>
                <th className="pb-2.5 px-3 text-center">Outcome Truth</th>
                <th className="pb-2.5 px-3 text-right">Total Cost</th>
                <th className="pb-2.5 px-3 text-right">Observed CPS</th>
                <th className="pb-2.5 px-3 text-right">Expected CPS</th>
                <th className="pb-2.5 pl-4 text-center">Sufficiency Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-subtle/50 text-xs text-text-secondary font-mono">
              {filteredSummaries.map((summary, idx) => {
                const badge = getSufficiencyBadge(summary.status);
                const successRate =
                  summary.logical_tasks_count > 0
                    ? ((summary.verified_successes / summary.logical_tasks_count) * 100).toFixed(1)
                    : '0.0';

                return (
                  <tr key={`${summary.initial_model_identity.provider_id}-${summary.initial_model_identity.model_id}-${idx}`} className="hover:bg-bg-elevated/20 transition-colors">
                    {/* Model */}
                    <td className="py-3 pr-4 font-sans">
                      <div className="font-semibold text-text-primary">
                        {summary.initial_model_identity.model_id}
                      </div>
                      <div className="text-[11px] text-text-muted">
                        {summary.initial_provider_id}
                      </div>
                    </td>

                    {/* Cohort */}
                    <td className="py-3 px-3 font-sans">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-[10px] text-text-secondary">
                          {summary.task_family}
                        </span>
                        <span className="px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-[10px] text-text-muted flex items-center gap-1">
                          <ShieldCheck className="w-3 h-3 text-accent" />
                          {summary.effective_privacy_class}
                        </span>
                      </div>
                      <div className="text-[10px] text-text-muted mt-1">
                        eval: {summary.evaluator_version} • policy: {summary.routing_policy_version}
                      </div>
                    </td>

                    {/* Tasks / Attempts */}
                    <td className="py-3 px-3 text-right">
                      <span className="text-text-primary font-bold">{summary.logical_tasks_count}</span>
                      <span className="text-text-muted text-[11px]"> ({summary.total_attempts_count} att)</span>
                    </td>

                    {/* Outcomes */}
                    <td className="py-3 px-3 text-center">
                      <div className="flex items-center justify-center gap-1.5 text-[11px]">
                        <span className="text-emerald-400" title="Verified Successes">
                          {summary.verified_successes}s
                        </span>
                        <span className="text-text-muted">/</span>
                        <span className="text-rose-400" title="Failures">
                          {summary.failures}f
                        </span>
                        <span className="text-text-muted">/</span>
                        <span className="text-amber-400" title="Partials">
                          {summary.partials}p
                        </span>
                        <span className="text-text-muted">/</span>
                        <span className="text-zinc-400" title="Unknowns">
                          {summary.unknowns}u
                        </span>
                      </div>
                      <div className="text-[10px] text-text-muted font-sans mt-0.5">
                        {successRate}% verified
                      </div>
                    </td>

                    {/* Total Cost */}
                    <td className="py-3 px-3 text-right text-text-secondary">
                      {formatMicrosToUsd(summary.total_cost.amount_micros)}
                    </td>

                    {/* Observed CPS */}
                    <td className="py-3 px-3 text-right font-medium">
                      {summary.observed_cost_per_verified_success ? (
                        <span className="text-text-primary">
                          {formatMicrosToUsd(summary.observed_cost_per_verified_success.amount_micros)}
                        </span>
                      ) : (
                        <span className="text-text-muted font-normal text-[11px]">—</span>
                      )}
                    </td>

                    {/* Expected CPS */}
                    <td className="py-3 px-3 text-right font-bold">
                      {summary.expected_cost_per_success ? (
                        <span className="text-emerald-400">
                          {formatMicrosToUsd(summary.expected_cost_per_success.amount_micros)}
                        </span>
                      ) : (
                        <span className="text-text-muted font-normal text-[11px]" title={summary.expected_cost_per_success_provenance || 'None'}>
                          None
                        </span>
                      )}
                    </td>

                    {/* Status Badge */}
                    <td className="py-3 pl-4 text-center font-sans">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-medium ${badge.bg}`}
                      >
                        {badge.icon}
                        {badge.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
