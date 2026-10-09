import React, { useState, useEffect } from 'react';
import {
  Gauge,
  Cpu,
  Cloud,
  RefreshCw,
  HardDrive,
  ChevronDown,
  ChevronUp,
  Loader2,
} from 'lucide-react';
import { LocalModelRecommendations } from '../components/LocalModelRecommendations';
import { sidecarClient } from '../api/client';
import { DownloadStatus, ProviderConnectionVerification } from '../types';

export const Models: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'local' | 'cloud' | 'installed'>('local');
  const [installedModels, setInstalledModels] = useState<DownloadStatus[]>([]);
  const [activeDownloads, setActiveDownloads] = useState<DownloadStatus[]>([]);
  const [verifyingProvider, setVerifyingProvider] = useState<string | null>(null);
  const [providerStatuses, setProviderStatuses] = useState<Record<string, ProviderConnectionVerification>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);

  const loadModelsState = async () => {
    try {
      const [installed, downloads] = await Promise.all([
        sidecarClient.getInstalledModels().catch(() => []),
        sidecarClient.getModelDownloads().catch(() => []),
      ]);
      setInstalledModels(installed || []);
      setActiveDownloads(downloads || []);
    } catch {
      // offline fallback
    }
  };

  useEffect(() => {
    loadModelsState();
  }, []);

  const handleTestProvider = async (providerId: string) => {
    setVerifyingProvider(providerId);
    try {
      const res = await sidecarClient.verifyProvider(providerId);
      setProviderStatuses((prev) => ({ ...prev, [providerId]: res }));
    } catch (err: any) {
      setProviderStatuses((prev) => ({
        ...prev,
        [providerId]: {
          provider_id: providerId,
          status: 'error',
          error: err?.message || 'Connection verification failed',
        } as any,
      }));
    } finally {
      setVerifyingProvider(null);
    }
  };

  const cloudProviders = [
    { id: 'openai', name: 'OpenAI', defaultModel: 'gpt-4o / gpt-4o-mini', desc: 'Commercial frontier models and tool calling' },
    { id: 'anthropic', name: 'Anthropic', defaultModel: 'claude-3-5-sonnet / haiku', desc: 'High-capability analytical reasoning' },
    { id: 'gemini', name: 'Google Gemini', defaultModel: 'gemini-1.5-pro / flash', desc: 'Long-context multimodal inference' },
    { id: 'groq', name: 'Groq Cloud', defaultModel: 'llama-3.3-70b-versatile', desc: 'Ultra-fast LPUs for real-time streaming' },
    { id: 'ollama', name: 'Ollama (Local Daemon)', defaultModel: 'qwen2.5:7b / llama3.2', desc: 'Local daemon running on http://127.0.0.1:11434' },
  ];

  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden" data-testid="models-screen">
      {/* Header */}
      <div className="h-12 border-b border-border-subtle bg-bg-elevated px-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Gauge className="w-4 h-4 text-accent" />
          <h1 className="text-sm font-semibold tracking-tight text-text-primary">Models Hub</h1>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-text-tertiary uppercase">
            R3 Execution Hub
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary transition-colors"
          >
            <span>Advanced Specs</span>
            {showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
          <button
            type="button"
            onClick={loadModelsState}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="px-4 py-2 border-b border-border-subtle bg-bg-elevated/50 flex items-center gap-1 text-xs">
        <button
          type="button"
          onClick={() => setActiveTab('local')}
          className={`flex items-center gap-1.5 px-3 py-1 rounded font-medium transition-colors ${
            activeTab === 'local'
              ? 'bg-bg-elevated text-text-primary shadow-xs border border-border-subtle'
              : 'text-text-tertiary hover:text-text-secondary'
          }`}
        >
          <Cpu className="w-3.5 h-3.5" />
          <span>Local Recommendations</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('cloud')}
          className={`flex items-center gap-1.5 px-3 py-1 rounded font-medium transition-colors ${
            activeTab === 'cloud'
              ? 'bg-bg-elevated text-text-primary shadow-xs border border-border-subtle'
              : 'text-text-tertiary hover:text-text-secondary'
          }`}
        >
          <Cloud className="w-3.5 h-3.5" />
          <span>Cloud Providers</span>
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('installed')}
          className={`flex items-center gap-1.5 px-3 py-1 rounded font-medium transition-colors ${
            activeTab === 'installed'
              ? 'bg-bg-elevated text-text-primary shadow-xs border border-border-subtle'
              : 'text-text-tertiary hover:text-text-secondary'
          }`}
        >
          <HardDrive className="w-3.5 h-3.5" />
          <span>Installed Artifacts ({installedModels.length})</span>
        </button>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
        {activeTab === 'local' && (
          <div className="space-y-4 max-w-4xl">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-text-primary">
                Hardware-Calibrated Local Recommendations
              </h2>
              <p className="text-xs text-text-secondary leading-relaxed">
                Inspected hardware facts are matched against quantized GGUF weights to guarantee fit within available host RAM & VRAM.
              </p>
            </div>
            {/* Embedded Canonical R3 Local Recommendations Component */}
            <LocalModelRecommendations />
          </div>
        )}

        {activeTab === 'cloud' && (
          <div className="space-y-4 max-w-4xl">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-text-primary">Cloud Model Providers</h2>
              <p className="text-xs text-text-secondary leading-relaxed">
                Test connectivity, probe available model IDs, and verify inference latency. API credentials are encrypted in local secure storage.
              </p>
            </div>

            <div className="divide-y divide-border-subtle border border-border-subtle rounded-lg bg-bg-elevated/40 overflow-hidden">
              {cloudProviders.map((prov) => {
                const status = providerStatuses[prov.id];
                const isVerifying = verifyingProvider === prov.id;

                return (
                  <div key={prov.id} className="p-4 flex items-center justify-between text-xs hover:bg-bg-hover transition-colors">
                    <div className="space-y-1 flex-1 mr-4">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-text-primary text-sm">{prov.name}</span>
                        <span className="text-[11px] font-mono text-text-tertiary">({prov.defaultModel})</span>
                        {status && (
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${
                              status.status === 'VERIFIED_CONNECTED'
                                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                                : 'bg-red-500/10 text-red-400 border border-red-500/20'
                            }`}
                          >
                            {status.status === 'VERIFIED_CONNECTED'
                              ? `Verified (${status.latency_ms ? `${status.latency_ms}ms` : 'OK'})`
                              : 'Failed'}
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-text-secondary">{prov.desc}</p>
                    </div>

                    <button
                      type="button"
                      onClick={() => handleTestProvider(prov.id)}
                      disabled={isVerifying}
                      className="px-3 py-1.5 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary hover:text-text-primary transition-colors flex items-center gap-1.5 disabled:opacity-50 flex-shrink-0"
                    >
                      {isVerifying ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          <span>Testing...</span>
                        </>
                      ) : (
                        <span>Test Connection</span>
                      )}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {activeTab === 'installed' && (
          <div className="space-y-4 max-w-4xl">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-text-primary">Installed Weights & Artifacts</h2>
              <p className="text-xs text-text-secondary leading-relaxed">
                Locally cached GGUF and safetensors model weights verified with SHA-256 checksums.
              </p>
            </div>

            {activeDownloads.length > 0 && (
              <div className="p-3 bg-accent/10 border border-accent/30 rounded-lg text-xs space-y-2">
                <div className="font-semibold text-accent flex items-center gap-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  <span>Active Downloads ({activeDownloads.length})</span>
                </div>
                {activeDownloads.map((d) => (
                  <div key={d.artifact_id} className="font-mono text-[11px] flex justify-between">
                    <span>{d.model_identity?.model_id || d.artifact_id}</span>
                    <span>{Math.round(d.progress_ratio * 100)}% ({d.state})</span>
                  </div>
                ))}
              </div>
            )}

            {installedModels.length === 0 ? (
              <div className="p-12 text-center border border-border-subtle rounded-lg bg-bg-elevated/30 text-xs text-text-tertiary">
                <HardDrive className="w-8 h-8 mx-auto text-text-tertiary/40 mb-2" />
                <div className="font-medium text-text-secondary">No local model weights installed yet</div>
                <p className="text-[11px] mt-1">
                  Navigate to "Local Recommendations" above to download verified local models.
                </p>
              </div>
            ) : (
              <div className="border border-border-subtle rounded-lg bg-bg-elevated/40 divide-y divide-border-subtle">
                {installedModels.map((m, idx) => (
                  <div key={idx} className="p-3.5 flex items-center justify-between text-xs font-mono">
                    <div>
                      <div className="font-semibold text-text-primary">
                        {m.model_identity?.model_id || m.artifact_id}
                      </div>
                      <div className="text-[11px] text-text-tertiary mt-0.5">
                        State: {m.state} · Artifact ID: {m.artifact_id}
                      </div>
                    </div>
                    <span className="text-emerald-400 font-medium">Ready</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Advanced Specifications Disclosure */}
        {showAdvanced && (
          <div className="p-4 rounded-lg bg-bg-elevated border border-border-subtle space-y-3 text-xs font-mono">
            <div className="font-semibold text-text-primary uppercase tracking-wider text-[10px]">
              Advanced Execution Telemetry & Precision
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[11px]">
              <div>
                <span className="text-text-tertiary block">Quantization Matrix</span>
                <span className="text-text-secondary">Q4_K_M (4.50 bpw)</span>
              </div>
              <div>
                <span className="text-text-tertiary block">Context Ceiling</span>
                <span className="text-text-secondary">32,768 tokens</span>
              </div>
              <div>
                <span className="text-text-tertiary block">Engine Target</span>
                <span className="text-text-secondary">llama.cpp / Vulkan</span>
              </div>
              <div>
                <span className="text-text-tertiary block">Model Canonical ID</span>
                <span className="text-text-secondary">qwen2.5:7b-instruct</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
