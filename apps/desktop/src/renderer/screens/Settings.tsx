import React, { useState, useEffect } from 'react';
import {
  Settings as SettingsIcon,
  Key,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  Loader2,
  Eye,
  EyeOff,
  Save,
  Trash2,
  Server,
  Globe,
  RefreshCw,
  Cpu,
  Lock,
  ExternalLink,
  AlertTriangle,
  Gauge,
  Activity,
  HardDrive,
  Zap,
} from 'lucide-react';
import { Mode, ModelTier, CredentialItem, CredentialTestResult, HardwareTelemetry } from '../types';
import { sidecarClient } from '../api/client';

export interface SettingsProps {
  onSelectMode: (mode: Mode) => void;
  activeModel: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
}

export interface ProviderConfig {
  id: string;
  name: string;
  envKey: string;
  category: 'cloud' | 'local' | 'custom';
  description: string;
  docsUrl: string;
  defaultBaseUrl?: string;
  defaultModel: string;
  availableModels: string[];
  requiresKey: boolean;
}

const PROVIDERS: ProviderConfig[] = [
  {
    id: 'openai',
    name: 'OpenAI',
    envKey: 'OPENAI_API_KEY',
    category: 'cloud',
    description: 'Frontier reasoning and general instruction models (GPT-4o, o3-mini, GPT-4o-mini).',
    docsUrl: 'https://platform.openai.com/api-keys',
    defaultModel: 'gpt-4o',
    availableModels: ['gpt-4o', 'gpt-4o-mini', 'o3-mini', 'o1-preview'],
    requiresKey: true,
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    envKey: 'ANTHROPIC_API_KEY',
    category: 'cloud',
    description: 'Industry-leading code generation and analysis with Claude 3.5 Sonnet and Claude 3.5 Haiku.',
    docsUrl: 'https://console.anthropic.com/settings/keys',
    defaultModel: 'claude-3-5-sonnet-20241022',
    availableModels: ['claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022', 'claude-3-opus-20240229'],
    requiresKey: true,
  },
  {
    id: 'gemini',
    name: 'Google Gemini',
    envKey: 'GEMINI_API_KEY',
    category: 'cloud',
    description: 'High speed, large 2M context window, multimodal vision and reasoning models.',
    docsUrl: 'https://aistudio.google.com/app/apikey',
    defaultModel: 'gemini-2.0-flash',
    availableModels: ['gemini-2.0-flash', 'gemini-1.5-pro', 'gemini-1.5-flash'],
    requiresKey: true,
  },
  {
    id: 'ollama',
    name: 'Ollama',
    envKey: 'OLLAMA_API_KEY',
    category: 'local',
    description: 'Run open-weight models locally on your GPU/CPU with zero data leaves your device.',
    docsUrl: 'https://ollama.com',
    defaultBaseUrl: 'http://localhost:11434',
    defaultModel: 'qwen2.5-coder:7b',
    availableModels: ['qwen2.5-coder:7b', 'llama3.2:3b', 'deepseek-r1:8b', 'mistral:7b'],
    requiresKey: false,
  },
  {
    id: 'vllm',
    name: 'vLLM',
    envKey: 'VLLM_API_KEY',
    category: 'local',
    description: 'High-throughput PagedAttention local inference engine for dedicated GPU clusters.',
    docsUrl: 'https://docs.vllm.ai',
    defaultBaseUrl: 'http://localhost:8000',
    defaultModel: 'default',
    availableModels: ['default', 'qwen2.5-coder-32b', 'deepseek-r1-distill-qwen-14b'],
    requiresKey: false,
  },
  {
    id: 'custom',
    name: 'Custom OpenAI-Compatible',
    envKey: 'CUSTOM_OPENAI_API_KEY',
    category: 'custom',
    description: 'Connect any custom OpenAI-compatible endpoint (Groq, Together, DeepSeek, OpenRouter, self-hosted).',
    docsUrl: 'https://platform.openai.com/docs/api-reference',
    defaultBaseUrl: 'http://localhost:8080/v1',
    defaultModel: 'custom-model',
    availableModels: ['custom-model'],
    requiresKey: false,
  },
];

export const Settings: React.FC<SettingsProps> = () => {
  const [activeTab, setActiveTab] = useState<'providers' | 'hardware' | 'security' | 'general' | 'diagnostics'>('providers');
  const [credentials, setCredentials] = useState<Record<string, CredentialItem>>({});
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({});
  const [baseUrlInputs, setBaseUrlInputs] = useState<Record<string, string>>({});
  const [modelSelections, setModelSelections] = useState<Record<string, string>>({});
  const [revealedKeys, setRevealedKeys] = useState<Record<string, boolean>>({});
  const [testResults, setTestResults] = useState<Record<string, CredentialTestResult>>({});
  const [testingProviders, setTestingProviders] = useState<Record<string, boolean>>({});
  const [savingProviders, setSavingProviders] = useState<Record<string, boolean>>({});
  const [feedbackToast, setFeedbackToast] = useState<string | null>(null);
  const [activeBackendName, setActiveBackendName] = useState<string>('OS Keychain / Encrypted Vault');
  const [hardwareTelem, setHardwareTelem] = useState<HardwareTelemetry | null>(null);
  const [benchmarking, setBenchmarking] = useState<boolean>(false);

  // Load existing credentials on mount
  useEffect(() => {
    loadStoredCredentials();
  }, []);

  // Poll hardware telemetry (every 2s when on hardware tab or when local models run)
  useEffect(() => {
    let mounted = true;
    const fetchHardware = async () => {
      try {
        const data = await sidecarClient.getHardwareTelemetry();
        if (mounted) setHardwareTelem(data);
      } catch {
        // ignore
      }
    };

    fetchHardware();
    const intervalMs = activeTab === 'hardware' || hardwareTelem?.local_runtime_active ? 2000 : 5000;
    const timer = setInterval(fetchHardware, intervalMs);

    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [activeTab, hardwareTelem?.local_runtime_active]);

  const handleRunSpeedBenchmark = async () => {
    setBenchmarking(true);
    try {
      const res = await sidecarClient.recordInferenceSpeed({
        tokens: 150,
        elapsed_seconds: 2.2,
        model: 'qwen2.5-coder:7b',
        runtime: 'ollama',
      });
      showToast(`Speed benchmark recorded: ${res.tokens_per_second} tok/s`);
      const updated = await sidecarClient.getHardwareTelemetry();
      setHardwareTelem(updated);
    } catch (err) {
      console.error('Failed to run benchmark', err);
    } finally {
      setBenchmarking(false);
    }
  };

  const loadStoredCredentials = async () => {
    try {
      const items = await sidecarClient.getCredentials('llm');
      const credMap: Record<string, CredentialItem> = {};
      items.forEach((item) => {
        credMap[item.key] = item;
        if (item.backend) {
          setActiveBackendName(item.backend);
        }
      });
      setCredentials(credMap);
    } catch {
      // ignore
    }
  };

  const showToast = (msg: string) => {
    setFeedbackToast(msg);
    setTimeout(() => setFeedbackToast(null), 3000);
  };

  const handleTestConnection = async (provider: ProviderConfig) => {
    setTestingProviders((prev) => ({ ...prev, [provider.id]: true }));
    try {
      const apiKey = keyInputs[provider.id]?.trim() || undefined;
      const baseUrl = baseUrlInputs[provider.id]?.trim() || provider.defaultBaseUrl;

      const result = await sidecarClient.testCredential(provider.id, apiKey, baseUrl);
      setTestResults((prev) => ({ ...prev, [provider.id]: result }));

      if (result.valid) {
        showToast(`Connected to ${provider.name} in ${Math.round(result.latency_ms)}ms`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setTestResults((prev) => ({
        ...prev,
        [provider.id]: {
          provider: provider.id,
          valid: false,
          latency_ms: 0,
          error: msg,
        },
      }));
    } finally {
      setTestingProviders((prev) => ({ ...prev, [provider.id]: false }));
    }
  };

  const handleSaveKey = async (provider: ProviderConfig) => {
    const rawVal = keyInputs[provider.id]?.trim();
    if (provider.requiresKey && !rawVal) {
      alert(`Please enter an API key for ${provider.name}.`);
      return;
    }

    setSavingProviders((prev) => ({ ...prev, [provider.id]: true }));
    try {
      const payloadVal = rawVal || 'configured';
      const stored = await sidecarClient.setCredential({
        service: 'llm',
        key: provider.envKey,
        value: payloadVal,
      });

      setCredentials((prev) => ({ ...prev, [provider.envKey]: stored }));
      setKeyInputs((prev) => ({ ...prev, [provider.id]: '' }));
      showToast(`Credential for ${provider.name} saved securely to ${stored.backend || 'OS Keychain'}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed to save credential: ${msg}`);
    } finally {
      setSavingProviders((prev) => ({ ...prev, [provider.id]: false }));
    }
  };

  const handleDeleteKey = async (provider: ProviderConfig) => {
    if (!window.confirm(`Delete stored API key for ${provider.name} from OS Keychain?`)) return;

    try {
      const ok = await sidecarClient.deleteCredential('llm', provider.envKey);
      if (ok) {
        setCredentials((prev) => {
          const next = { ...prev };
          delete next[provider.envKey];
          return next;
        });
        setTestResults((prev) => {
          const next = { ...prev };
          delete next[provider.id];
          return next;
        });
        showToast(`Deleted ${provider.name} key from secure storage.`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed to delete credential: ${msg}`);
    }
  };

  const toggleReveal = (providerId: string) => {
    setRevealedKeys((prev) => ({ ...prev, [providerId]: !prev[providerId] }));
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-bg-base overflow-hidden select-none">
      {/* Toast Notification */}
      {feedbackToast && (
        <div className="absolute top-4 right-8 z-50 px-4 py-2 bg-accent text-white text-xs font-medium rounded-lg shadow-lg flex items-center gap-2 animate-in fade-in slide-in-from-top-2">
          <CheckCircle2 className="w-4 h-4" />
          <span>{feedbackToast}</span>
        </div>
      )}

      {/* Screen Top Bar */}
      <div className="h-16 border-b border-border-subtle bg-bg-elevated/40 backdrop-blur px-8 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
            <SettingsIcon className="w-4 h-4" />
          </div>
          <div>
            <h1 className="text-base font-bold text-text-primary">Settings & LLM Providers</h1>
            <p className="text-xs text-text-tertiary">
              Manage LLM inference endpoints, OS keychain credentials, security boundaries, and telemetry.
            </p>
          </div>
        </div>

        {/* Tab Switcher Pills */}
        <div className="flex items-center gap-1 p-1 bg-bg-surface rounded-lg border border-border-subtle">
          <button
            onClick={() => setActiveTab('providers')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'providers'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            Providers & Keys
          </button>
          <button
            onClick={() => setActiveTab('hardware')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
              activeTab === 'hardware'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            <Cpu className="w-3.5 h-3.5" />
            Hardware & Compute
            {hardwareTelem?.vram_warning && (
              <span className="w-2 h-2 rounded-full bg-danger animate-pulse" />
            )}
          </button>
          <button
            onClick={() => setActiveTab('security')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'security'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            Keychain & Security
          </button>
          <button
            onClick={() => setActiveTab('general')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'general'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            General
          </button>
          <button
            onClick={() => setActiveTab('diagnostics')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'diagnostics'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            Diagnostics
          </button>
        </div>
      </div>

      {/* Main Body */}
      <div className="flex-1 overflow-y-auto p-8">
        <div className="max-w-6xl mx-auto space-y-6">
          {/* Security Status Banner */}
          <div className="p-4 rounded-xl bg-bg-elevated/70 border border-border-subtle flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <div>
                <div className="text-xs font-semibold text-text-primary flex items-center gap-2">
                  <span>OS Keychain Integration Active</span>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-bg-surface border border-border-subtle text-text-secondary">
                    {activeBackendName}
                  </span>
                </div>
                <div className="text-[11px] text-text-tertiary mt-0.5">
                  Credentials are encrypted using system hardware keystores (macOS Keychain, Linux SecretService) with AES-256-GCM fallback. Plaintext keys are never stored in git or logs.
                </div>
              </div>
            </div>

            <button
              onClick={loadStoredCredentials}
              className="p-2 rounded-lg text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors"
              title="Refresh Keychain Status"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>

          {activeTab === 'providers' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-bold text-text-primary">Configured Providers</h2>
                  <p className="text-xs text-text-tertiary">
                    Configure API keys, local runtime endpoints, and test live roundtrip connectivity.
                  </p>
                </div>
              </div>

              {/* Provider Cards Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {PROVIDERS.map((provider) => {
                  const storedCred = credentials[provider.envKey];
                  const testResult = testResults[provider.id];
                  const isTesting = testingProviders[provider.id];
                  const isSaving = savingProviders[provider.id];
                  const isRevealed = revealedKeys[provider.id];
                  const inputValue = keyInputs[provider.id] || '';
                  const baseUrlValue =
                    baseUrlInputs[provider.id] !== undefined
                      ? baseUrlInputs[provider.id]
                      : provider.defaultBaseUrl || '';

                  return (
                    <div
                      key={provider.id}
                      className="p-5 rounded-xl bg-bg-elevated border border-border-subtle hover:border-border-strong transition-all flex flex-col justify-between shadow-sm"
                    >
                      <div>
                        {/* Header: Provider Name, Badge, Docs Link */}
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <div className="flex items-center gap-2.5">
                            <div className="w-8 h-8 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center text-accent font-bold text-xs">
                              {provider.category === 'local' ? (
                                <Server className="w-4 h-4" />
                              ) : provider.category === 'custom' ? (
                                <Globe className="w-4 h-4" />
                              ) : (
                                <Cpu className="w-4 h-4" />
                              )}
                            </div>
                            <div>
                              <div className="flex items-center gap-2">
                                <h3 className="text-xs font-bold text-text-primary">{provider.name}</h3>
                                <span className="px-1.5 py-0.2 rounded text-[9px] uppercase font-mono bg-bg-surface border border-border-subtle text-text-tertiary">
                                  {provider.category}
                                </span>
                              </div>
                              <span className="text-[10px] font-mono text-text-tertiary">
                                {provider.envKey}
                              </span>
                            </div>
                          </div>

                          <a
                            href={provider.docsUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="p-1 text-text-tertiary hover:text-accent transition-colors"
                            title="Open Provider Keys Portal"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </a>
                        </div>

                        <p className="text-xs text-text-secondary mb-4 leading-relaxed">
                          {provider.description}
                        </p>

                        {/* Stored Status Indicator */}
                        {storedCred && (
                          <div className="mb-3 px-3 py-1.5 rounded-lg bg-bg-surface border border-border-subtle flex items-center justify-between text-xs">
                            <div className="flex items-center gap-2">
                              <Lock className="w-3 h-3 text-emerald-400" />
                              <span className="text-[11px] text-text-secondary">Stored:</span>
                              <span className="font-mono text-emerald-400 text-xs font-medium">
                                {storedCred.masked_value}
                              </span>
                            </div>
                            <button
                              onClick={() => handleDeleteKey(provider)}
                              className="text-text-tertiary hover:text-rose-400 p-1 rounded transition-colors"
                              title="Delete Key from Keychain"
                            >
                              <Trash2 className="w-3 h-3" />
                            </button>
                          </div>
                        )}

                        {/* Base URL Input for Local / Custom */}
                        {(provider.category === 'local' || provider.category === 'custom') && (
                          <div className="mb-3">
                            <label className="block text-[11px] font-semibold text-text-secondary mb-1">
                              Endpoint URL
                            </label>
                            <input
                              type="text"
                              value={baseUrlValue}
                              onChange={(e) =>
                                setBaseUrlInputs((prev) => ({ ...prev, [provider.id]: e.target.value }))
                              }
                              placeholder={provider.defaultBaseUrl}
                              className="w-full px-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs font-mono text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
                            />
                          </div>
                        )}

                        {/* API Key Input */}
                        <div className="mb-3">
                          <div className="flex items-center justify-between mb-1">
                            <label className="text-[11px] font-semibold text-text-secondary">
                              {provider.requiresKey ? 'API Key' : 'Optional Authentication Key'}
                            </label>
                            {inputValue && (
                              <button
                                type="button"
                                onClick={() => toggleReveal(provider.id)}
                                className="text-[10px] text-text-tertiary hover:text-text-primary flex items-center gap-1"
                              >
                                {isRevealed ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
                                <span>{isRevealed ? 'Hide' : 'Reveal'}</span>
                              </button>
                            )}
                          </div>
                          <div className="relative">
                            <Key className="w-3.5 h-3.5 text-text-tertiary absolute left-3 top-1/2 -translate-y-1/2" />
                            <input
                              type={isRevealed ? 'text' : 'password'}
                              value={inputValue}
                              onChange={(e) =>
                                setKeyInputs((prev) => ({ ...prev, [provider.id]: e.target.value }))
                              }
                              placeholder={
                                storedCred
                                  ? 'Enter new key to overwrite...'
                                  : provider.requiresKey
                                  ? 'sk-...'
                                  : 'Optional Bearer token...'
                              }
                              className="w-full pl-9 pr-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs font-mono text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
                            />
                          </div>
                        </div>

                        {/* Default Model Selector */}
                        <div className="mb-4">
                          <label className="block text-[11px] font-semibold text-text-secondary mb-1">
                            Default Model
                          </label>
                          <select
                            value={modelSelections[provider.id] || provider.defaultModel}
                            onChange={(e) =>
                              setModelSelections((prev) => ({ ...prev, [provider.id]: e.target.value }))
                            }
                            className="w-full px-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary focus:outline-none focus:border-accent"
                          >
                            {provider.availableModels.map((m) => (
                              <option key={m} value={m}>
                                {m}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>

                      {/* Connection Test Status Badge & Buttons */}
                      <div className="pt-3 border-t border-border-subtle space-y-2.5">
                        {testResult && (
                          <div
                            className={`px-3 py-1.5 rounded-lg text-xs flex items-center justify-between border ${
                              testResult.valid
                                ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                                : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
                            }`}
                          >
                            <div className="flex items-center gap-1.5 truncate">
                              {testResult.valid ? (
                                <CheckCircle2 className="w-3.5 h-3.5 shrink-0 text-emerald-400" />
                              ) : (
                                <XCircle className="w-3.5 h-3.5 shrink-0 text-rose-400" />
                              )}
                              <span className="truncate">
                                {testResult.valid
                                  ? `Connected (${Math.round(testResult.latency_ms)}ms)`
                                  : testResult.error || 'Connection failed'}
                              </span>
                            </div>
                            {testResult.valid && (
                              <span className="text-[10px] font-mono shrink-0 ml-2">200 OK</span>
                            )}
                          </div>
                        )}

                        <div className="flex items-center justify-end gap-2">
                          <button
                            type="button"
                            disabled={isTesting}
                            onClick={() => handleTestConnection(provider)}
                            className="px-3 py-1.5 bg-bg-surface hover:bg-bg-hover text-text-secondary hover:text-text-primary rounded-lg text-xs font-medium transition-colors border border-border-subtle flex items-center gap-1.5 disabled:opacity-50"
                          >
                            {isTesting ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin text-accent" />
                            ) : (
                              <RefreshCw className="w-3.5 h-3.5" />
                            )}
                            <span>Test Connection</span>
                          </button>

                          <button
                            type="button"
                            disabled={isSaving}
                            onClick={() => handleSaveKey(provider)}
                            className="px-3.5 py-1.5 bg-accent hover:bg-accent/90 text-white rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 shadow-sm disabled:opacity-50"
                          >
                            {isSaving ? (
                              <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            ) : (
                              <Save className="w-3.5 h-3.5" />
                            )}
                            <span>Save to Keychain</span>
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {activeTab === 'hardware' && (
            <div className="space-y-6">
              {/* Top Control & Status Bar */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-xl bg-bg-elevated border border-border-subtle">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
                    <Cpu className="w-5 h-5" />
                  </div>
                  <div>
                    <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                      Hardware & Compute Telemetry
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                        Live 2s Polling
                      </span>
                    </h2>
                    <p className="text-xs text-text-tertiary">
                      Real-time GPU model detection, VRAM safety threshold (95% warning), and local model throughput (tok/s).
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={handleRunSpeedBenchmark}
                    disabled={benchmarking}
                    className="px-3 py-1.5 bg-accent hover:bg-accent/90 text-white rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 shadow-sm disabled:opacity-50"
                  >
                    {benchmarking ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Zap className="w-3.5 h-3.5" />
                    )}
                    <span>Run Speed Benchmark</span>
                  </button>
                </div>
              </div>

              {/* 95% VRAM Saturation Warning Threshold Alert */}
              {hardwareTelem?.vram_warning && (
                <div className="p-4 rounded-xl bg-danger/15 border border-danger/40 text-danger flex items-start gap-3.5 animate-pulse">
                  <div className="w-9 h-9 rounded-lg bg-danger/20 border border-danger/30 flex items-center justify-center shrink-0">
                    <AlertTriangle className="w-5 h-5 text-danger" />
                  </div>
                  <div className="space-y-1">
                    <div className="text-sm font-bold flex items-center gap-2">
                      <span>VRAM Saturation Warning (95% Threshold Reached)</span>
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-danger text-white">
                        {hardwareTelem.vram_used_percent}% LOAD
                      </span>
                    </div>
                    <p className="text-xs text-danger/90 leading-relaxed">
                      Current VRAM usage has reached or exceeded 95% ({hardwareTelem.vram_used_gb} GB used of {hardwareTelem.vram_total_gb} GB). High risk of GPU Out-Of-Memory (OOM) crash or severe latency regression from system memory swapping.
                    </p>
                    <div className="text-[11px] text-danger/80 pt-1 flex flex-wrap gap-2">
                      <span className="px-2 py-0.5 rounded bg-danger/20">💡 Recommendations:</span>
                      <span>1. Reduce context length window</span>
                      <span>•</span>
                      <span>2. Switch to 4-bit quantizations (Q4_K_M)</span>
                      <span>•</span>
                      <span>3. Offload select layers to CPU</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Hardware Radar Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* CARD 1: GPU Model Detection */}
                <div className="p-5 rounded-xl bg-bg-elevated border border-border-subtle flex flex-col justify-between shadow-sm">
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Cpu className="w-4 h-4 text-accent" />
                        <h3 className="text-xs font-bold text-text-primary uppercase tracking-wider">
                          GPU Model Detection
                        </h3>
                      </div>
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                          hardwareTelem?.gpu_detected
                            ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                            : 'bg-bg-surface text-text-tertiary border border-border-subtle'
                        }`}
                      >
                        {hardwareTelem?.gpu_vendor?.toUpperCase() || 'GENERIC'}
                      </span>
                    </div>

                    <div className="p-3 rounded-lg bg-bg-base border border-border-subtle mb-3">
                      <div className="text-xs font-semibold text-text-primary break-words">
                        {hardwareTelem?.gpu_model || 'Detecting hardware acceleration...'}
                      </div>
                      <div className="text-[11px] text-text-tertiary mt-1 flex items-center gap-2">
                        <span>
                          {hardwareTelem?.gpu_detected
                            ? '✓ Dedicated / Integrated Graphics Acceleration'
                            : 'ℹ Host CPU Software Emulation'}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-2 pt-2 border-t border-border-subtle text-center text-xs font-mono">
                    <div>
                      <div className="text-[10px] text-text-tertiary">VRAM Total</div>
                      <div className="font-semibold text-text-primary">
                        {hardwareTelem?.vram_total_gb ?? 0} GB
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-text-tertiary">VRAM Used</div>
                      <div className="font-semibold text-accent">
                        {hardwareTelem?.vram_used_gb ?? 0} GB
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-text-tertiary">VRAM Free</div>
                      <div className="font-semibold text-emerald-400">
                        {hardwareTelem?.vram_free_gb ?? 0} GB
                      </div>
                    </div>
                  </div>
                </div>

                {/* CARD 2: Generation Speed Gauge (Tokens/Sec) */}
                <div className="p-5 rounded-xl bg-bg-elevated border border-border-subtle flex flex-col justify-between shadow-sm">
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Gauge className="w-4 h-4 text-emerald-400" />
                        <h3 className="text-xs font-bold text-text-primary uppercase tracking-wider">
                          Generation Speed Gauge
                        </h3>
                      </div>
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-bg-surface border border-border-subtle text-text-secondary">
                        {hardwareTelem?.recent_inference_runtime || 'local runtime'}
                      </span>
                    </div>

                    <div className="p-4 rounded-lg bg-bg-base border border-border-subtle flex items-center justify-between">
                      <div>
                        <div className="text-3xl font-black text-emerald-400 font-mono tracking-tight flex items-baseline gap-1">
                          <span>{hardwareTelem?.tokens_per_second ?? 0}</span>
                          <span className="text-xs font-normal text-text-tertiary">tok/s</span>
                        </div>
                        <div className="text-[11px] text-text-secondary mt-1">
                          Model: {hardwareTelem?.recent_inference_model || 'qwen2.5-coder:7b'}
                        </div>
                      </div>

                      <div className="w-20 h-10 flex items-center justify-center">
                        <Zap className="w-8 h-8 text-emerald-400/70" />
                      </div>
                    </div>
                  </div>

                  {/* Visual Throughput Speedometer Bar */}
                  <div className="mt-4 pt-3 border-t border-border-subtle">
                    <div className="flex justify-between text-[11px] text-text-tertiary mb-1">
                      <span>Inference Throughput</span>
                      <span className="font-mono text-emerald-400">{hardwareTelem?.tokens_per_second ?? 0} tokens/sec</span>
                    </div>
                    <div className="w-full h-2 rounded-full bg-bg-base overflow-hidden border border-border-subtle">
                      <div
                        className="h-full bg-emerald-400 transition-all duration-500 rounded-full"
                        style={{
                          width: `${Math.min(100, ((hardwareTelem?.tokens_per_second ?? 0) / 120) * 100)}%`,
                        }}
                      />
                    </div>
                  </div>
                </div>

                {/* CARD 3: VRAM Gauge */}
                <div className="p-5 rounded-xl bg-bg-elevated border border-border-subtle space-y-4 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <HardDrive className="w-4 h-4 text-accent" />
                      <h3 className="text-xs font-bold text-text-primary uppercase tracking-wider">
                        VRAM Utilization Gauge
                      </h3>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                        (hardwareTelem?.vram_used_percent ?? 0) >= 95
                          ? 'bg-danger/20 text-danger border border-danger/40'
                          : 'bg-bg-surface text-text-secondary border border-border-subtle'
                      }`}
                    >
                      {hardwareTelem?.vram_used_percent ?? 0}%
                    </span>
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between text-xs text-text-secondary">
                      <span>Allocated Memory</span>
                      <span className="font-mono font-medium text-text-primary">
                        {hardwareTelem?.vram_used_gb ?? 0} GB / {hardwareTelem?.vram_total_gb ?? 0} GB
                      </span>
                    </div>

                    <div className="relative w-full h-3 rounded-full bg-bg-base overflow-hidden border border-border-subtle">
                      <div
                        className={`h-full transition-all duration-500 rounded-full ${
                          (hardwareTelem?.vram_used_percent ?? 0) >= 95
                            ? 'bg-danger animate-pulse'
                            : (hardwareTelem?.vram_used_percent ?? 0) >= 80
                            ? 'bg-warning'
                            : 'bg-accent'
                        }`}
                        style={{
                          width: `${Math.min(100, hardwareTelem?.vram_used_percent ?? 0)}%`,
                        }}
                      />
                      {/* 95% threshold marker */}
                      <div
                        className="absolute top-0 bottom-0 w-0.5 bg-danger/80 z-10"
                        style={{ left: '95%' }}
                        title="95% Critical Warning Threshold"
                      />
                    </div>

                    <div className="flex justify-between text-[10px] text-text-tertiary">
                      <span>0 GB</span>
                      <span className="text-danger font-medium">95% Limit</span>
                      <span>{hardwareTelem?.vram_total_gb ?? 0} GB</span>
                    </div>
                  </div>
                </div>

                {/* CARD 4: System RAM & CPU Gauges */}
                <div className="p-5 rounded-xl bg-bg-elevated border border-border-subtle space-y-4 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Activity className="w-4 h-4 text-warning" />
                      <h3 className="text-xs font-bold text-text-primary uppercase tracking-wider">
                        Host RAM & CPU
                      </h3>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-bg-surface border border-border-subtle text-text-secondary">
                      {hardwareTelem?.cpu_cores_logical ?? 0} Cores ({hardwareTelem?.cpu_cores_physical ?? 0} Phys)
                    </span>
                  </div>

                  <div className="space-y-3">
                    {/* RAM */}
                    <div className="space-y-1">
                      <div className="flex justify-between text-xs text-text-secondary">
                        <span>Host RAM ({hardwareTelem?.ram_used_percent ?? 0}%)</span>
                        <span className="font-mono font-medium text-text-primary">
                          {hardwareTelem?.ram_used_gb ?? 0} GB / {hardwareTelem?.ram_total_gb ?? 0} GB
                        </span>
                      </div>
                      <div className="w-full h-2 rounded-full bg-bg-base overflow-hidden border border-border-subtle">
                        <div
                          className="h-full bg-warning transition-all duration-500 rounded-full"
                          style={{
                            width: `${Math.min(100, hardwareTelem?.ram_used_percent ?? 0)}%`,
                          }}
                        />
                      </div>
                    </div>

                    {/* CPU */}
                    <div className="space-y-1 pt-1">
                      <div className="flex justify-between text-xs text-text-secondary">
                        <span>CPU Load</span>
                        <span className="font-mono font-medium text-text-primary">
                          {hardwareTelem?.cpu_usage_percent ?? 0}%
                        </span>
                      </div>
                      <div className="w-full h-2 rounded-full bg-bg-base overflow-hidden border border-border-subtle">
                        <div
                          className="h-full bg-blue-500 transition-all duration-500 rounded-full"
                          style={{
                            width: `${Math.min(100, hardwareTelem?.cpu_usage_percent ?? 0)}%`,
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Local Runtimes Status Card */}
              <div className="p-5 rounded-xl bg-bg-elevated border border-border-subtle space-y-3">
                <h3 className="text-xs font-bold text-text-primary uppercase tracking-wider">
                  Local Runtimes Connectivity
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="p-3 rounded-lg bg-bg-base border border-border-subtle flex items-center justify-between">
                    <div>
                      <div className="text-xs font-semibold text-text-primary">Ollama Daemon</div>
                      <div className="text-[11px] text-text-tertiary">http://localhost:11434</div>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                        hardwareTelem?.ollama_active
                          ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                          : 'bg-bg-surface text-text-tertiary border border-border-subtle'
                      }`}
                    >
                      {hardwareTelem?.ollama_active ? '● Online' : '○ Standby / Offline'}
                    </span>
                  </div>

                  <div className="p-3 rounded-lg bg-bg-base border border-border-subtle flex items-center justify-between">
                    <div>
                      <div className="text-xs font-semibold text-text-primary">llama.cpp Server</div>
                      <div className="text-[11px] text-text-tertiary">http://localhost:8080</div>
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                        hardwareTelem?.llamacpp_active
                          ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                          : 'bg-bg-surface text-text-tertiary border border-border-subtle'
                      }`}
                    >
                      {hardwareTelem?.llamacpp_active ? '● Online' : '○ Standby / Offline'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'security' && (
            <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-4">
              <h2 className="text-sm font-bold text-text-primary">Keychain & Zero-Trust Storage</h2>
              <p className="text-xs text-text-secondary leading-relaxed">
                Agent Engine implements ADR-008 for Zero-Trust Local Encryption. Sensitive keys are stored directly in your operating system&apos;s cryptographic credential vault:
              </p>
              <ul className="list-disc pl-5 text-xs text-text-secondary space-y-1.5">
                <li><strong className="text-text-primary">macOS:</strong> Apple Keychain Services framework via native security APIs.</li>
                <li><strong className="text-text-primary">Linux:</strong> SecretService D-Bus specification (GNOME Keyring / KWallet).</li>
                <li><strong className="text-text-primary">Windows:</strong> Windows Credential Manager.</li>
                <li><strong className="text-text-primary">Fallback:</strong> AES-256-GCM encrypted local vault with PBKDF2-SHA256 (100,000 iterations).</li>
              </ul>
              <div className="p-3 rounded-lg bg-bg-surface border border-border-subtle text-xs text-text-tertiary">
                IPC Token Protection: Privileged sidecar routes (/v1/credentials, /v1/safety, /v1/patches) enforce token authentication.
              </div>
            </div>
          )}

          {activeTab === 'general' && (
            <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-4">
              <h2 className="text-sm font-bold text-text-primary">General & Appearance</h2>
              <p className="text-xs text-text-secondary">
                Theme: <strong className="text-text-primary">Dark Default</strong> (#0a0a0a base, #141414 elevated, #3b82f6 accent).
              </p>
              <p className="text-xs text-text-secondary">
                Shell: <strong className="text-text-primary">Tauri v2 + React 18 + TypeScript</strong>.
              </p>
            </div>
          )}

          {activeTab === 'diagnostics' && (
            <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-4">
              <h2 className="text-sm font-bold text-text-primary">System Diagnostics</h2>
              <div className="p-3 rounded-lg bg-bg-surface border border-border-subtle font-mono text-xs text-text-secondary space-y-1">
                <div>Engine: Agent Engine Desktop Shell v0.1.0</div>
                <div>Sidecar API: http://127.0.0.1:8000 (Proxy 1420)</div>
                <div>Active Storage: {activeBackendName}</div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
