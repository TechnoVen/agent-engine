import React, { useState } from 'react';
import {
  ChevronDown,
  Check,
  Sparkles,
  Zap,
  Brain,
  WifiOff,
} from 'lucide-react';
import { Mode, ModelTier, ModelTierOption, SidecarHealth } from '../types';

interface TopBarProps {
  activeMode: Mode;
  activeModel: ModelTier;
  onSelectModel: (tier: ModelTier) => void;
  health: SidecarHealth;
}

const MODEL_OPTIONS: ModelTierOption[] = [
  {
    id: 'instant',
    label: 'Instant High',
    description: 'Ultra-fast local Gemma 2 9B / Claude 3.5 Haiku',
    costPer1k: '$0.0002 / 1k',
  },
  {
    id: 'swarm',
    label: 'K3 Swarm High',
    description: 'Balanced multi-agent Flash & Sonnet 3.5',
    costPer1k: '$0.0015 / 1k',
  },
  {
    id: 'reasoning',
    label: 'K3 High',
    description: 'Frontier deep reasoning (Claude 3.5 Sonnet / GPT-4o)',
    costPer1k: '$0.0080 / 1k',
  },
];

export const TopBar: React.FC<TopBarProps> = ({
  activeMode,
  activeModel,
  onSelectModel,
  health,
}) => {
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);

  const currentModel = MODEL_OPTIONS.find((m) => m.id === activeModel) || MODEL_OPTIONS[0];

  const getModeTitle = (mode: Mode) => {
    switch (mode) {
      case 'home':
        return 'Chat';
      case 'agent':
        return "Nadir's Agent";
      case 'tasks':
        return 'Scheduled Tasks';
      case 'swarm':
        return 'Swarm Studio';
      case 'workflows':
        return 'Workflow Builder';
      case 'code':
        return 'Kimi Code Mode';
      case 'deep-research':
        return 'Deep Research';
      case 'docs':
        return 'Document Writer';
      case 'sheets':
        return 'Sheets & Analysis';
      case 'slides':
        return 'Presentation Slides';
      case 'websites':
        return 'Website Builder';
      case 'design':
        return 'Design Studio';
      case 'diagrams':
        return 'Architecture Diagrams';
      case 'channels':
        return 'Channels Bridge';
      case 'skills':
        return 'Skills & Adapters';
      case 'marketplace':
        return 'Agent Marketplace';
      case 'cost':
        return 'Cost Dashboard';
      case 'policies':
        return 'Policies & Approval Queue';
      case 'benchmarks':
        return 'Model Eval & Benchmarks';
      case 'settings':
        return 'Settings';
      case 'projects':
        return 'Projects & Workspaces';
      default:
        return 'Agent Engine';
    }
  };

  return (
    <header className="h-12 bg-bg-elevated border-b border-border-subtle px-4 flex items-center justify-between select-none">
      {/* Left: Mode Title */}
      <div className="flex items-center gap-3">
        <h1 className="text-sm font-semibold text-text-primary tracking-tight">
          {getModeTitle(activeMode)}
        </h1>
      </div>

      {/* Right: Model Tier Dropdown & Sidecar Status */}
      <div className="flex items-center gap-3">
        {/* Model Tier Selector */}
        <div className="relative">
          <button
            onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
            className="flex items-center gap-2 px-2.5 py-1 bg-bg-base border border-border-strong rounded-md text-xs text-text-primary hover:border-accent transition-colors"
          >
            {activeModel === 'instant' && <Zap className="w-3.5 h-3.5 text-warning" />}
            {activeModel === 'swarm' && <Sparkles className="w-3.5 h-3.5 text-accent" />}
            {activeModel === 'reasoning' && <Brain className="w-3.5 h-3.5 text-success" />}
            <span className="font-medium">{currentModel.label}</span>
            <ChevronDown className="w-3 h-3 text-text-tertiary" />
          </button>

          {modelDropdownOpen && (
            <div className="absolute right-0 mt-1.5 w-64 bg-bg-elevated border border-border-strong rounded-lg shadow-xl py-1 z-50">
              <div className="px-3 py-1.5 text-[10px] uppercase font-semibold text-text-tertiary tracking-wider border-b border-border-subtle">
                Execution Model Tier
              </div>
              {MODEL_OPTIONS.map((opt) => (
                <button
                  key={opt.id}
                  onClick={() => {
                    onSelectModel(opt.id);
                    setModelDropdownOpen(false);
                  }}
                  className="w-full text-left px-3 py-2 hover:bg-bg-hover flex items-start justify-between gap-2 transition-colors"
                >
                  <div>
                    <div className="text-xs font-medium text-text-primary flex items-center gap-1.5">
                      {opt.label}
                      <span className="text-[10px] text-text-tertiary font-mono">
                        {opt.costPer1k}
                      </span>
                    </div>
                    <div className="text-[11px] text-text-secondary mt-0.5">
                      {opt.description}
                    </div>
                  </div>
                  {activeModel === opt.id && (
                    <Check className="w-4 h-4 text-accent flex-shrink-0 mt-0.5" />
                  )}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Sidecar Status Indicator */}
        <div
          title={`Python Sidecar: ${health.status} (${health.engine || 'FastAPI'})`}
          className="flex items-center gap-1.5 px-2 py-1 bg-bg-base border border-border-subtle rounded-md text-xs font-mono"
        >
          {health.status === 'healthy' && (
            <>
              <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
              <span className="text-[11px] text-text-secondary">Sidecar 8000</span>
            </>
          )}
          {health.status === 'degraded' && (
            <>
              <span className="w-2 h-2 rounded-full bg-warning" />
              <span className="text-[11px] text-warning">Degraded</span>
            </>
          )}
          {health.status === 'offline' && (
            <>
              <WifiOff className="w-3 h-3 text-danger" />
              <span className="text-[11px] text-danger">Offline</span>
            </>
          )}
        </div>
      </div>
    </header>
  );
};
