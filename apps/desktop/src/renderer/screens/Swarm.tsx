import React, { useState, useEffect } from 'react';
import {
  Users,
  Play,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  Clock,
  Coins,
  Copy,
  Check,
  RefreshCw,
  Code2,
  ShieldAlert,
  FileSearch,
  Bot,
  Zap,
  Cpu,
  Layers,
} from 'lucide-react';
import { Mode, ModelTier, SwarmCase, SwarmRunResult, SwarmAgentProgress } from '../types';
import { sidecarClient } from '../api/client';

export interface SwarmScreenProps {
  onSelectMode: (mode: Mode) => void;
  activeModel: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
}

const FALLBACK_CASES: SwarmCase[] = [
  {
    id: 'build_deploy_api',
    title: 'Build & deploy an API',
    tagline: '4 agents: architect, coder, tester, deployer',
    description: 'Architect schemas, write endpoint handlers, generate test suites, and draft deployment configs.',
    default_prompt: 'Design and build a high-performance REST API for user profile and token management with caching.',
    agents: [
      { id: 'architect', name: 'Architect', role: 'API Architecture & Data Contracts', model_tier: 'instant', estimated_cost_usd: 0.001 },
      { id: 'coder', name: 'Coder', role: 'Backend Endpoint Implementation', model_tier: 'instant', estimated_cost_usd: 0.0015 },
      { id: 'tester', name: 'Tester', role: 'Pytest & Integration Validation', model_tier: 'instant', estimated_cost_usd: 0.0008 },
      { id: 'deployer', name: 'Deployer', role: 'Docker & Service Deployment Manifest', model_tier: 'instant', estimated_cost_usd: 0.0007 },
    ],
  },
  {
    id: 'deep_code_review',
    title: 'Deep code review',
    tagline: '3 agents: security, lint, fix',
    description: 'Comprehensive multi-perspective audit covering security boundaries, code cleanliness, and fix generation.',
    default_prompt: 'Perform deep security audit and linter analysis on authentication and session storage modules.',
    agents: [
      { id: 'security', name: 'Security Auditor', role: 'Security Boundaries & Vulnerability Scanner', model_tier: 'instant', estimated_cost_usd: 0.0015 },
      { id: 'lint', name: 'Linter & Style', role: 'Code Quality & Performance Auditor', model_tier: 'instant', estimated_cost_usd: 0.0008 },
      { id: 'fix', name: 'Remediation Engineer', role: 'Automated Staged Patch Generator', model_tier: 'instant', estimated_cost_usd: 0.0012 },
    ],
  },
  {
    id: 'market_research',
    title: 'Market research report',
    tagline: '4 agents: search, analyst, writer, editor',
    description: 'Autonomous research team conducting market landscape analysis, trend forecasting, and executive drafting.',
    default_prompt: 'Analyze local-first AI developer tooling landscape, open-weights trends, and privacy compliance needs.',
    agents: [
      { id: 'search', name: 'Researcher', role: 'Information Gathering & Source Indexing', model_tier: 'instant', estimated_cost_usd: 0.001 },
      { id: 'analyst', name: 'Market Analyst', role: 'Quantitative & Strategic Analysis', model_tier: 'instant', estimated_cost_usd: 0.001 },
      { id: 'writer', name: 'Report Drafter', role: 'Comprehensive Section Drafter', model_tier: 'instant', estimated_cost_usd: 0.0012 },
      { id: 'editor', name: 'Executive Editor', role: 'Fact-Check & Executive Synthesis', model_tier: 'instant', estimated_cost_usd: 0.0008 },
    ],
  },
];

export const Swarm: React.FC<SwarmScreenProps> = () => {
  const [cases, setCases] = useState<SwarmCase[]>(FALLBACK_CASES);
  const [selectedCaseId, setSelectedCaseId] = useState<string>('build_deploy_api');
  const [prompt, setPrompt] = useState<string>(FALLBACK_CASES[0].default_prompt);
  const [modelTier, setModelTier] = useState<'instant' | 'swarm-high'>('instant');
  const [estimatedCost, setEstimatedCost] = useState<number>(0.004);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [runResult, setRunResult] = useState<SwarmRunResult | null>(null);
  const [activeTab, setActiveTab] = useState<'synthesis' | 'agents'>('synthesis');
  const [copied, setCopied] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Load cases from sidecar on mount
  useEffect(() => {
    let mounted = true;
    const fetchCases = async () => {
      const data = await sidecarClient.listSwarmCases();
      if (mounted && data && data.length > 0) {
        setCases(data);
      }
    };
    fetchCases();
    return () => {
      mounted = false;
    };
  }, []);

  const activeCase = cases.find((c) => c.id === selectedCaseId) || cases[0];

  // Recalculate estimated cost
  useEffect(() => {
    let mounted = true;
    const calcCost = async () => {
      const est = await sidecarClient.estimateSwarmCost({
        case_id: selectedCaseId,
        agents: activeCase.agents,
        model_tier: modelTier,
      });
      if (mounted && est) {
        setEstimatedCost(est.estimated_cost_usd);
      }
    };
    calcCost();
    return () => {
      mounted = false;
    };
  }, [selectedCaseId, modelTier, activeCase]);

  const handleSelectCase = (c: SwarmCase) => {
    setSelectedCaseId(c.id);
    setPrompt(c.default_prompt);
    setError(null);
  };

  const handleDispatch = async () => {
    if (!prompt.trim() || isRunning) return;
    setIsRunning(true);
    setError(null);

    // Initial optimistic progress
    const simulatedInitial: SwarmAgentProgress[] = activeCase.agents.map((a) => ({
      agent_id: a.id,
      agent_name: a.name,
      role: a.role,
      model_tier: modelTier,
      status: 'running',
      progress_percent: 50,
      output: '',
      cost_usd: a.estimated_cost_usd,
      execution_time_ms: 0,
    }));

    setRunResult({
      swarm_id: 'pending...',
      prompt,
      model_tier: modelTier,
      status: 'completed',
      agent_results: simulatedInitial,
      aggregated_output: 'Dispatching parallel agents...',
      total_cost_usd: estimatedCost,
      total_time_ms: 0,
      created_at: new Date().toISOString(),
    });

    try {
      const result = await sidecarClient.runSwarm({
        prompt,
        case_id: selectedCaseId,
        agents: activeCase.agents,
        model_tier: modelTier,
      });
      setRunResult(result);
    } catch (err: any) {
      setError(err?.message || 'Swarm execution failed.');
    } finally {
      setIsRunning(false);
    }
  };

  const handleCopy = () => {
    if (!runResult) return;
    navigator.clipboard.writeText(runResult.aggregated_output);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getCaseIcon = (id: string) => {
    switch (id) {
      case 'build_deploy_api':
        return <Code2 className="w-5 h-5 text-accent" />;
      case 'deep_code_review':
        return <ShieldAlert className="w-5 h-5 text-amber-400" />;
      case 'market_research':
        return <FileSearch className="w-5 h-5 text-emerald-400" />;
      default:
        return <Bot className="w-5 h-5 text-accent" />;
    }
  };

  return (
    <div className="h-full flex flex-col bg-bg-base overflow-y-auto">
      {/* Top Header */}
      <div className="px-8 pt-8 pb-6 border-b border-border-subtle bg-bg-elevated/30">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-accent/10 border border-accent/20 flex items-center justify-center text-accent shadow-sm">
              <Users className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold text-text-primary tracking-tight">Swarm</h1>
                <span className="px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider rounded-full bg-accent/15 text-accent border border-accent/30">
                  Multi-Agent
                </span>
              </div>
              <p className="text-sm text-text-secondary mt-0.5">
                Assign a task to your AI team • Parallel execution across specialized micro-agents
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Model Tier Selector */}
            <div className="flex items-center bg-bg-base p-1 rounded-xl border border-border-subtle shadow-sm">
              <button
                onClick={() => setModelTier('instant')}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 ${
                  modelTier === 'instant'
                    ? 'bg-bg-elevated text-accent font-semibold shadow-xs'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                <Zap className="w-3.5 h-3.5" />
                <span>Instant (90%)</span>
              </button>
              <button
                onClick={() => setModelTier('swarm-high')}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 ${
                  modelTier === 'swarm-high'
                    ? 'bg-accent text-bg-base font-semibold shadow-xs'
                    : 'text-text-secondary hover:text-text-primary'
                }`}
              >
                <Cpu className="w-3.5 h-3.5" />
                <span>Swarm High (Reasoning)</span>
              </button>
            </div>

            {/* Cost Estimator Badge */}
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-bg-base border border-border-subtle text-xs font-mono text-text-secondary">
              <Coins className="w-3.5 h-3.5 text-amber-400" />
              <span>Estimated: ${estimatedCost.toFixed(4)}</span>
            </div>
          </div>
        </div>

        {/* Featured Cases Section */}
        <div className="mt-6">
          <div className="text-xs font-semibold text-text-tertiary uppercase tracking-wider mb-3">
            Featured Swarm Teams
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {cases.map((c) => {
              const isSelected = c.id === selectedCaseId;
              return (
                <div
                  key={c.id}
                  onClick={() => handleSelectCase(c)}
                  className={`p-4 rounded-2xl border transition-all cursor-pointer select-none relative group ${
                    isSelected
                      ? 'bg-bg-elevated border-accent shadow-md ring-1 ring-accent/30'
                      : 'bg-bg-base border-border-subtle hover:border-border-strong hover:bg-bg-elevated/50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3 mb-2">
                    <div className="flex items-center gap-2.5">
                      <div className="p-2 rounded-xl bg-bg-elevated border border-border-subtle">
                        {getCaseIcon(c.id)}
                      </div>
                      <div>
                        <h3 className="text-sm font-semibold text-text-primary">{c.title}</h3>
                        <p className="text-[11px] text-accent font-medium">{c.tagline}</p>
                      </div>
                    </div>
                  </div>
                  <p className="text-xs text-text-secondary line-clamp-2 mb-3 leading-relaxed">
                    {c.description}
                  </p>
                  <div className="flex items-center justify-between text-[11px] pt-2 border-t border-border-subtle/50 text-text-tertiary">
                    <div className="flex items-center gap-1.5">
                      <Users className="w-3 h-3" />
                      <span>{c.agents.length} Specialized Agents</span>
                    </div>
                    <span className="font-mono text-text-secondary">
                      ~${c.agents.reduce((acc, a) => acc + a.estimated_cost_usd, 0).toFixed(4)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Main Workspace Body */}
      <div className="p-8 flex-1 flex flex-col gap-6 max-w-6xl w-full mx-auto">
        {/* Task Dispatch Input Box */}
        <div className="p-5 rounded-2xl bg-bg-elevated border border-border-strong shadow-lg">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-1 rounded-lg bg-accent/15 text-accent text-xs font-semibold flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5" />
                <span>Swarm Mode</span>
              </span>
              <span className="text-xs text-text-tertiary">•</span>
              <span className="text-xs font-medium text-text-secondary">
                Selected Team: <strong className="text-text-primary">{activeCase.title}</strong> ({activeCase.agents.length} agents)
              </span>
            </div>
            <div className="text-xs text-text-tertiary">
              Cost Router: <strong className="text-text-secondary">Law 1 (90/9/1)</strong>
            </div>
          </div>

          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            disabled={isRunning}
            placeholder="Describe the objective for your swarm of agents..."
            rows={3}
            className="w-full bg-bg-base border border-border-subtle rounded-xl p-3.5 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent resize-none transition-all"
          />

          <div className="flex items-center justify-between mt-3">
            <div className="flex items-center gap-2 text-xs text-text-tertiary">
              <span>Parallel execution merges outputs automatically.</span>
            </div>
            <button
              onClick={handleDispatch}
              disabled={isRunning || !prompt.trim()}
              className={`px-5 py-2.5 rounded-xl font-medium text-xs flex items-center gap-2 shadow-md transition-all ${
                isRunning || !prompt.trim()
                  ? 'bg-bg-base text-text-tertiary border border-border-subtle cursor-not-allowed'
                  : 'bg-accent hover:bg-accent/90 text-bg-base cursor-pointer hover:scale-[1.01]'
              }`}
            >
              {isRunning ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  <span>Dispatching Swarm...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-current" />
                  <span>Dispatch Swarm</span>
                </>
              )}
            </button>
          </div>
        </div>

        {error && (
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Live Multi-Agent Progress Strips */}
        {runResult && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xs font-semibold text-text-tertiary uppercase tracking-wider flex items-center gap-2">
                <Layers className="w-3.5 h-3.5" />
                <span>Live Agent Execution Strips</span>
              </h2>
              <div className="text-xs font-mono text-text-secondary">
                {runResult.agent_results.filter((a) => a.status === 'completed').length} / {runResult.agent_results.length} Completed
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {runResult.agent_results.map((agent) => {
                const isCompleted = agent.status === 'completed';
                const isFailed = agent.status === 'failed';
                return (
                  <div
                    key={agent.agent_id}
                    className="p-3.5 rounded-xl bg-bg-elevated border border-border-subtle flex flex-col gap-2 relative overflow-hidden shadow-xs"
                  >
                    {/* Top strip progress bar */}
                    <div className="absolute top-0 left-0 right-0 h-1 bg-border-subtle">
                      <div
                        className={`h-full transition-all duration-500 ${
                          isCompleted
                            ? 'bg-emerald-400 w-full'
                            : isFailed
                            ? 'bg-rose-400 w-full'
                            : 'bg-accent animate-pulse w-2/3'
                        }`}
                      />
                    </div>

                    <div className="flex items-center justify-between gap-3 pt-1">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="w-8 h-8 rounded-lg bg-bg-base border border-border-subtle flex items-center justify-center text-text-primary text-xs font-bold shrink-0">
                          {agent.agent_name.slice(0, 1)}
                        </div>
                        <div className="min-w-0">
                          <h4 className="text-xs font-semibold text-text-primary truncate">
                            {agent.agent_name}
                          </h4>
                          <p className="text-[11px] text-text-tertiary truncate">{agent.role}</p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2 shrink-0">
                        <span className="px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-[10px] font-mono text-text-secondary">
                          {agent.model_tier}
                        </span>
                        {isCompleted && (
                          <span className="flex items-center gap-1 text-[11px] text-emerald-400 font-medium">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            <span>Done</span>
                          </span>
                        )}
                        {isFailed && (
                          <span className="flex items-center gap-1 text-[11px] text-rose-400 font-medium">
                            <AlertTriangle className="w-3.5 h-3.5" />
                            <span>Failed</span>
                          </span>
                        )}
                        {!isCompleted && !isFailed && (
                          <span className="flex items-center gap-1 text-[11px] text-accent font-medium">
                            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                            <span>Running</span>
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-[11px] text-text-tertiary font-mono pt-1">
                      <div className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        <span>{agent.execution_time_ms ? `${agent.execution_time_ms}ms` : 'running...'}</span>
                      </div>
                      <div className="flex items-center gap-1 text-text-secondary">
                        <Coins className="w-3 h-3 text-amber-400" />
                        <span>${agent.cost_usd.toFixed(4)}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Aggregated Output Section */}
        {runResult && !isRunning && (
          <div className="p-6 rounded-2xl bg-bg-elevated border border-border-strong shadow-lg flex flex-col gap-4">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-border-subtle">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl bg-accent/10 border border-accent/20 text-accent">
                  <Sparkles className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-text-primary">Aggregated Output & Attribution</h3>
                  <p className="text-xs text-text-secondary">
                    Status: <span className="font-semibold capitalize text-emerald-400">{runResult.status.replace('_', ' ')}</span> • Total Cost: ${runResult.total_cost_usd.toFixed(4)} • Duration: {runResult.total_time_ms.toFixed(0)}ms
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {/* Tab Switcher */}
                <div className="flex items-center bg-bg-base p-0.5 rounded-xl border border-border-subtle text-xs">
                  <button
                    onClick={() => setActiveTab('synthesis')}
                    className={`px-3 py-1 rounded-lg transition-all ${
                      activeTab === 'synthesis'
                        ? 'bg-bg-elevated text-text-primary font-semibold shadow-xs'
                        : 'text-text-secondary hover:text-text-primary'
                    }`}
                  >
                    Synthesis
                  </button>
                  <button
                    onClick={() => setActiveTab('agents')}
                    className={`px-3 py-1 rounded-lg transition-all ${
                      activeTab === 'agents'
                        ? 'bg-bg-elevated text-text-primary font-semibold shadow-xs'
                        : 'text-text-secondary hover:text-text-primary'
                    }`}
                  >
                    Agents ({runResult.agent_results.length})
                  </button>
                </div>

                <button
                  onClick={handleCopy}
                  className="px-3 py-1.5 rounded-lg bg-bg-base hover:bg-bg-elevated border border-border-subtle text-xs font-medium text-text-secondary hover:text-text-primary transition-all flex items-center gap-1.5"
                >
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  <span>{copied ? 'Copied' : 'Copy'}</span>
                </button>
              </div>
            </div>

            {activeTab === 'synthesis' ? (
              <div className="prose prose-invert max-w-none text-sm text-text-secondary leading-relaxed bg-bg-base p-5 rounded-xl border border-border-subtle font-sans whitespace-pre-wrap">
                {runResult.aggregated_output}
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                {runResult.agent_results.map((res) => (
                  <div key={res.agent_id} className="p-4 rounded-xl bg-bg-base border border-border-subtle">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-text-primary text-xs">{res.agent_name}</span>
                        <span className="text-xs text-text-tertiary">({res.role})</span>
                      </div>
                      <span className="font-mono text-xs text-text-secondary">${res.cost_usd.toFixed(4)}</span>
                    </div>
                    <div className="text-xs text-text-secondary whitespace-pre-wrap bg-bg-elevated/50 p-3 rounded-lg border border-border-subtle/50 font-mono">
                      {res.output || res.error || 'No output generated.'}
                    </div>
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
