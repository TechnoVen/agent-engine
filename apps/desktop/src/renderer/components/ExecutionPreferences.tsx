import React, { useState, useRef, useEffect } from 'react';
import {
  ChevronDown,
  Check,
  ShieldCheck,
  Cloud,
  Globe,
  SlidersHorizontal,
  Sparkles,
  Coins,
  Zap,
} from 'lucide-react';
import {
  PrivacyBoundary,
  RoutingObjective,
  PrivacyBoundaryOption,
  RoutingObjectiveOption,
} from '../types';

export interface ExecutionPreferencesProps {
  privacyBoundary: PrivacyBoundary;
  onSelectPrivacyBoundary: (boundary: PrivacyBoundary) => void;
  routingObjective: RoutingObjective;
  onSelectRoutingObjective: (objective: RoutingObjective) => void;
  className?: string;
}

export const PRIVACY_OPTIONS: PrivacyBoundaryOption[] = [
  {
    id: 'local_only',
    label: 'Local Only',
    description: 'Task data stays on this device.',
  },
  {
    id: 'approved_cloud',
    label: 'Approved Cloud',
    description: 'Only cloud providers you have explicitly approved may receive task data.',
  },
  {
    id: 'any_configured',
    label: 'Any Configured',
    description: 'Any otherwise permitted configured provider may be selected.',
  },
];

export const ROUTING_OPTIONS: RoutingObjectiveOption[] = [
  {
    id: 'balanced',
    label: 'Balanced',
    description: 'Balances quality, cost and responsiveness.',
  },
  {
    id: 'quality_first',
    label: 'Quality First',
    description: 'Prioritizes capability and accuracy.',
  },
  {
    id: 'cost_first',
    label: 'Cost First',
    description: 'Prioritizes lowest cost and local execution.',
  },
  {
    id: 'latency_first',
    label: 'Latency First',
    description: 'Prioritizes fastest time-to-first-token.',
  },
];

export const ExecutionPreferences: React.FC<ExecutionPreferencesProps> = ({
  privacyBoundary,
  onSelectPrivacyBoundary,
  routingObjective,
  onSelectRoutingObjective,
  className = '',
}) => {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [open]);

  const currentPrivacy =
    PRIVACY_OPTIONS.find((p) => p.id === privacyBoundary) || PRIVACY_OPTIONS[0];
  const currentRouting =
    ROUTING_OPTIONS.find((r) => r.id === routingObjective) || ROUTING_OPTIONS[0];

  // Derive truthful compact label
  const getSummaryLabel = () => {
    if (privacyBoundary === 'local_only' && routingObjective === 'balanced') {
      return 'Automatic · Local preferred';
    }
    return `${currentPrivacy.label} · ${currentRouting.label}`;
  };

  const getPrivacyIcon = (id: PrivacyBoundary) => {
    switch (id) {
      case 'local_only':
        return <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />;
      case 'approved_cloud':
        return <Cloud className="w-3.5 h-3.5 text-blue-400" />;
      case 'any_configured':
        return <Globe className="w-3.5 h-3.5 text-accent" />;
    }
  };

  const getRoutingIcon = (id: RoutingObjective) => {
    switch (id) {
      case 'balanced':
        return <SlidersHorizontal className="w-3.5 h-3.5 text-accent" />;
      case 'quality_first':
        return <Sparkles className="w-3.5 h-3.5 text-purple-400" />;
      case 'cost_first':
        return <Coins className="w-3.5 h-3.5 text-emerald-400" />;
      case 'latency_first':
        return <Zap className="w-3.5 h-3.5 text-amber-400" />;
    }
  };

  return (
    <div ref={containerRef} className={`relative inline-block ${className}`}>
      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-label="Execution preferences"
        aria-expanded={open}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-bg-elevated hover:bg-bg-hover border border-border-subtle hover:border-border-strong text-xs text-text-secondary hover:text-text-primary transition-all select-none"
      >
        {getPrivacyIcon(privacyBoundary)}
        <span className="font-medium">{getSummaryLabel()}</span>
        <ChevronDown className="w-3 h-3 text-text-tertiary" />
      </button>

      {/* Disclosed Preferences Popover */}
      {open && (
        <div className="absolute right-0 bottom-full mb-1.5 sm:bottom-auto sm:top-full sm:mt-1.5 w-80 bg-bg-elevated border border-border-strong rounded-lg shadow-2xl p-2 z-50 animate-in fade-in duration-100 text-xs select-none">
          <div className="px-2 py-1 font-semibold text-text-primary border-b border-border-subtle/80 flex items-center justify-between">
            <span>Execution Preferences</span>
            <span className="text-[10px] font-mono text-text-tertiary uppercase">Policy</span>
          </div>

          {/* Privacy Section */}
          <div className="mt-2 space-y-1">
            <div className="px-2 text-[10px] uppercase font-semibold text-text-tertiary tracking-wider">
              Privacy Boundary
            </div>
            {PRIVACY_OPTIONS.map((opt) => {
              const selected = privacyBoundary === opt.id;
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => onSelectPrivacyBoundary(opt.id)}
                  className={`w-full text-left p-2 rounded-md hover:bg-bg-hover flex items-start justify-between gap-2 transition-colors ${
                    selected ? 'bg-bg-base/60 border border-border-subtle' : ''
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <div className="mt-0.5">{getPrivacyIcon(opt.id)}</div>
                    <div>
                      <div className="font-medium text-text-primary flex items-center gap-1.5">
                        {opt.label}
                      </div>
                      <div className="text-[11px] text-text-secondary mt-0.5 leading-snug">
                        {opt.description}
                      </div>
                    </div>
                  </div>
                  {selected && <Check className="w-3.5 h-3.5 text-accent flex-shrink-0 mt-0.5" />}
                </button>
              );
            })}
          </div>

          {/* Routing Section */}
          <div className="mt-3 pt-2 border-t border-border-subtle/60 space-y-1">
            <div className="px-2 text-[10px] uppercase font-semibold text-text-tertiary tracking-wider">
              Routing Objective
            </div>
            {ROUTING_OPTIONS.map((opt) => {
              const selected = routingObjective === opt.id;
              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => onSelectRoutingObjective(opt.id)}
                  className={`w-full text-left p-2 rounded-md hover:bg-bg-hover flex items-start justify-between gap-2 transition-colors ${
                    selected ? 'bg-bg-base/60 border border-border-subtle' : ''
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <div className="mt-0.5">{getRoutingIcon(opt.id)}</div>
                    <div>
                      <div className="font-medium text-text-primary flex items-center gap-1.5">
                        {opt.label}
                      </div>
                      <div className="text-[11px] text-text-secondary mt-0.5 leading-snug">
                        {opt.description}
                      </div>
                    </div>
                  </div>
                  {selected && <Check className="w-3.5 h-3.5 text-accent flex-shrink-0 mt-0.5" />}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
