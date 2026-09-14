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
} from 'lucide-react';
import { Mode, ModelTier, CredentialItem, CredentialTestResult } from '../types';
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
  const [activeTab, setActiveTab] = useState<'providers' | 'general' | 'security' | 'diagnostics'>('providers');
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

  // Load existing credentials on mount
  useEffect(() => {
    loadStoredCredentials();
  }, []);

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
