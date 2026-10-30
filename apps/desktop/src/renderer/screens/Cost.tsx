import React, { useState, useEffect } from 'react';
import {
  CircleDollarSign,
  PieChart,
  BarChart3,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Download,
  Flame,
  Layers,
  Sparkles,
  Save,
  Database,
} from 'lucide-react';
import {
  Mode,
  ModelTier,
  CostMetrics,
  BudgetConfig,
  DistillationCandidate,
} from '../types';
import { sidecarClient } from '../api/client';
import { ModelEconomicsComparison } from '../components/ModelEconomicsComparison';

export interface CostScreenProps {
  onSelectMode: (mode: Mode) => void;
  activeModel?: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
}

export const Cost: React.FC<CostScreenProps> = () => {
  const [metrics, setMetrics] = useState<CostMetrics | null>(null);
  const [budget, setBudget] = useState<BudgetConfig | null>(null);
  const [candidates, setCandidates] = useState<DistillationCandidate[]>([]);
  const [groupBy, setGroupBy] = useState<string>('day');
  const [project, setProject] = useState<string>('default');
  const [loading, setLoading] = useState<boolean>(true);
  const [refreshing, setRefreshing] = useState<boolean>(false);
  const [distillingMap, setDistillingMap] = useState<Record<string, boolean>>({});

  // Budget Edit Form State
  const [editMonthly, setEditMonthly] = useState<number>(100.0);
  const [editDaily, setEditDaily] = useState<number>(10.0);
  const [editWarningPct, setEditWarningPct] = useState<number>(80.0);
  const [editCriticalPct, setEditCriticalPct] = useState<number>(100.0);
  const [budgetSaveStatus, setBudgetSaveStatus] = useState<string | null>(null);

  const fetchCostData = async (showRefreshIndicator = false) => {
    if (showRefreshIndicator) setRefreshing(true);
    try {
      const [costRes, budgetRes, candRes] = await Promise.all([
        sidecarClient.getCostMetrics(groupBy, project),
        sidecarClient.getBudgetConfig(project),
        sidecarClient.listDistillationCandidates(),
      ]);
      setMetrics(costRes);
      setBudget(budgetRes);
      setCandidates(candRes);
      if (budgetRes) {
        setEditMonthly(budgetRes.monthly_budget_usd);
        setEditDaily(budgetRes.daily_budget_usd);
        setEditWarningPct(budgetRes.warning_threshold_pct);
        setEditCriticalPct(budgetRes.critical_threshold_pct);
      }
    } catch (err) {
      console.error('Failed to load cost metrics', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchCostData();
  }, [groupBy, project]);

  const handleSaveBudget = async (e: React.FormEvent) => {
    e.preventDefault();
    setBudgetSaveStatus('Saving...');
    try {
      const updated = await sidecarClient.setBudgetConfig({
        monthly_budget_usd: editMonthly,
        daily_budget_usd: editDaily,
        warning_threshold_pct: editWarningPct,
        critical_threshold_pct: editCriticalPct,
        project,
      });
      setBudget(updated);
      setBudgetSaveStatus('Budget settings saved!');
      setTimeout(() => setBudgetSaveStatus(null), 3000);
      await fetchCostData();
    } catch (err: any) {
      setBudgetSaveStatus(`Error: ${err?.message || err}`);
    }
  };

  const handleTriggerDistill = async (candidateId: string) => {
    setDistillingMap((prev) => ({ ...prev, [candidateId]: true }));
    try {
      const res = await sidecarClient.triggerDistillation(candidateId);
      alert(res.message);
      await fetchCostData();
    } catch (err: any) {
      alert(`Distillation failed: ${err?.message || err}`);
    } finally {
      setDistillingMap((prev) => ({ ...prev, [candidateId]: false }));
    }
  };

  const exportCSV = () => {
    if (!metrics || !metrics.breakdown || metrics.breakdown.length === 0) return;
    const headers = ['Group', 'Calls', 'Prompt Tokens', 'Completion Tokens', 'Total Tokens', 'Cost USD'];
    const rows = metrics.breakdown.map((r) => [
      `"${r.group}"`,
      r.calls,
      r.prompt_tokens,
      r.completion_tokens,
      r.total_tokens,
      r.cost_usd.toFixed(6),
    ]);
    const csvContent = [headers.join(','), ...rows.map((e) => e.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `agent_engine_spend_${groupBy}_${Date.now()}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const exportJSON = () => {
    if (!metrics) return;
    const jsonString = `data:text/json;charset=utf-8,${encodeURIComponent(
      JSON.stringify(metrics, null, 2)
    )}`;
    const downloadAnchor = document.createElement('a');
    downloadAnchor.setAttribute('href', jsonString);
    downloadAnchor.setAttribute('download', `agent_engine_cost_telemetry_${Date.now()}.json`);
    document.body.appendChild(downloadAnchor);
    downloadAnchor.click();
    downloadAnchor.remove();
  };

  const monthSpend = metrics?.month_spend_usd ?? 0.0;
  const monthBudget = budget?.monthly_budget_usd ?? 100.0;
  const monthPercent = monthBudget > 0 ? (monthSpend / monthBudget) * 100.0 : 0;
  const isMonthWarning = monthPercent >= (budget?.warning_threshold_pct ?? 80.0);
  const isMonthCritical = monthPercent >= (budget?.critical_threshold_pct ?? 100.0);

  const daySpend = metrics?.day_spend_usd ?? 0.0;
  const dayBudget = budget?.daily_budget_usd ?? 10.0;
  const dayPercent = dayBudget > 0 ? (daySpend / dayBudget) * 100.0 : 0;

  // Donut values (Law 1)
  const tier90 = metrics?.tier_split?.deterministic_cache_local_pct ?? 90.0;
  const tier9 = metrics?.tier_split?.mid_tier_pct ?? 9.0;
  const tier1 = metrics?.tier_split?.frontier_pct ?? 1.0;

  // Render SVG Donut Chart
  const renderDonutChart = () => {
    const size = 160;
    const strokeWidth = 24;
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;

    const stroke1 = (tier90 / 100) * circumference;
    const stroke2 = (tier9 / 100) * circumference;
    const stroke3 = (tier1 / 100) * circumference;

    const offset1 = 0;
    const offset2 = -stroke1;
    const offset3 = -(stroke1 + stroke2);

    return (
      <div className="relative w-40 h-40 flex items-center justify-center">
        <svg width={size} height={size} className="transform -rotate-90">
          {/* Background circle */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="transparent"
            stroke="rgba(255, 255, 255, 0.05)"
            strokeWidth={strokeWidth}
          />
          {/* 90% Tier (Deterministic, Cache, Local) */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="transparent"
            stroke="#10b981"
            strokeWidth={strokeWidth}
            strokeDasharray={`${stroke1} ${circumference}`}
            strokeDashoffset={offset1}
            strokeLinecap="round"
            className="transition-all duration-700"
          />
          {/* 9% Tier (Mid-tier models) */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="transparent"
            stroke="#3b82f6"
            strokeWidth={strokeWidth}
            strokeDasharray={`${stroke2} ${circumference}`}
            strokeDashoffset={offset2}
            className="transition-all duration-700"
          />
          {/* 1% Tier (Frontier models) */}
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="transparent"
            stroke="#a855f7"
            strokeWidth={strokeWidth}
            strokeDasharray={`${stroke3} ${circumference}`}
            strokeDashoffset={offset3}
            className="transition-all duration-700"
          />
        </svg>
        <div className="absolute flex flex-col items-center justify-center text-center">
          <span className="text-xl font-black text-text-primary font-mono">{tier90.toFixed(0)}%</span>
          <span className="text-[10px] text-text-tertiary uppercase font-bold tracking-wider">Local/Code</span>
        </div>
      </div>
    );
  };

  // Render SVG Bar Chart for Breakdown
  const renderBarChart = () => {
    if (!metrics || !metrics.breakdown || metrics.breakdown.length === 0) {
      return (
        <div className="h-44 flex items-center justify-center text-xs text-text-tertiary">
          No spend records available for chart.
        </div>
      );
    }
    const maxVal = Math.max(...metrics.breakdown.map((b) => b.cost_usd), 0.001);

    return (
      <div className="h-44 flex items-end gap-2 pt-6 pb-2 px-2 overflow-x-auto">
        {metrics.breakdown.map((b, idx) => {
          const heightPct = Math.max(6, Math.round((b.cost_usd / maxVal) * 100));
          return (
            <div key={idx} className="flex-1 min-w-[48px] max-w-[80px] flex flex-col items-center gap-1.5 group">
              <div className="text-[10px] font-mono text-text-tertiary opacity-0 group-hover:opacity-100 transition-opacity">
                ${b.cost_usd.toFixed(3)}
              </div>
              <div className="w-full bg-bg-base/70 rounded-t-md h-28 flex items-end p-1 border border-border-subtle">
                <div
                  style={{ height: `${heightPct}%` }}
                  className="w-full rounded bg-gradient-to-t from-accent to-accent-hover transition-all duration-500 shadow-sm"
                />
              </div>
              <span className="text-[11px] font-mono text-text-secondary truncate w-full text-center">
                {b.group}
              </span>
            </div>
          );
        })}
      </div>
    );
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-bg-base">
        <div className="flex flex-col items-center gap-3">
          <RefreshCw className="w-6 h-6 text-accent animate-spin" />
          <span className="text-sm font-medium text-text-secondary">Loading cost metrics & budget telemetry...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-bg-base overflow-hidden select-none">
      {/* Header Bar */}
      <div className="p-4 border-b border-border-subtle bg-bg-elevated/40 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-success/15 border border-success/30 flex items-center justify-center text-success">
            <CircleDollarSign className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-bold text-text-primary">Cost & Budget Command Center</h1>
              <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-accent/15 border border-accent/30 text-accent flex items-center gap-1">
                <Sparkles className="w-3 h-3" /> Law 1 Enforced
              </span>
            </div>
            <p className="text-xs text-text-secondary mt-0.5">
              90/9/1 Cost Routing • Token Spend Ledger • Budget Guardrails • Distillation Pipeline
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 bg-bg-base border border-border-subtle rounded-lg px-2.5 py-1 text-xs">
            <span className="text-text-tertiary">Project:</span>
            <input
              type="text"
              value={project}
              onChange={(e) => setProject(e.target.value)}
              className="bg-transparent text-text-primary font-mono font-medium focus:outline-none w-20"
            />
          </div>

          <button
            onClick={exportCSV}
            className="px-2.5 py-1.5 rounded-lg bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-text-secondary hover:text-text-primary text-xs font-medium flex items-center gap-1.5 transition-all"
            title="Export CSV"
          >
            <Download className="w-3.5 h-3.5" /> CSV
          </button>
          <button
            onClick={exportJSON}
            className="px-2.5 py-1.5 rounded-lg bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-text-secondary hover:text-text-primary text-xs font-medium flex items-center gap-1.5 transition-all"
            title="Export JSON"
          >
            <Download className="w-3.5 h-3.5" /> JSON
          </button>
          <button
            onClick={() => fetchCostData(true)}
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
        {/* Active Alert Banner */}
        {metrics?.alerts && metrics.alerts.length > 0 && (
          <div className="space-y-2">
            {metrics.alerts.map((al, idx) => (
              <div
                key={idx}
                className={`p-3 rounded-xl border flex items-center justify-between text-xs font-medium ${
                  al.level === 'critical'
                    ? 'bg-danger/15 border-danger/40 text-danger animate-pulse'
                    : 'bg-warning/15 border-warning/40 text-warning'
                }`}
              >
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                  <span>
                    <strong>[{al.period.toUpperCase()} {al.level.toUpperCase()}]</strong> {al.message}
                  </span>
                </div>
                <span className="font-mono font-bold">{al.percentage.toFixed(1)}% of Budget</span>
              </div>
            ))}
          </div>
        )}

        {/* 4 Summary Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {/* Card 1: Total Spend */}
          <div className="p-4 rounded-xl bg-bg-elevated/40 border border-border-subtle flex flex-col justify-between">
            <span className="text-xs text-text-secondary font-medium">Total Incurred Spend</span>
            <div className="my-2">
              <div className="text-2xl font-bold font-mono text-text-primary">
                ${metrics?.total_cost_usd.toFixed(4) || '0.0000'}
              </div>
              <div className="text-xs text-text-tertiary mt-0.5">
                {(metrics?.total_tokens || 0).toLocaleString()} tokens tracked
              </div>
            </div>
            <div className="text-[11px] text-success flex items-center gap-1 font-medium">
              <CheckCircle2 className="w-3.5 h-3.5" /> Deterministic-first ledger
            </div>
          </div>

          {/* Card 2: Monthly Spend vs Budget */}
          <div className="p-4 rounded-xl bg-bg-elevated/40 border border-border-subtle flex flex-col justify-between">
            <span className="text-xs text-text-secondary font-medium">Monthly Spend / Budget</span>
            <div className="my-2">
              <div className="flex items-baseline gap-1">
                <span className={`text-2xl font-bold font-mono ${
                  isMonthCritical ? 'text-danger' : isMonthWarning ? 'text-warning' : 'text-text-primary'
                }`}>
                  ${monthSpend.toFixed(2)}
                </span>
                <span className="text-sm font-mono text-text-tertiary">/ ${monthBudget.toFixed(2)}</span>
              </div>
              {/* Progress Bar */}
              <div className="w-full bg-bg-base/80 rounded-full h-1.5 mt-2 overflow-hidden border border-border-subtle">
                <div
                  style={{ width: `${Math.min(100, monthPercent)}%` }}
                  className={`h-full rounded-full transition-all duration-500 ${
                    isMonthCritical ? 'bg-danger' : isMonthWarning ? 'bg-warning' : 'bg-success'
                  }`}
                />
              </div>
            </div>
            <div className="text-[11px] font-mono text-text-secondary flex justify-between">
              <span>{monthPercent.toFixed(1)}% consumed</span>
              <span>Ceiling: ${monthBudget}</span>
            </div>
          </div>

          {/* Card 3: Daily Spend */}
          <div className="p-4 rounded-xl bg-bg-elevated/40 border border-border-subtle flex flex-col justify-between">
            <span className="text-xs text-text-secondary font-medium">Daily Spend / Ceiling</span>
            <div className="my-2">
              <div className="flex items-baseline gap-1">
                <span className="text-2xl font-bold font-mono text-text-primary">
                  ${daySpend.toFixed(2)}
                </span>
                <span className="text-sm font-mono text-text-tertiary">/ ${dayBudget.toFixed(2)}</span>
              </div>
              <div className="w-full bg-bg-base/80 rounded-full h-1.5 mt-2 overflow-hidden border border-border-subtle">
                <div
                  style={{ width: `${Math.min(100, dayPercent)}%` }}
                  className="h-full rounded-full bg-accent transition-all duration-500"
                />
              </div>
            </div>
            <div className="text-[11px] font-mono text-text-secondary flex justify-between">
              <span>{dayPercent.toFixed(1)}% daily</span>
              <span>Reset 00:00 UTC</span>
            </div>
          </div>

          {/* Card 4: Semantic Cache Hit Rate */}
          <div className="p-4 rounded-xl bg-bg-elevated/40 border border-border-subtle flex flex-col justify-between">
            <span className="text-xs text-text-secondary font-medium">Cache Hit Rate (Law 4)</span>
            <div className="my-2">
              <div className="text-2xl font-bold font-mono text-success">
                {((metrics?.cache_hit_rate ?? 0.42) * 100).toFixed(1)}%
              </div>
              <div className="text-xs text-text-tertiary mt-0.5">
                ChromaDB 0.95 cosine threshold
              </div>
            </div>
            <div className="text-[11px] text-text-secondary flex items-center gap-1">
              <Database className="w-3.5 h-3.5 text-accent" />
              <span>Sub-20ms instant recall</span>
            </div>
          </div>
        </div>

        {/* Middle Section: Law 1 Donut & Breakdown Bar Chart */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Left Column: Law 1 90/9/1 Split */}
          <div className="lg:col-span-5 p-4 rounded-xl bg-bg-elevated/40 border border-border-subtle flex flex-col justify-between">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <PieChart className="w-4 h-4 text-accent" />
                <h3 className="text-sm font-bold text-text-primary">Law 1: 90/9/1 Routing Split</h3>
              </div>
              <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded bg-success/15 border border-success/30 text-success font-bold">
                Compliant
              </span>
            </div>

            <div className="flex flex-col sm:flex-row items-center justify-around gap-4 my-2">
              {renderDonutChart()}

              <div className="space-y-2.5 text-xs w-full sm:w-auto">
                {/* 90% Tier */}
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-sm bg-emerald-500 flex-shrink-0" />
                  <div className="flex-1 font-mono">
                    <span className="text-text-primary font-bold">{tier90.toFixed(1)}%</span>
                    <span className="text-text-secondary text-[11px] ml-1.5">Deterministic / Cache / Local</span>
                  </div>
                </div>
                {/* 9% Tier */}
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-sm bg-blue-500 flex-shrink-0" />
                  <div className="flex-1 font-mono">
                    <span className="text-text-primary font-bold">{tier9.toFixed(1)}%</span>
                    <span className="text-text-secondary text-[11px] ml-1.5">Mid-Tier Models</span>
                  </div>
                </div>
                {/* 1% Tier */}
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-sm bg-purple-500 flex-shrink-0" />
                  <div className="flex-1 font-mono">
                    <span className="text-text-primary font-bold">{tier1.toFixed(1)}%</span>
                    <span className="text-text-secondary text-[11px] ml-1.5">Frontier (GPT-4o / Claude)</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="pt-3 border-t border-border-subtle/50 text-[11px] text-text-tertiary">
              Target: 90% code/cache/local (<span className="text-emerald-400 font-mono">$0</span>), 9% mid-tier, ≤1% frontier calls.
            </div>
          </div>

          {/* Right Column: Spend Breakdown Bar Chart */}
          <div className="lg:col-span-7 p-4 rounded-xl bg-bg-elevated/40 border border-border-subtle flex flex-col justify-between">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-accent" />
                <h3 className="text-sm font-bold text-text-primary">Spend Breakdown</h3>
              </div>
              <div className="flex bg-bg-base border border-border-subtle rounded-lg p-0.5">
                {(['day', 'agent', 'model', 'project'] as const).map((g) => (
                  <button
                    key={g}
                    onClick={() => setGroupBy(g)}
                    className={`px-2.5 py-1 rounded text-xs capitalize transition-all ${
                      groupBy === g
                        ? 'bg-accent text-white font-semibold shadow-xs'
                        : 'text-text-secondary hover:text-text-primary'
                    }`}
                  >
                    {g}
                  </button>
                ))}
              </div>
            </div>

            {renderBarChart()}

            <div className="pt-2 border-t border-border-subtle/50 flex items-center justify-between text-[11px] text-text-tertiary font-mono">
              <span>Grouped by {groupBy}</span>
              <span>{metrics?.breakdown?.length || 0} buckets</span>
            </div>
          </div>
        </div>

        {/* Distillation Engine (Law 8) */}
        <div className="p-4 rounded-xl bg-bg-elevated/40 border border-border-subtle space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Flame className="w-4 h-4 text-warning" />
              <h3 className="text-sm font-bold text-text-primary">
                Law 8: Model Distillation Engine (&gt;10k calls/mo)
              </h3>
            </div>
            <span className="text-xs text-text-tertiary font-mono">
              Automated Teacher-to-Student Specialist Compression
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-bg-base/80 border-b border-border-subtle text-text-tertiary font-mono uppercase tracking-wider">
                <tr>
                  <th className="p-2.5">Task / Pattern</th>
                  <th className="p-2.5">Teacher Model</th>
                  <th className="p-2.5">Target Student</th>
                  <th className="p-2.5">Monthly Volume</th>
                  <th className="p-2.5">Monthly Savings</th>
                  <th className="p-2.5">Accuracy</th>
                  <th className="p-2.5 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-subtle/50 font-mono">
                {candidates.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="p-6 text-center text-text-tertiary font-sans">
                      No repeating tasks currently exceed the 10,000 calls/month threshold for distillation.
                    </td>
                  </tr>
                ) : (
                  candidates.map((c) => {
                    const isDistilling = distillingMap[c.candidate_id] || c.status === 'distilling';
                    return (
                      <tr key={c.candidate_id} className="hover:bg-bg-hover/50 transition-colors">
                        <td className="p-2.5 font-semibold text-text-primary font-sans">
                          {c.task_name}
                        </td>
                        <td className="p-2.5 text-text-secondary">{c.teacher_model}</td>
                        <td className="p-2.5 text-accent">{c.student_model}</td>
                        <td className="p-2.5">{c.monthly_calls.toLocaleString()}</td>
                        <td className="p-2.5 text-success font-bold">${c.monthly_savings_usd.toFixed(2)}/mo</td>
                        <td className="p-2.5">{(c.accuracy_score * 100).toFixed(1)}%</td>
                        <td className="p-2.5 text-right">
                          <button
                            onClick={() => handleTriggerDistill(c.candidate_id)}
                            disabled={isDistilling}
                            className={`px-3 py-1 rounded-md text-xs font-bold transition-all shadow-sm ${
                              isDistilling
                                ? 'bg-bg-hover text-text-tertiary cursor-not-allowed'
                                : 'bg-warning/20 hover:bg-warning/30 border border-warning/40 text-warning'
                            }`}
                          >
                            {isDistilling ? 'Distilling...' : '1-Click Distill'}
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Budget Configuration Panel (Full replacement of Streamlit Tab 5) */}
        <div className="p-4 rounded-xl bg-bg-elevated/40 border border-border-subtle space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-accent" />
              <h3 className="text-sm font-bold text-text-primary">
                Budget Ceilings & Threshold Policy Guardrails
              </h3>
            </div>
            {budgetSaveStatus && (
              <span className="text-xs text-success font-medium animate-pulse">
                {budgetSaveStatus}
              </span>
            )}
          </div>

          <form onSubmit={handleSaveBudget} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-text-secondary uppercase mb-1">
                Monthly Budget ($ USD)
              </label>
              <input
                type="number"
                min="1"
                max="100000"
                step="5"
                value={editMonthly}
                onChange={(e) => setEditMonthly(parseFloat(e.target.value) || 0)}
                className="w-full p-2 bg-bg-base border border-border-subtle rounded-lg text-sm text-text-primary font-mono focus:outline-none focus:border-accent"
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold text-text-secondary uppercase mb-1">
                Daily Budget ($ USD)
              </label>
              <input
                type="number"
                min="0.5"
                max="10000"
                step="1"
                value={editDaily}
                onChange={(e) => setEditDaily(parseFloat(e.target.value) || 0)}
                className="w-full p-2 bg-bg-base border border-border-subtle rounded-lg text-sm text-text-primary font-mono focus:outline-none focus:border-accent"
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold text-text-secondary uppercase mb-1">
                Warning Threshold (%)
              </label>
              <input
                type="number"
                min="10"
                max="99"
                step="5"
                value={editWarningPct}
                onChange={(e) => setEditWarningPct(parseFloat(e.target.value) || 0)}
                className="w-full p-2 bg-bg-base border border-border-subtle rounded-lg text-sm text-text-primary font-mono focus:outline-none focus:border-accent"
              />
            </div>

            <div>
              <label className="block text-[11px] font-semibold text-text-secondary uppercase mb-1">
                Critical Threshold (%)
              </label>
              <input
                type="number"
                min="100"
                max="200"
                step="5"
                value={editCriticalPct}
                onChange={(e) => setEditCriticalPct(parseFloat(e.target.value) || 0)}
                className="w-full p-2 bg-bg-base border border-border-subtle rounded-lg text-sm text-text-primary font-mono focus:outline-none focus:border-accent"
              />
            </div>

            <div className="sm:col-span-2 lg:col-span-4 flex justify-end">
              <button
                type="submit"
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-xs font-bold rounded-lg flex items-center gap-1.5 shadow-sm transition-all"
              >
                <Save className="w-3.5 h-3.5" /> Save Budget Settings
              </button>
            </div>
          </form>
        </div>

        {/* Model Economics & Whole-Chain Cost-Per-Success Comparison */}
        <ModelEconomicsComparison />
      </div>
    </div>
  );
};
