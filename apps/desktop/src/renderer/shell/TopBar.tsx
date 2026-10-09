import React, { useState, useEffect, useRef } from 'react';
import {
  ChevronDown,
  AlertTriangle,
  Gauge,
  Cpu,
  Server,
  Database,
  Terminal,
  Cloud,
} from 'lucide-react';
import {
  Mode,
  ModelTier,
  SidecarHealth,
  HardwareTelemetry,
  PrivacyBoundary,
  RoutingObjective,
} from '../types';
import { sidecarClient } from '../api/client';

export interface TopBarProps {
  activeMode: Mode;
  health: SidecarHealth;
  isBusy?: boolean;
  projectName?: string;
  onOpenDiagnostics?: () => void;
  /** @deprecated Legacy compatibility prop */
  routingObjective?: RoutingObjective;
  /** @deprecated Legacy compatibility prop */
  onSelectRoutingObjective?: (objective: RoutingObjective) => void;
  /** @deprecated Legacy compatibility prop */
  privacyBoundary?: PrivacyBoundary;
  /** @deprecated Legacy compatibility prop */
  onSelectPrivacyBoundary?: (boundary: PrivacyBoundary) => void;
  /** @deprecated Legacy compatibility prop */
  activeModel?: ModelTier;
  /** @deprecated Legacy compatibility prop */
  onSelectModel?: (tier: ModelTier) => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  activeMode,
  health,
  isBusy = false,
  projectName,
  onOpenDiagnostics,
}) => {
  const [statusPopoverOpen, setStatusPopoverOpen] = useState(false);
  const [telemetry, setTelemetry] = useState<HardwareTelemetry | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Close popover on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setStatusPopoverOpen(false);
      }
    };
    if (statusPopoverOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [statusPopoverOpen]);

  // Poll hardware telemetry (every 2s when local models run, 5s otherwise)
  useEffect(() => {
    let mounted = true;
    const fetchTelem = async () => {
      try {
        const data = await sidecarClient.getHardwareTelemetry();
        if (mounted) setTelemetry(data);
      } catch {
        // ignore
      }
    };

    fetchTelem();
    const intervalMs = telemetry?.local_runtime_active ? 2000 : 5000;
    const timer = setInterval(fetchTelem, intervalMs);

    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [telemetry?.local_runtime_active]);

  const getLocationTitle = (mode: Mode, project?: string) => {
    if (project) return project;
    switch (mode) {
      case 'home':
        return 'Home';
      case 'projects':
        return 'Projects';
      case 'tasks':
        return 'Tasks';
      case 'workflows':
      case 'swarm':
        return 'Automations';
      case 'code':
        return 'Developer';
      case 'deep-research':
        return 'Research';
      case 'docs':
        return 'Writing';
      case 'sheets':
        return 'Data';
      case 'skills':
      case 'marketplace':
        return 'Skills';
      case 'cost':
        return 'Activity / Usage';
      case 'policies':
        return 'Approvals';
      case 'benchmarks':
        return 'Models / Diagnostics';
      case 'settings':
        return 'Settings';
      default:
        return 'Workspace';
    }
  };

  const getStatusLabel = () => {
    if (health.status === 'offline') return 'Offline';
    if (health.status === 'degraded') return 'Degraded';
    if (isBusy) return 'Busy';
    return 'Ready';
  };

  const getStatusDotClass = () => {
    if (health.status === 'offline') return 'bg-danger';
    if (health.status === 'degraded') return 'bg-warning';
    if (isBusy) return 'bg-accent animate-pulse';
    return 'bg-emerald-400';
  };

  return (
    <header className="h-11 bg-bg-elevated border-b border-border-subtle px-4 flex items-center justify-between select-none">
      {/* Left: Canonical Location Breadcrumb */}
      <div className="flex items-center gap-1.5 text-xs text-text-secondary select-none">
        <span className="font-semibold text-text-primary tracking-tight">Agent Engine</span>
        <span className="text-text-tertiary">/</span>
        <span className="text-text-secondary font-medium">{getLocationTitle(activeMode, projectName)}</span>
      </div>

      {/* Right: Restrained Single Status Popover Trigger */}
      <div ref={popoverRef} className="relative">
        <button
          type="button"
          onClick={() => setStatusPopoverOpen(!statusPopoverOpen)}
          aria-label="System status"
          aria-expanded={statusPopoverOpen}
          className="flex items-center gap-2 px-2.5 py-1 rounded-md bg-bg-base hover:bg-bg-hover border border-border-subtle hover:border-border-strong text-xs font-medium text-text-primary transition-colors"
        >
          <span className={`w-2 h-2 rounded-full ${getStatusDotClass()}`} />
          <span>{getStatusLabel()}</span>
          <ChevronDown className="w-3 h-3 text-text-tertiary" />
        </button>

        {/* System Status Popover */}
        {statusPopoverOpen && (
          <div className="absolute right-0 mt-1.5 w-80 bg-bg-elevated border border-border-strong rounded-lg shadow-2xl p-3 z-50 animate-in fade-in duration-100 text-xs">
            {/* Header */}
            <div className="flex items-center justify-between pb-2 border-b border-border-subtle/80">
              <span className="font-semibold text-text-primary">System Status</span>
              <span className="text-[10px] font-mono text-text-tertiary uppercase">Sidecar 8000</span>
            </div>

            {/* Core Services State */}
            <div className="py-2.5 space-y-1.5 border-b border-border-subtle/60">
              <div className="flex items-center justify-between text-text-secondary">
                <span className="flex items-center gap-1.5">
                  <Server className="w-3.5 h-3.5 text-text-tertiary" />
                  <span>Execution service</span>
                </span>
                <span className="font-mono text-text-primary">
                  {health.status === 'healthy' ? 'Ready' : health.status === 'degraded' ? 'Degraded' : 'Offline'}
                </span>
              </div>
              <div className="flex items-center justify-between text-text-secondary">
                <span className="flex items-center gap-1.5">
                  <Cpu className="w-3.5 h-3.5 text-text-tertiary" />
                  <span>Local runtime</span>
                </span>
                <span className="font-mono text-text-primary">
                  {telemetry?.local_runtime_active || telemetry?.gpu_detected ? 'Ready' : 'Standby'}
                </span>
              </div>
              <div className="flex items-center justify-between text-text-secondary">
                <span className="flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5 text-text-tertiary" />
                  <span>Database</span>
                </span>
                <span className="font-mono text-text-primary">Ready</span>
              </div>
              <div className="flex items-center justify-between text-text-secondary">
                <span className="flex items-center gap-1.5">
                  <Terminal className="w-3.5 h-3.5 text-text-tertiary" />
                  <span>Sandbox</span>
                </span>
                <span className="font-mono text-text-primary">Ready</span>
              </div>
              <div className="flex items-center justify-between text-text-secondary">
                <span className="flex items-center gap-1.5">
                  <Cloud className="w-3.5 h-3.5 text-text-tertiary" />
                  <span>Cloud providers</span>
                </span>
                <span className="font-mono text-text-secondary">Connected</span>
              </div>
            </div>

            {/* Compute Resources */}
            {telemetry && (
              <div className="py-2.5 space-y-1.5 border-b border-border-subtle/60 text-[11px] font-mono">
                <div className="text-[10px] uppercase font-semibold text-text-tertiary tracking-wider font-sans mb-1">
                  Resources
                </div>
                <div className="flex items-center justify-between text-text-secondary">
                  <span>CPU</span>
                  <span className="text-text-primary">{telemetry.cpu_usage_percent}%</span>
                </div>
                <div className="flex items-center justify-between text-text-secondary">
                  <span>Memory</span>
                  <span className="text-text-primary">
                    {telemetry.ram_used_gb}G / {telemetry.ram_total_gb}G ({telemetry.ram_used_percent}%)
                  </span>
                </div>
                <div className="flex items-center justify-between text-text-secondary">
                  <span>VRAM</span>
                  <span className="text-text-primary">
                    {telemetry.vram_used_gb}G / {telemetry.vram_total_gb}G ({telemetry.vram_used_percent}%)
                  </span>
                </div>

                {/* VRAM Saturation Warning */}
                {telemetry.vram_warning && (
                  <div className="flex items-center gap-1 text-danger font-bold px-1.5 py-0.5 rounded bg-danger/15 border border-danger/30 mt-1">
                    <AlertTriangle className="w-3.5 h-3.5" />
                    <span>VRAM {telemetry.vram_used_percent}% CRITICAL</span>
                  </div>
                )}

                {/* Real Observed Throughput (Only when actively measured) */}
                {telemetry.local_runtime_active && telemetry.tokens_per_second > 0 && (
                  <div className="flex items-center justify-between text-emerald-400 font-medium pt-1 border-t border-border-subtle/40">
                    <span className="flex items-center gap-1">
                      <Gauge className="w-3.5 h-3.5" />
                      <span>Observed speed</span>
                    </span>
                    <span>{telemetry.tokens_per_second} tok/s</span>
                  </div>
                )}
              </div>
            )}

            {/* Footer Action */}
            <div className="pt-2 flex items-center justify-between">
              <span className="text-[10px] text-text-tertiary font-mono">
                Engine: {health.engine || 'FastAPI sidecar'}
              </span>
              <button
                type="button"
                onClick={() => {
                  setStatusPopoverOpen(false);
                  onOpenDiagnostics?.();
                }}
                className="text-[11px] text-accent hover:underline cursor-pointer"
              >
                Open diagnostics
              </button>
            </div>
          </div>
        )}
      </div>
    </header>
  );
};
