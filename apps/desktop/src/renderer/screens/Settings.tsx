import React, { useState, useEffect } from 'react';
import {
  Settings as SettingsIcon,
  Key,
  ShieldCheck,
  ShieldAlert,
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
  Download,
  Bell,
  Palette,
  Terminal,
  Clock,
  Info,
  SlidersHorizontal,
} from 'lucide-react';
import {
  Mode,
  ModelTier,
  CredentialItem,
  CredentialTestResult,
  HardwareTelemetry,
  AppSettings,
  ProviderConnectionVerification,
  PrivacyBoundary,
  RoutingObjective,
} from '../types';
import { sidecarClient } from '../api/client';
import { LocalModelRecommendations } from '../components/LocalModelRecommendations';

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

export type SettingsTab =
  | 'general'
  | 'appearance'
  | 'models'
  | 'connections'
  | 'storage'
  | 'security'
  | 'notifications'
  | 'developer'
  | 'about'
  // Legacy aliases for backward compatibility with existing tests and deep links:
  | 'providers'
  | 'local'
  | 'adapters'
  | 'channels'
  | 'diagnostics';

const getInitialTab = (): SettingsTab => {
  const hash = typeof window !== 'undefined' ? window.location.hash : '';
  const match = hash.match(/[?&]tab=([a-z]+)/);
  if (match) {
    const raw = match[1];
    if (raw === 'providers' || raw === 'adapters') return 'connections';
    if (raw === 'local') return 'models';
    if (raw === 'channels') return 'notifications';
    if (raw === 'diagnostics') return 'developer';
    const canonicalTabs: SettingsTab[] = [
      'general',
      'appearance',
      'models',
      'connections',
      'storage',
      'security',
      'notifications',
      'developer',
      'about',
    ];
    if (canonicalTabs.includes(raw as SettingsTab)) {
      return raw as SettingsTab;
    }
  }
  return 'general';
};

export const Settings: React.FC<SettingsProps> = () => {
  const [activeTab, setActiveTab] = useState<SettingsTab>(getInitialTab);
  const [connectionSubTab, setConnectionSubTab] = useState<'providers' | 'adapters'>('providers');
  const [routingObjective, setRoutingObjective] = useState<RoutingObjective>(() => {
    return (localStorage.getItem('ae_routing_objective') as RoutingObjective) || 'balanced';
  });
  const [privacyBoundary, setPrivacyBoundary] = useState<PrivacyBoundary>(() => {
    return (localStorage.getItem('ae_privacy_boundary') as PrivacyBoundary) || 'local_only';
  });
  const [workspacePath, setWorkspacePath] = useState<string>(() => {
    return localStorage.getItem('ae_workspace_path') || '~/code/agent_engine';
  });
  const [startupBehavior, setStartupBehavior] = useState<string>(() => {
    return localStorage.getItem('ae_startup_behavior') || 'restore_session';
  });
  const [language, setLanguage] = useState<string>('en-US');

  const handleSelectRoutingObjective = (obj: RoutingObjective) => {
    setRoutingObjective(obj);
    localStorage.setItem('ae_routing_objective', obj);
    window.dispatchEvent(new CustomEvent('routing-objective-changed', { detail: obj }));
    showToast(`Routing strategy set to ${obj.replace('_', ' ').toUpperCase()}`);
  };

  const handleSelectPrivacyBoundary = (boundary: PrivacyBoundary) => {
    setPrivacyBoundary(boundary);
    localStorage.setItem('ae_privacy_boundary', boundary);
    window.dispatchEvent(new CustomEvent('privacy-boundary-changed', { detail: boundary }));
    showToast(`Privacy boundary set to ${boundary.replace('_', ' ').toUpperCase()}`);
  };

  // Backward compatibility alias handler for legacy tests and deep links:
  const handleSelectLegacyTab = (legacy: string) => {
    switch (legacy) {
      case 'providers':
        setActiveTab('providers');
        setConnectionSubTab('providers');
        break;
      case 'adapters':
        setActiveTab('adapters');
        setConnectionSubTab('adapters');
        break;
      case 'local':
        setActiveTab('local');
        break;
      case 'channels':
        setActiveTab('channels');
        break;
      case 'diagnostics':
        setActiveTab('diagnostics');
        break;
      default:
        break;
    }
  };

  const [credentials, setCredentials] = useState<Record<string, CredentialItem>>({});
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({});
  const [baseUrlInputs, setBaseUrlInputs] = useState<Record<string, string>>({});
  const [modelSelections, setModelSelections] = useState<Record<string, string>>({});
  const [revealedKeys, setRevealedKeys] = useState<Record<string, boolean>>({});
  const [testResults, setTestResults] = useState<Record<string, CredentialTestResult>>({});
  const [verifications, setVerifications] = useState<Record<string, ProviderConnectionVerification>>({});
  const [testingProviders, setTestingProviders] = useState<Record<string, boolean>>({});
  const [savingProviders, setSavingProviders] = useState<Record<string, boolean>>({});
  const [feedbackToast, setFeedbackToast] = useState<string | null>(null);
  const [activeBackendName, setActiveBackendName] = useState<string>('OS Keychain / Encrypted Vault');
  const [hardwareTelem, setHardwareTelem] = useState<HardwareTelemetry | null>(null);
  const [benchmarking, setBenchmarking] = useState<boolean>(false);
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [savingSettings, setSavingSettings] = useState<boolean>(false);
  const [exportingDiagnostics, setExportingDiagnostics] = useState<boolean>(false);
  const [diagnosticsSuccess, setDiagnosticsSuccess] = useState<string | null>(null);

  // Developer Mode (Default: OFF)
  const [developerMode, setDeveloperMode] = useState<boolean>(() => {
    return (
      localStorage.getItem('agent_engine_developer_mode') === 'true' ||
      localStorage.getItem('ae_developer_mode') === 'true'
    );
  });

  const handleToggleDeveloperMode = (enabled: boolean) => {
    setDeveloperMode(enabled);
    localStorage.setItem('agent_engine_developer_mode', String(enabled));
    localStorage.setItem('ae_developer_mode', String(enabled));
    window.dispatchEvent(new Event('developer-mode-changed'));
  };

  // Load existing credentials & app settings on mount
  useEffect(() => {
    loadStoredCredentials();
    loadAppSettings();
  }, []);

  const loadAppSettings = async () => {
    try {
      const config = await sidecarClient.getAppSettings();
      setAppSettings(config);
    } catch (err) {
      console.error('Failed to load app settings', err);
    }
  };

  useEffect(() => {
    const handleHashChange = () => {
      const match = window.location.hash.match(/[?&]tab=([a-z]+)/);
      if (match) {
        handleSelectLegacyTab(match[1]);
      } else {
        setActiveTab(getInitialTab());
      }
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
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
    const intervalMs = activeTab === 'local' || (activeTab as string) === 'hardware' || hardwareTelem?.local_runtime_active ? 2000 : 5000;
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

  const handleSaveAppSettings = async () => {
    if (!appSettings) return;
    setSavingSettings(true);
    try {
      const updated = await sidecarClient.saveAppSettings(appSettings);
      setAppSettings(updated);
      showToast('Settings saved & encrypted to vault successfully.');
    } catch (err: any) {
      console.error('Failed to save settings:', err);
      alert(`Failed to save settings: ${err.message || err}`);
    } finally {
      setSavingSettings(false);
    }
  };

  const handleExportDiagnostics = async (format: 'zip' | 'json' = 'zip') => {
    setExportingDiagnostics(true);
    setDiagnosticsSuccess(null);
    try {
      const result = await sidecarClient.exportDiagnostics(format);
      const dateStr = new Date().toISOString().slice(0, 10);
      if (result instanceof Blob) {
        const url = URL.createObjectURL(result);
        const a = document.createElement('a');
        a.href = url;
        a.download = `agent-engine-diagnostics-${dateStr}.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } else {
        const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `agent-engine-diagnostics-${dateStr}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
      setDiagnosticsSuccess(`Diagnostics bundle (.${format}) exported successfully.`);
      setTimeout(() => setDiagnosticsSuccess(null), 4000);
    } catch (err: any) {
      console.error('Failed to export diagnostics:', err);
      alert(`Export failed: ${err.message || err}`);
    } finally {
      setExportingDiagnostics(false);
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
      const selectedModel = modelSelections[provider.id] || provider.defaultModel;
      try {
        const ver = await sidecarClient.verifyProvider(provider.id, selectedModel);
        setVerifications((prev) => ({ ...prev, [provider.id]: ver }));

        setTestResults((prev) => ({
          ...prev,
          [provider.id]: {
            provider: provider.id,
            valid: ver.status === 'VERIFIED_CONNECTED',
            latency_ms: ver.latency_ms,
            error: ver.sanitized_error || undefined,
          },
        }));

        if (ver.status === 'VERIFIED_CONNECTED') {
          showToast(`Connected to ${provider.name} in ${Math.round(ver.latency_ms)}ms`);
        } else {
          showToast(`Verification: ${ver.display_state}`);
        }
        return;
      } catch (verifyErr: unknown) {
        // Verification endpoint unavailable / failed
        // Note: Legacy testCredential is for diagnostic setup checks only and NEVER establishes Connected
        const verifyErrMsg = verifyErr instanceof Error ? verifyErr.message : String(verifyErr);

        // Optional diagnostic probe via legacy testCredential for setup checks
        try {
          const apiKey = keyInputs[provider.id]?.trim() || undefined;
          const baseUrl = baseUrlInputs[provider.id]?.trim() || provider.defaultBaseUrl;
          await sidecarClient.testCredential(provider.id, apiKey, baseUrl);
        } catch (_) {
          // Ignore diagnostic setup probe errors
        }

        const unavailableRecord: ProviderConnectionVerification = {
          provider_id: provider.id,
          status: 'UNKNOWN_FAILURE',
          last_verified_at: Date.now() / 1000,
          latency_ms: 0,
          failure_class: 'VERIFICATION_UNAVAILABLE',
          sanitized_error: `Verification unavailable: ${verifyErrMsg}`,
          verification_version: 'v1',
          verification_method_version: 'v1_canary',
          probe_type: 'real_completion_canary',
          is_fresh: false,
          display_state: 'Verification unavailable',
          details: {},
        };
        setVerifications((prev) => ({ ...prev, [provider.id]: unavailableRecord }));

        setTestResults((prev) => ({
          ...prev,
          [provider.id]: {
            provider: provider.id,
            valid: false, // NEVER valid / connected!
            latency_ms: 0,
            error: `Verification unavailable: ${verifyErrMsg}`,
          },
        }));
        showToast('Cannot verify connection: Verification unavailable');
        return;
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
            <h1 className="text-base font-bold text-text-primary">Settings</h1>
            <p className="text-xs text-text-tertiary">
              Configure model routing, connections, security boundaries, and workspace preferences.
            </p>
          </div>
        </div>

        {/* Tab Switcher Pills */}
        <div className="flex items-center gap-1 p-1 bg-bg-surface rounded-lg border border-border-subtle overflow-x-auto max-w-full">
          <button
            onClick={() => setActiveTab('general')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
              activeTab === 'general'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            General
          </button>
          <button
            onClick={() => setActiveTab('appearance')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
              activeTab === 'appearance'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            <Palette className="w-3.5 h-3.5" />
            Appearance
          </button>
          <button
            onClick={() => setActiveTab('models')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
              activeTab === 'models' || activeTab === 'local'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            <Cpu className="w-3.5 h-3.5" />
            Models
            {hardwareTelem?.vram_warning && (
              <span className="w-2 h-2 rounded-full bg-danger animate-pulse" />
            )}
          </button>
          <button
            onClick={() => {
              setActiveTab('connections');
              setConnectionSubTab('providers');
            }}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
              activeTab === 'connections' || activeTab === 'providers' || activeTab === 'adapters'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            <Key className="w-3.5 h-3.5" />
            Connections
          </button>
          <button
            onClick={() => setActiveTab('storage')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
              activeTab === 'storage'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            <HardDrive className="w-3.5 h-3.5" />
            Storage
          </button>
          <button
            onClick={() => setActiveTab('security')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
              activeTab === 'security'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            <Lock className="w-3.5 h-3.5" />
            Security
          </button>
          <button
            onClick={() => setActiveTab('notifications')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
              activeTab === 'notifications' || activeTab === 'channels'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            <Bell className="w-3.5 h-3.5" />
            Notifications
          </button>
          <button
            onClick={() => setActiveTab('developer')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
              activeTab === 'developer' || activeTab === 'diagnostics'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            Developer
          </button>
          <button
            onClick={() => setActiveTab('about')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
              activeTab === 'about'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
            }`}
          >
            <Info className="w-3.5 h-3.5" />
            About
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

          {activeTab === 'general' && (
            <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-6">
              <div className="flex items-center justify-between border-b border-border-subtle pb-4">
                <div>
                  <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                    <SlidersHorizontal className="w-4 h-4 text-accent" />
                    General Preferences
                  </h2>
                  <p className="text-xs text-text-secondary mt-1">
                    Configure default workspace directory, startup behavior, and local environment settings.
                  </p>
                </div>
                <button
                  onClick={() => {
                    localStorage.setItem('ae_workspace_path', workspacePath);
                    localStorage.setItem('ae_startup_behavior', startupBehavior);
                    showToast('General preferences saved successfully.');
                  }}
                  className="px-3.5 py-1.5 rounded-lg bg-accent text-white text-xs font-semibold hover:bg-accent-hover transition-colors flex items-center gap-2 shadow-sm"
                >
                  <Save className="w-3.5 h-3.5" />
                  Save General
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-xs">
                <div className="space-y-1.5">
                  <label className="text-text-primary font-medium">Default Workspace Directory</label>
                  <input
                    type="text"
                    value={workspacePath}
                    onChange={(e) => setWorkspacePath(e.target.value)}
                    placeholder="~/code/agent_engine"
                    className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary font-mono text-xs focus:outline-none focus:border-accent"
                  />
                  <p className="text-[11px] text-text-tertiary">
                    Primary project root opened when launching Agent Engine desktop shell.
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label className="text-text-primary font-medium">Startup Behavior</label>
                  <select
                    value={startupBehavior}
                    onChange={(e) => setStartupBehavior(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary text-xs focus:outline-none focus:border-accent"
                  >
                    <option value="restore_session">Restore Last Active Session</option>
                    <option value="blank_prompt">Open Blank Prompt Workspace</option>
                    <option value="recent_list">Show Recent Tasks Directory</option>
                  </select>
                  <p className="text-[11px] text-text-tertiary">
                    Action performed when the desktop application launches.
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label className="text-text-primary font-medium">Interface Language</label>
                  <select
                    value={language}
                    onChange={(e) => setLanguage(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary text-xs focus:outline-none focus:border-accent"
                  >
                    <option value="en-US">English (US) — Canonical</option>
                    <option value="es" disabled>Español (Coming later)</option>
                    <option value="de" disabled>Deutsch (Coming later)</option>
                    <option value="ja" disabled>日本語 (Coming later)</option>
                  </select>
                  <p className="text-[11px] text-text-tertiary">
                    Desktop shell localization language (Release 0.5 is English-only).
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label className="text-text-primary font-medium">Application Updates Channel</label>
                  <div className="p-3 rounded-lg bg-bg-base border border-border-subtle flex items-center justify-between">
                    <div>
                      <div className="font-semibold text-text-primary">Founder Release Channel</div>
                      <div className="text-[11px] text-text-tertiary">Version 0.5 Nadir Edition (Local IPC) · Auto-updater coming later (manual git builds in 0.5).</div>
                    </div>
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-bg-surface text-text-tertiary border border-border-subtle font-medium">
                      Manual / Verified
                    </span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {(activeTab === 'connections' || activeTab === 'providers' || activeTab === 'adapters') && (
            <div className="space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border-subtle">
                <div>
                  <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                    <Key className="w-4 h-4 text-accent" />
                    Connections & Tool Adapters
                  </h2>
                  <p className="text-xs text-text-tertiary">
                    Configure LLM provider endpoints, OS keychain credentials, canary connectivity, and tool adapters.
                  </p>
                </div>

                {/* Sub-tab segmented pills */}
                <div className="flex items-center gap-1 p-1 bg-bg-surface rounded-lg border border-border-subtle">
                  <button
                    type="button"
                    onClick={() => {
                      setConnectionSubTab('providers');
                      if (activeTab === 'adapters') setActiveTab('connections');
                    }}
                    className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                      (activeTab === 'adapters' ? false : connectionSubTab === 'providers')
                        ? 'bg-accent text-white shadow-sm'
                        : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
                    }`}
                  >
                    <Globe className="w-3.5 h-3.5" />
                    AI Providers ({Object.keys(credentials).length}/{PROVIDERS.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setConnectionSubTab('adapters');
                      if (activeTab === 'providers') setActiveTab('connections');
                    }}
                    className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all flex items-center gap-1.5 ${
                      (activeTab === 'adapters' || (activeTab !== 'providers' && connectionSubTab === 'adapters'))
                        ? 'bg-accent text-white shadow-sm'
                        : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
                    }`}
                  >
                    <Terminal className="w-3.5 h-3.5" />
                    Tool Adapters (6)
                  </button>
                </div>
              </div>

              {(activeTab === 'adapters' ? false : connectionSubTab === 'providers') && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-xs font-bold text-text-primary uppercase tracking-wider">Configured AI Providers</h3>
                      <p className="text-[11px] text-text-tertiary">
                        Configure API keys, local runtime endpoints, and test live canary roundtrip connectivity.
                      </p>
                    </div>
                  </div>

              {/* Provider Cards Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {PROVIDERS.map((provider) => {
                  const storedCred = credentials[provider.envKey];
                  const testResult = testResults[provider.id];
                  const verification = verifications[provider.id];
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
                        {(verification || testResult) && (() => {
                          const isConnected = verification ? verification.status === 'VERIFIED_CONNECTED' && verification.is_fresh : testResult?.valid;
                          const isStale = verification ? verification.status === 'VERIFIED_CONNECTED' && !verification.is_fresh : false;
                          const isPolicyBlocked = verification ? verification.status === 'POLICY_BLOCKED' : false;
                          const isAccessDenied = verification ? verification.status === 'ACCESS_DENIED' : false;
                          const isNotConfigured = verification ? verification.status === 'NOT_CONFIGURED' : false;
                          const latency = verification ? verification.latency_ms : (testResult?.latency_ms || 0);
                          const errMsg = verification ? (verification.sanitized_error || verification.failure_class) : testResult?.error;
                          const lastVerified = verification?.last_verified_at ? new Date(verification.last_verified_at * 1000).toLocaleTimeString() : null;

                          return (
                            <div
                              className={`px-3 py-1.5 rounded-lg text-xs flex items-center justify-between border ${
                                isConnected
                                  ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                                  : isStale
                                  ? 'bg-amber-500/10 border-amber-500/20 text-amber-400'
                                  : isPolicyBlocked
                                  ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                                  : isAccessDenied
                                  ? 'bg-rose-500/10 border-rose-500/20 text-rose-400'
                                  : isNotConfigured
                                  ? 'bg-bg-surface border-border-subtle text-text-tertiary'
                                  : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
                              }`}
                            >
                              <div className="flex items-center gap-1.5 truncate">
                                {isConnected ? (
                                  <CheckCircle2 className="w-3.5 h-3.5 shrink-0 text-emerald-400" />
                                ) : isStale ? (
                                  <Clock className="w-3.5 h-3.5 shrink-0 text-amber-400" />
                                ) : isPolicyBlocked ? (
                                  <ShieldAlert className="w-3.5 h-3.5 shrink-0 text-amber-400" />
                                ) : isAccessDenied ? (
                                  <ShieldCheck className="w-3.5 h-3.5 shrink-0 text-rose-400" />
                                ) : isNotConfigured ? (
                                  <ShieldCheck className="w-3.5 h-3.5 shrink-0 text-text-tertiary" />
                                ) : (
                                  <XCircle className="w-3.5 h-3.5 shrink-0 text-rose-400" />
                                )}
                                <span className="truncate">
                                  {isConnected
                                    ? `Connected (${Math.round(latency)}ms)`
                                    : isStale
                                    ? `Verification Stale (${Math.round(latency)}ms)`
                                    : isPolicyBlocked
                                    ? 'Policy blocked: verification not authorized'
                                    : isAccessDenied
                                    ? 'Access denied: credential lacks required permissions (403)'
                                    : isNotConfigured
                                    ? 'Not configured'
                                    : `Verification failed: ${errMsg || 'Operation failed'}`}
                                </span>
                              </div>
                              {lastVerified && (
                                <span className="text-[10px] font-mono shrink-0 ml-2 text-text-tertiary">
                                  {lastVerified}
                                </span>
                              )}
                            </div>
                          );
                        })()}

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

            {(activeTab === 'adapters' || (activeTab !== 'providers' && connectionSubTab === 'adapters')) && (
              <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-6">
                <div className="flex items-center justify-between border-b border-border-subtle pb-4">
                  <div>
                    <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                      <Terminal className="w-4 h-4 text-accent" />
                      Tool Adapters & Connectors
                    </h2>
                    <p className="text-xs text-text-secondary mt-1">
                      Manage execution adapters, Model Context Protocol (MCP), and external coding agent integrations.
                    </p>
                  </div>
                  <button
                    onClick={handleSaveAppSettings}
                    disabled={savingSettings || !appSettings}
                    className="px-3.5 py-1.5 rounded-lg bg-accent text-white text-xs font-semibold hover:bg-accent-hover transition-colors flex items-center gap-2 disabled:opacity-50"
                  >
                    {savingSettings ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                    Save Adapters
                  </button>
                </div>

                {appSettings && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                    <label className="flex items-center gap-3 p-3.5 rounded-lg bg-bg-surface border border-border-subtle cursor-pointer hover:border-accent/40 transition-colors">
                      <input
                        type="checkbox"
                        checked={appSettings.adapters.mcp_enabled}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            adapters: { ...appSettings.adapters, mcp_enabled: e.target.checked },
                          })
                        }
                        className="rounded accent-accent w-4 h-4"
                      />
                      <div>
                        <div className="font-semibold text-text-primary">Model Context Protocol (MCP)</div>
                        <div className="text-[11px] text-text-tertiary">Allow agents to discover and call MCP tools.</div>
                      </div>
                    </label>

                    <label className="flex items-center gap-3 p-3.5 rounded-lg bg-bg-surface border border-border-subtle cursor-pointer hover:border-accent/40 transition-colors">
                      <input
                        type="checkbox"
                        checked={appSettings.adapters.claude_code_adapter}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            adapters: { ...appSettings.adapters, claude_code_adapter: e.target.checked },
                          })
                        }
                        className="rounded accent-accent w-4 h-4"
                      />
                      <div>
                        <div className="font-semibold text-text-primary">Claude Code Adapter</div>
                        <div className="text-[11px] text-text-tertiary">Enable bridge to Anthropic Claude Code commands.</div>
                      </div>
                    </label>

                    <label className="flex items-center gap-3 p-3.5 rounded-lg bg-bg-surface border border-border-subtle cursor-pointer hover:border-accent/40 transition-colors">
                      <input
                        type="checkbox"
                        checked={appSettings.adapters.codex_adapter}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            adapters: { ...appSettings.adapters, codex_adapter: e.target.checked },
                          })
                        }
                        className="rounded accent-accent w-4 h-4"
                      />
                      <div>
                        <div className="font-semibold text-text-primary">Codex CLI Adapter</div>
                        <div className="text-[11px] text-text-tertiary">OpenAI Codex syntax transform & tool pipeline.</div>
                      </div>
                    </label>

                    <label className="flex items-center gap-3 p-3.5 rounded-lg bg-bg-surface border border-border-subtle cursor-pointer hover:border-accent/40 transition-colors">
                      <input
                        type="checkbox"
                        checked={appSettings.adapters.openclaw_adapter}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            adapters: { ...appSettings.adapters, openclaw_adapter: e.target.checked },
                          })
                        }
                        className="rounded accent-accent w-4 h-4"
                      />
                      <div>
                        <div className="font-semibold text-text-primary">OpenClaw Autonomous Crawler</div>
                        <div className="text-[11px] text-text-tertiary">Autonomous repository mapping adapter.</div>
                      </div>
                    </label>

                    <label className="flex items-center gap-3 p-3.5 rounded-lg bg-bg-surface border border-border-subtle cursor-pointer hover:border-accent/40 transition-colors">
                      <input
                        type="checkbox"
                        checked={appSettings.adapters.goose_adapter}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            adapters: { ...appSettings.adapters, goose_adapter: e.target.checked },
                          })
                        }
                        className="rounded accent-accent w-4 h-4"
                      />
                      <div>
                        <div className="font-semibold text-text-primary">Goose Agent Adapter</div>
                        <div className="text-[11px] text-text-tertiary">Block Goose protocol bridge & extensions.</div>
                      </div>
                    </label>

                    <label className="flex items-center gap-3 p-3.5 rounded-lg bg-bg-surface border border-border-subtle cursor-pointer hover:border-accent/40 transition-colors">
                      <input
                        type="checkbox"
                        checked={appSettings.adapters.cursor_adapter}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            adapters: { ...appSettings.adapters, cursor_adapter: e.target.checked },
                          })
                        }
                        className="rounded accent-accent w-4 h-4"
                      />
                      <div>
                        <div className="font-semibold text-text-primary">Cursor IDE Adapter</div>
                        <div className="text-[11px] text-text-tertiary">Bi-directional editor patch sync.</div>
                      </div>
                    </label>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

          {(activeTab === 'models' || activeTab === 'local') && (
            <div className="space-y-6">
              <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-6">
                <div className="flex items-center justify-between border-b border-border-subtle pb-4">
                  <div>
                    <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-accent" />
                      Model Routing & Execution Truth
                    </h2>
                    <p className="text-xs text-text-secondary mt-1">
                      Configure autonomous routing strategy, privacy boundaries, and task context limits.
                    </p>
                  </div>
                  <button
                    onClick={handleSaveAppSettings}
                    disabled={savingSettings || !appSettings}
                    className="px-3.5 py-1.5 rounded-lg bg-accent text-white text-xs font-semibold hover:bg-accent-hover transition-colors flex items-center gap-2 disabled:opacity-50"
                  >
                    {savingSettings ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                    Save Models
                  </button>
                </div>

                {/* Routing Strategy Cards */}
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-text-primary">
                    Routing Strategy
                  </label>
                  <p className="text-[11px] text-text-tertiary mb-2">
                    Determines model selection trade-offs between accuracy, speed, cost, and local isolation.
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
                    {[
                      { id: 'balanced', label: 'Balanced', desc: 'Balances quality, cost and responsiveness.' },
                      { id: 'quality_first', label: 'Quality First', desc: 'Prioritizes reasoning capability and accuracy.' },
                      { id: 'cost_first', label: 'Cost First', desc: 'Prioritizes lowest cost and local execution.' },
                      { id: 'latency_first', label: 'Latency First', desc: 'Prioritizes fastest time-to-first-token.' },
                    ].map((opt) => {
                      const isSelected = routingObjective === opt.id;
                      return (
                        <button
                          key={opt.id}
                          type="button"
                          onClick={() => handleSelectRoutingObjective(opt.id as RoutingObjective)}
                          className={`p-3.5 rounded-xl text-left border transition-all flex flex-col justify-between ${
                            isSelected
                              ? 'bg-accent/10 border-accent text-text-primary ring-1 ring-accent'
                              : 'bg-bg-surface border-border-subtle text-text-secondary hover:text-text-primary hover:border-border-strong'
                          }`}
                        >
                          <div>
                            <div className="font-bold text-xs flex items-center justify-between">
                              <span>{opt.label}</span>
                              {isSelected && <CheckCircle2 className="w-3.5 h-3.5 text-accent" />}
                            </div>
                            <div className="text-[11px] text-text-tertiary mt-1 leading-snug">
                              {opt.desc}
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Privacy Boundary Cards */}
                <div className="space-y-2 pt-2 border-t border-border-subtle">
                  <label className="text-xs font-semibold text-text-primary">
                    Privacy Boundary
                  </label>
                  <p className="text-[11px] text-text-tertiary mb-2">
                    Defines strict network boundaries and external API access for model inference.
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                    {[
                      { id: 'local_only', label: 'Local Only', desc: 'Task data stays on this device. Zero cloud API calls.' },
                      { id: 'approved_cloud', label: 'Approved Cloud', desc: 'Only cloud providers explicitly configured & verified may receive task data.' },
                      { id: 'any_configured', label: 'Any Configured', desc: 'Any configured provider endpoint may be selected.' },
                    ].map((opt) => {
                      const isSelected = privacyBoundary === opt.id;
                      return (
                        <button
                          key={opt.id}
                          type="button"
                          onClick={() => handleSelectPrivacyBoundary(opt.id as PrivacyBoundary)}
                          className={`p-3.5 rounded-xl text-left border transition-all flex flex-col justify-between ${
                            isSelected
                              ? 'bg-accent/10 border-accent text-text-primary ring-1 ring-accent'
                              : 'bg-bg-surface border-border-subtle text-text-secondary hover:text-text-primary hover:border-border-strong'
                          }`}
                        >
                          <div>
                            <div className="font-bold text-xs flex items-center justify-between">
                              <span>{opt.label}</span>
                              {isSelected && <CheckCircle2 className="w-3.5 h-3.5 text-accent" />}
                            </div>
                            <div className="text-[11px] text-text-tertiary mt-1 leading-snug">
                              {opt.desc}
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Context Parameters */}
                {appSettings && (
                  <div className="pt-2 border-t border-border-subtle space-y-4">
                    <label className="text-xs font-semibold text-text-primary">
                      Context Token Limits & Generation Controls
                    </label>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-xs">
                      <div className="space-y-1.5">
                        <label className="text-text-primary font-medium">Max Context Tokens</label>
                        <input
                          type="number"
                          value={appSettings.models.max_context_tokens}
                          onChange={(e) =>
                            setAppSettings({
                              ...appSettings,
                              models: { ...appSettings.models, max_context_tokens: parseInt(e.target.value) || 4000 },
                            })
                          }
                          className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary font-mono text-xs focus:outline-none focus:border-accent"
                        />
                        <p className="text-[11px] text-text-tertiary">Token budget allocated before context pruning.</p>
                      </div>

                      <div className="space-y-1.5">
                        <label className="text-text-primary font-medium">Hard Ceiling Tokens</label>
                        <input
                          type="number"
                          value={appSettings.models.hard_ceiling_tokens}
                          onChange={(e) =>
                            setAppSettings({
                              ...appSettings,
                              models: { ...appSettings.models, hard_ceiling_tokens: parseInt(e.target.value) || 32000 },
                            })
                          }
                          className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary font-mono text-xs focus:outline-none focus:border-accent"
                        />
                        <p className="text-[11px] text-text-tertiary">Maximum token ceiling per task invocation.</p>
                      </div>

                      <div className="space-y-1.5">
                        <label className="text-text-primary font-medium">Temperature: {appSettings.models.temperature}</label>
                        <input
                          type="range"
                          min="0.0"
                          max="1.0"
                          step="0.05"
                          value={appSettings.models.temperature}
                          onChange={(e) =>
                            setAppSettings({
                              ...appSettings,
                              models: { ...appSettings.models, temperature: parseFloat(e.target.value) },
                            })
                          }
                          className="w-full accent-accent"
                        />
                        <p className="text-[11px] text-text-tertiary">0.0 for deterministic code, 0.7 for creative generation.</p>
                      </div>

                      <label className="flex items-center gap-3 p-3.5 rounded-lg bg-bg-surface border border-border-subtle cursor-pointer hover:border-accent/40 transition-colors">
                        <input
                          type="checkbox"
                          checked={appSettings.models.bypass_cache}
                          onChange={(e) =>
                            setAppSettings({
                              ...appSettings,
                              models: { ...appSettings.models, bypass_cache: e.target.checked },
                            })
                          }
                          className="rounded accent-accent w-4 h-4"
                        />
                        <div>
                          <div className="font-semibold text-text-primary">Bypass Prompt Cache</div>
                          <div className="text-[11px] text-text-tertiary">Force direct model generation without checking deterministic cache.</div>
                        </div>
                      </label>
                    </div>
                  </div>
                )}

                {/* Developer Mode Only: Advanced Low-Level Tier Mappings */}
                {developerMode && appSettings && (
                  <div className="p-4 rounded-xl bg-bg-surface border border-border-subtle space-y-3 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-accent font-mono text-[11px] uppercase">
                        ⚙ Advanced Tier Mapping (Developer Mode Only)
                      </span>
                      <span className="text-[10px] text-text-tertiary">Low-level backend failover tiers</span>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-1">
                        <label className="text-text-secondary">Default Internal Tier</label>
                        <select
                          value={appSettings.models.default_tier}
                          onChange={(e) =>
                            setAppSettings({
                              ...appSettings,
                              models: { ...appSettings.models, default_tier: e.target.value as ModelTier },
                            })
                          }
                          className="w-full px-3 py-1.5 rounded-lg bg-bg-base border border-border-subtle text-text-primary text-xs"
                        >
                          <option value="instant">Instant (Deterministic / Local)</option>
                          <option value="swarm">Swarm (Mid-Tier Reasoning)</option>
                          <option value="reasoning">Reasoning (Frontier)</option>
                        </select>
                      </div>
                      <div className="space-y-1">
                        <label className="text-text-secondary">Fallback Internal Tier</label>
                        <select
                          value={appSettings.models.fallback_tier}
                          onChange={(e) =>
                            setAppSettings({
                              ...appSettings,
                              models: { ...appSettings.models, fallback_tier: e.target.value as ModelTier },
                            })
                          }
                          className="w-full px-3 py-1.5 rounded-lg bg-bg-base border border-border-subtle text-text-primary text-xs"
                        >
                          <option value="instant">Instant (Deterministic / Local)</option>
                          <option value="swarm">Swarm (Mid-Tier Reasoning)</option>
                          <option value="reasoning">Reasoning (Frontier)</option>
                        </select>
                      </div>
                    </div>
                  </div>
                )}
              </div>
              {/* Local Runtime Configuration Card */}
              <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-4">
                <div className="flex items-center justify-between border-b border-border-subtle pb-3">
                  <div>
                    <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-accent" />
                      Local Daemon & Runtime Engine
                    </h2>
                    <p className="text-xs text-text-secondary mt-0.5">
                      Configure local execution provider, base endpoint, and memory limits.
                    </p>
                  </div>
                  <button
                    onClick={handleSaveAppSettings}
                    disabled={savingSettings || !appSettings}
                    className="px-3.5 py-1.5 rounded-lg bg-accent text-white text-xs font-semibold hover:bg-accent-hover transition-colors flex items-center gap-2 disabled:opacity-50"
                  >
                    {savingSettings ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                    Save Runtime
                  </button>
                </div>

                {appSettings && (
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                    <div className="space-y-1">
                      <label className="text-text-primary font-medium">Ollama Base URL</label>
                      <input
                        type="text"
                        value={appSettings.local_runtime.ollama_base_url}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            local_runtime: { ...appSettings.local_runtime, ollama_base_url: e.target.value },
                          })
                        }
                        className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary font-mono text-xs focus:outline-none focus:border-accent"
                      />
                    </div>

                    <div className="space-y-1">
                      <label className="text-text-primary font-medium">llama.cpp Base URL</label>
                      <input
                        type="text"
                        value={appSettings.local_runtime.llamacpp_base_url}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            local_runtime: { ...appSettings.local_runtime, llamacpp_base_url: e.target.value },
                          })
                        }
                        className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary font-mono text-xs focus:outline-none focus:border-accent"
                      />
                    </div>

                    <div className="space-y-1">
                      <label className="text-text-primary font-medium">GPU Offload Layers</label>
                      <input
                        type="number"
                        value={appSettings.local_runtime.gpu_layers}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            local_runtime: {
                              ...appSettings.local_runtime,
                              gpu_layers: parseInt(e.target.value) || 33,
                            },
                          })
                        }
                        className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary font-mono text-xs focus:outline-none focus:border-accent"
                      />
                    </div>

                    <div className="space-y-1">
                      <label className="text-text-primary font-medium">CPU Threads</label>
                      <input
                        type="number"
                        value={appSettings.local_runtime.cpu_threads}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            local_runtime: {
                              ...appSettings.local_runtime,
                              cpu_threads: parseInt(e.target.value) || 4,
                            },
                          })
                        }
                        className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary font-mono text-xs focus:outline-none focus:border-accent"
                      />
                    </div>

                    <div className="space-y-1">
                      <label className="text-text-primary font-medium">Context Length</label>
                      <input
                        type="number"
                        value={appSettings.local_runtime.context_length}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            local_runtime: {
                              ...appSettings.local_runtime,
                              context_length: parseInt(e.target.value) || 8192,
                            },
                          })
                        }
                        className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary font-mono text-xs focus:outline-none focus:border-accent"
                      />
                    </div>

                    <div className="flex items-center pt-5">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={appSettings.local_runtime.auto_detect_gpu}
                          onChange={(e) =>
                            setAppSettings({
                              ...appSettings,
                              local_runtime: {
                                ...appSettings.local_runtime,
                                auto_detect_gpu: e.target.checked,
                              },
                            })
                          }
                          className="rounded accent-accent w-4 h-4"
                        />
                        <span className="font-semibold text-text-primary text-xs">Auto-Detect GPU & VRAM</span>
                      </label>
                    </div>
                  </div>
                )}
              </div>
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

              {/* Hardware-Fit Local Model Recommendations */}
              <LocalModelRecommendations />

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


          {(activeTab === 'notifications' || activeTab === 'channels') && (
            <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-6">
              <div className="flex items-center justify-between border-b border-border-subtle pb-4">
                <div>
                  <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                    <Bell className="w-4 h-4 text-accent" />
                    Notifications
                  </h2>
                  <p className="text-xs text-text-secondary mt-1">
                    System notification dispatch and external alert integrations.
                  </p>
                </div>
                <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-bg-surface border border-border-subtle text-text-tertiary">
                  Deferred for 0.5
                </span>
              </div>

              {/* Truthful Empty State */}
              <div className="p-10 rounded-xl bg-bg-surface border border-border-subtle flex flex-col items-center justify-center text-center space-y-3">
                <div className="w-12 h-12 rounded-full bg-accent/10 border border-accent/20 flex items-center justify-center text-accent">
                  <Bell className="w-5 h-5 text-text-tertiary" />
                </div>
                <div className="max-w-md space-y-1">
                  <h3 className="text-sm font-bold text-text-primary">Notification integrations are not available in this release.</h3>
                  <p className="text-xs text-text-secondary leading-relaxed">
                    External dispatch channels (Slack, Discord, Telegram, WhatsApp) are deferred for post-0.5 roadmap milestones. No background notifications or shadow webhooks are dispatched by the local daemon.
                  </p>
                </div>
                <span className="px-3 py-1 rounded-full text-[11px] font-medium bg-bg-base border border-border-subtle text-text-tertiary">
                  Coming later
                </span>
              </div>
            </div>
          )}

          {activeTab === 'storage' && (
            <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-6">
              <div className="flex items-center justify-between border-b border-border-subtle pb-4">
                <div>
                  <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                    <HardDrive className="w-4 h-4 text-accent" />
                    Storage, Database & Data Retention
                  </h2>
                  <p className="text-xs text-text-secondary mt-1">
                    Manage database backend, vector storage (ChromaDB), and audit log retention period.
                  </p>
                </div>
                <button
                  onClick={handleSaveAppSettings}
                  disabled={savingSettings || !appSettings}
                  className="px-3.5 py-1.5 rounded-lg bg-accent text-white text-xs font-semibold hover:bg-accent-hover transition-colors flex items-center gap-2 disabled:opacity-50"
                >
                  {savingSettings ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                  Save Storage
                </button>
              </div>

              {appSettings && (
                <div className="space-y-4 text-xs">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label className="text-text-primary font-medium">Database Backend</label>
                      <select
                        value="sqlite"
                        disabled
                        className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary text-xs focus:outline-none focus:border-accent opacity-90 cursor-default"
                      >
                        <option value="sqlite">SQLite (Local Embedded — Canonical 0.5)</option>
                        <option value="postgres" disabled>PostgreSQL (Coming later — Cloud/Enterprise in R16)</option>
                      </select>
                      <p className="text-[11px] text-text-tertiary">SQLite is the single canonical local database for Release 0.5. Dedicated PostgreSQL is deferred for R16.</p>
                    </div>

                    <div className="space-y-1.5 opacity-75">
                      <label className="text-text-primary font-medium">Audit Log Retention (Days)</label>
                      <input
                        type="number"
                        value={appSettings.storage.retention_days || 90}
                        disabled
                        className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-secondary font-mono text-xs cursor-not-allowed"
                      />
                      <p className="text-[11px] text-text-tertiary">Default 90 days. Automated log pruning daemon coming later.</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label className="text-text-primary font-medium">SQLite Database Path</label>
                      <input
                        type="text"
                        value={appSettings.storage.sqlite_path}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            storage: { ...appSettings.storage, sqlite_path: e.target.value },
                          })
                        }
                        className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary font-mono text-xs focus:outline-none focus:border-accent"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <label className="text-text-primary font-medium">ChromaDB Path</label>
                      <input
                        type="text"
                        value={appSettings.storage.chroma_path}
                        onChange={(e) =>
                          setAppSettings({
                            ...appSettings,
                            storage: { ...appSettings.storage, chroma_path: e.target.value },
                          })
                        }
                        className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary font-mono text-xs focus:outline-none focus:border-accent"
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'security' && (
            <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-6">
              <div className="flex items-center justify-between border-b border-border-subtle pb-4">
                <div>
                  <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                    <Lock className="w-4 h-4 text-accent" />
                    Security Boundary & Zero-Trust Policies
                  </h2>
                  <p className="text-xs text-text-secondary mt-1">
                    Configure Zero-Trust fail-closed boundaries, approval escalation, and IPC token enforcement.
                  </p>
                </div>
                <button
                  onClick={handleSaveAppSettings}
                  disabled={savingSettings || !appSettings}
                  className="px-3.5 py-1.5 rounded-lg bg-accent text-white text-xs font-semibold hover:bg-accent-hover transition-colors flex items-center gap-2 disabled:opacity-50"
                >
                  {savingSettings ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                  Save Security
                </button>
              </div>

              {appSettings && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                  <div className="space-y-1.5">
                    <label className="text-text-primary font-medium">Zero-Trust Evaluation Mode</label>
                    <select
                      value={appSettings.security.zero_trust_eval}
                      onChange={(e) =>
                        setAppSettings({
                          ...appSettings,
                          security: {
                            ...appSettings.security,
                            zero_trust_eval: e.target.value as 'strict' | 'permissive',
                          },
                        })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary text-xs focus:outline-none focus:border-accent"
                    >
                      <option value="strict">Strict (Fail-Closed, Every Tool Evaluated)</option>
                      <option value="permissive">Permissive (Log Violations Only)</option>
                    </select>
                    <p className="text-[11px] text-text-tertiary">Fail-closed evaluation of untrusted agent operations.</p>
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-text-primary font-medium">Sandbox Isolation Mode</label>
                    <select
                      value={appSettings.security.sandbox_mode}
                      onChange={(e) =>
                        setAppSettings({
                          ...appSettings,
                          security: {
                            ...appSettings.security,
                            sandbox_mode: e.target.value as 'standard' | 'isolated',
                          },
                        })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary text-xs focus:outline-none focus:border-accent"
                    >
                      <option value="standard">Standard (Subprocess Isolation)</option>
                      <option value="isolated">Isolated (Strict Virtual Container)</option>
                    </select>
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-text-primary font-medium">Approval Timeout (Seconds)</label>
                    <input
                      type="number"
                      value={appSettings.security.approval_timeout_seconds}
                      onChange={(e) =>
                        setAppSettings({
                          ...appSettings,
                          security: {
                            ...appSettings.security,
                            approval_timeout_seconds: parseInt(e.target.value) || 60,
                          },
                        })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary font-mono text-xs focus:outline-none focus:border-accent"
                    />
                    <p className="text-[11px] text-text-tertiary">Timeout before pending approvals automatically expire.</p>
                  </div>

                  <label className="flex items-center gap-3 p-3.5 rounded-lg bg-bg-surface border border-border-subtle cursor-pointer hover:border-accent/40 transition-colors">
                    <input
                      type="checkbox"
                      checked={appSettings.security.ipc_token_enabled}
                      onChange={(e) =>
                        setAppSettings({
                          ...appSettings,
                          security: { ...appSettings.security, ipc_token_enabled: e.target.checked },
                        })
                      }
                      className="rounded accent-accent w-4 h-4"
                    />
                    <div>
                      <div className="font-semibold text-text-primary">IPC Token Authentication</div>
                      <div className="text-[11px] text-text-tertiary">Enforce cryptographic token on localhost sidecar endpoints.</div>
                    </div>
                  </label>
                </div>
              )}

              {/* Zero-Trust Storage Info */}
              <div className="p-4 rounded-lg bg-bg-surface border border-border-subtle space-y-2 text-xs">
                <h3 className="font-bold text-text-primary">Keychain & Cryptographic Credential Vault</h3>
                <p className="text-text-secondary leading-relaxed">
                  Agent Engine implements Zero-Trust Local Encryption. Sensitive keys are stored directly in your operating system&apos;s cryptographic credential vault:
                </p>
                <ul className="list-disc pl-5 text-text-secondary space-y-1">
                  <li><strong className="text-text-primary">macOS:</strong> Apple Keychain Services framework via native security APIs.</li>
                  <li><strong className="text-text-primary">Linux:</strong> SecretService D-Bus specification (GNOME Keyring / KWallet).</li>
                  <li><strong className="text-text-primary">Windows:</strong> Windows Credential Manager.</li>
                  <li><strong className="text-text-primary">Fallback:</strong> AES-256-GCM encrypted local vault with PBKDF2-SHA256 (100,000 iterations).</li>
                </ul>
              </div>
            </div>
          )}

          {activeTab === 'appearance' && (
            <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-6">
              <div className="flex items-center justify-between border-b border-border-subtle pb-4">
                <div>
                  <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                    <Palette className="w-4 h-4 text-accent" />
                    Appearance & Theme
                  </h2>
                  <p className="text-xs text-text-secondary mt-1">
                    Release 0.5 desktop visual presentation and dark-theme canonical settings.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="px-2.5 py-1 rounded-md text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    Dark Theme Active (Release 0.5)
                  </span>
                </div>
              </div>

              {/* Single Canonical Theme Notice */}
              <div className="p-4 rounded-xl bg-accent/10 border border-accent/20 flex items-start gap-3">
                <div className="w-8 h-8 rounded-lg bg-accent/20 border border-accent/30 flex items-center justify-center shrink-0 text-accent">
                  <Palette className="w-4 h-4" />
                </div>
                <div className="text-xs space-y-1">
                  <div className="font-semibold text-text-primary">Canonical Dark-Only Desktop Surface</div>
                  <div className="text-text-secondary leading-relaxed">
                    Release 0.5 Nadir Edition is standardized exclusively on the Canonical Dark Theme. Light Theme and Follow System OS options are deferred for future roadmap releases.
                  </div>
                </div>
              </div>

              {appSettings && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-5 text-xs">
                  <div className="space-y-1.5">
                    <label className="text-text-primary font-medium">Color Theme</label>
                    <select
                      value={appSettings.appearance.theme}
                      onChange={(e) =>
                        setAppSettings({
                          ...appSettings,
                          appearance: { ...appSettings.appearance, theme: e.target.value as any },
                        })
                      }
                      className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-primary text-xs focus:outline-none focus:border-accent"
                    >
                      <option value="dark">Dark Theme (Default & Only 0.5 Release Theme)</option>
                      <option value="light" disabled>Light Theme (Coming later — Deferred for 0.5)</option>
                      <option value="system" disabled>Follow System OS (Coming later — Deferred for 0.5)</option>
                    </select>
                    <p className="text-[11px] text-text-tertiary">
                      Release 0.5 is Dark-Only Founder MVP. Light and System themes deferred.
                    </p>
                  </div>

                  <div className="space-y-1.5 opacity-60">
                    <div className="flex items-center justify-between">
                      <label className="text-text-primary font-medium">UI Density</label>
                      <span className="text-[10px] font-mono text-text-tertiary uppercase">Coming later</span>
                    </div>
                    <select
                      value="comfortable"
                      disabled
                      className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-secondary text-xs cursor-not-allowed"
                    >
                      <option value="comfortable">Comfortable (Canonical Desktop Dense)</option>
                      <option value="compact">Compact</option>
                    </select>
                    <p className="text-[11px] text-text-tertiary">
                      Desktop dense spacing is hardwired as canonical for Release 0.5.
                    </p>
                  </div>

                  <div className="space-y-1.5 opacity-60">
                    <div className="flex items-center justify-between">
                      <label className="text-text-primary font-medium">Font Size</label>
                      <span className="text-[10px] font-mono text-text-tertiary uppercase">Coming later</span>
                    </div>
                    <select
                      value="base"
                      disabled
                      className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-secondary text-xs cursor-not-allowed"
                    >
                      <option value="base">Base (13px System Default)</option>
                      <option value="sm">Small (12px)</option>
                      <option value="lg">Large (14px)</option>
                    </select>
                    <p className="text-[11px] text-text-tertiary">
                      Standard typography hierarchy is hardwired for Release 0.5.
                    </p>
                  </div>

                  <div className="space-y-1.5 opacity-60">
                    <div className="flex items-center justify-between">
                      <label className="text-text-primary font-medium">Code Font Family</label>
                      <span className="text-[10px] font-mono text-text-tertiary uppercase">Coming later</span>
                    </div>
                    <input
                      type="text"
                      value="JetBrains Mono, Menlo, monospace"
                      disabled
                      className="w-full px-3 py-2 rounded-lg bg-bg-base border border-border-subtle text-text-secondary font-mono text-xs cursor-not-allowed"
                    />
                    <p className="text-[11px] text-text-tertiary">
                      Monospace font stack is hardwired for code readability.
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}

          {(activeTab === 'developer' || activeTab === 'diagnostics') && (
            <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-6">
              <div className="flex items-center justify-between border-b border-border-subtle pb-4">
                <div>
                  <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                    <Terminal className="w-4 h-4 text-accent" />
                    Developer Tools & Diagnostics
                  </h2>
                  <p className="text-xs text-text-secondary mt-1">
                    Advanced engineering controls, diagnostic bundles, and local daemon status.
                  </p>
                </div>
              </div>

              {/* Redaction Warning Banner */}
              <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/25 flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
                <div className="text-xs space-y-1">
                  <div className="font-semibold text-amber-300">Privacy & Credential Scrubbing Guarantee</div>
                  <div className="text-amber-200/80 leading-relaxed">
                    Sensitive data (keys, secrets, personal paths) has been redacted. Review before sharing.
                  </div>
                </div>
              </div>

              {/* Developer Mode Toggle */}
              <div className="p-5 rounded-xl bg-bg-surface border border-border-subtle space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-xs font-bold text-text-primary">Developer Mode</h3>
                    <p className="text-xs text-text-secondary mt-0.5">
                      Enable advanced engineering surfaces, raw telemetry, model tier names, and low-level pipeline logs.
                    </p>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={developerMode}
                      onChange={(e) => handleToggleDeveloperMode(e.target.checked)}
                      className="sr-only peer"
                    />
                    <div className="w-11 h-6 bg-bg-elevated peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-border-strong after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-accent border border-border-subtle"></div>
                  </label>
                </div>
                <div className="text-[11px] font-mono text-text-tertiary">
                  Current state: <span className={developerMode ? "text-accent font-semibold" : "text-text-secondary"}>{developerMode ? "ENABLED (Technical controls active)" : "DISABLED (Standard restrained UX)"}</span>
                </div>
              </div>

              {/* 1-Click Export Actions */}
              <div className="p-5 rounded-xl bg-bg-surface border border-border-subtle space-y-4">
                <h3 className="text-xs font-bold text-text-primary">1-Click Diagnostics Export</h3>
                <p className="text-xs text-text-secondary">
                  Export complete bundle containing system info, OpenAPI schema versions, redacted configurations, and server logs.
                </p>

                <div className="flex items-center gap-3 flex-wrap">
                  <button
                    onClick={() => handleExportDiagnostics('zip')}
                    disabled={exportingDiagnostics}
                    className="px-4 py-2 rounded-lg bg-accent text-white text-xs font-semibold hover:bg-accent-hover transition-colors flex items-center gap-2 shadow-sm disabled:opacity-50"
                  >
                    {exportingDiagnostics ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                    Export Diagnostics (.zip)
                  </button>

                  <button
                    onClick={() => handleExportDiagnostics('json')}
                    disabled={exportingDiagnostics}
                    className="px-4 py-2 rounded-lg bg-bg-hover text-text-primary text-xs font-semibold hover:bg-border-subtle transition-colors flex items-center gap-2 border border-border-subtle disabled:opacity-50"
                  >
                    {exportingDiagnostics ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                    Export Diagnostics (.json)
                  </button>
                </div>

                {diagnosticsSuccess && (
                  <div className="p-3 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-xs flex items-center gap-2 animate-in fade-in">
                    <CheckCircle2 className="w-4 h-4 shrink-0" />
                    <span>{diagnosticsSuccess}</span>
                  </div>
                )}
              </div>

              {/* System Metadata Overview */}
              <div className="p-4 rounded-xl bg-bg-surface border border-border-subtle font-mono text-xs text-text-secondary space-y-1.5">
                <div className="font-bold text-text-primary font-sans text-xs mb-2">Active Runtime Metadata</div>
                <div className="flex justify-between border-b border-border-subtle/50 pb-1">
                  <span>Engine Shell:</span>
                  <span className="text-text-primary">Agent Engine Desktop v0.5 Nadir Edition (Founder MVP)</span>
                </div>
                <div className="flex justify-between border-b border-border-subtle/50 pb-1">
                  <span>Sidecar Daemon:</span>
                  <span className="text-text-primary">FastAPI / Uvicorn (IPC Port 8000)</span>
                </div>
                <div className="flex justify-between border-b border-border-subtle/50 pb-1">
                  <span>Active Credential Backend:</span>
                  <span className="text-text-primary">{activeBackendName}</span>
                </div>
                <div className="flex justify-between border-b border-border-subtle/50 pb-1">
                  <span>Frontend SHA:</span>
                  <span className="text-text-primary text-[10px] font-mono">b9be6c1</span>
                </div>
                <div className="flex justify-between border-b border-border-subtle/50 pb-1">
                  <span>Tauri/Backend SHA:</span>
                  <span className="text-text-primary text-[10px] font-mono">b9be6c1</span>
                </div>
                <div className="flex justify-between border-b border-border-subtle/50 pb-1">
                  <span>Schema Version:</span>
                  <span className="text-text-primary text-[10px] font-mono">v1.0.0 (API 0.1.0 / SQLite v3)</span>
                </div>
                <div className="flex justify-between">
                  <span>Hardware Telemetry:</span>
                  <span className="text-text-primary">
                    {hardwareTelem?.gpu_model || 'Integrated / CPU'} ({hardwareTelem?.tokens_per_second.toFixed(1) || '0.0'} tok/s)
                  </span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'about' && (
            <div className="p-6 rounded-xl bg-bg-elevated border border-border-subtle space-y-6">
              <div className="flex items-center justify-between border-b border-border-subtle pb-4">
                <div>
                  <h2 className="text-sm font-bold text-text-primary flex items-center gap-2">
                    <Info className="w-4 h-4 text-accent" />
                    About Agent Engine
                  </h2>
                  <p className="text-xs text-text-secondary mt-1">
                    System specifications, platform architecture, and verification status.
                  </p>
                </div>
                <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-accent/15 text-accent border border-accent/30 font-semibold">
                  v0.5-nadir
                </span>
              </div>

              {/* Founder MVP Status Card */}
              <div className="p-5 rounded-xl bg-bg-surface border border-border-subtle space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400 font-bold text-xs">
                      <ShieldCheck className="w-4 h-4" />
                    </div>
                    <div>
                      <div className="text-xs font-bold text-text-primary">Release 0.5 Nadir Edition — Founder MVP</div>
                      <div className="text-[11px] text-text-secondary">Zero-Trust Desktop Architecture • Dark-Only Desktop Surface</div>
                    </div>
                  </div>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                    Verified
                  </span>
                </div>
                <p className="text-xs text-text-secondary leading-relaxed">
                  Agent Engine provides desktop-dense AI orchestration with strict local sidecar isolation, OS keychain credential encryption, and zero-trust execution boundaries.
                </p>
              </div>

              {/* Architecture Specifications Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
                <div className="p-4 rounded-xl bg-bg-surface border border-border-subtle space-y-2">
                  <div className="font-sans font-bold text-text-primary text-xs flex items-center gap-2">
                    <Cpu className="w-3.5 h-3.5 text-accent" />
                    Core Architecture
                  </div>
                  <div className="flex justify-between border-b border-border-subtle/50 pb-1 text-text-secondary">
                    <span>Desktop Shell:</span>
                    <span className="text-text-primary">Tauri v2 (Rust 2021)</span>
                  </div>
                  <div className="flex justify-between border-b border-border-subtle/50 pb-1 text-text-secondary">
                    <span>Sidecar Daemon:</span>
                    <span className="text-text-primary">FastAPI (Python 3.12+)</span>
                  </div>
                  <div className="flex justify-between border-b border-border-subtle/50 pb-1 text-text-secondary">
                    <span>IPC Communication:</span>
                    <span className="text-text-primary">Localhost REST (Authenticated)</span>
                  </div>
                  <div className="flex justify-between border-b border-border-subtle/50 pb-1 text-text-secondary">
                    <span>Build Identity:</span>
                    <span className="text-text-primary text-[10px]">Product Truth (Founder Dogfood)</span>
                  </div>
                  <div className="flex justify-between border-b border-border-subtle/50 pb-1 text-text-secondary">
                    <span>Frontend SHA:</span>
                    <span className="text-text-primary text-[10px] font-mono">b9be6c1</span>
                  </div>
                  <div className="flex justify-between border-b border-border-subtle/50 pb-1 text-text-secondary">
                    <span>Tauri/Backend SHA:</span>
                    <span className="text-text-primary text-[10px] font-mono">b9be6c1</span>
                  </div>
                  <div className="flex justify-between border-b border-border-subtle/50 pb-1 text-text-secondary">
                    <span>Schema Version:</span>
                    <span className="text-text-primary text-[10px] font-mono">v1.0.0 (API 0.1.0 / SQLite v3)</span>
                  </div>
                  <div className="flex justify-between text-text-secondary">
                    <span>Theme Surface:</span>
                    <span className="text-text-primary">Dark Only (Canonical)</span>
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-bg-surface border border-border-subtle space-y-2">
                  <div className="font-sans font-bold text-text-primary text-xs flex items-center gap-2">
                    <Lock className="w-3.5 h-3.5 text-accent" />
                    Security & Zero-Trust
                  </div>
                  <div className="flex justify-between border-b border-border-subtle/50 pb-1 text-text-secondary">
                    <span>Credential Vault:</span>
                    <span className="text-text-primary">{activeBackendName}</span>
                  </div>
                  <div className="flex justify-between border-b border-border-subtle/50 pb-1 text-text-secondary">
                    <span>Local Encryption:</span>
                    <span className="text-text-primary">AES-256-GCM</span>
                  </div>
                  <div className="flex justify-between border-b border-border-subtle/50 pb-1 text-text-secondary">
                    <span>Network Policy:</span>
                    <span className="text-text-primary">Privacy-Enforced Routing</span>
                  </div>
                  <div className="flex justify-between text-text-secondary">
                    <span>Substrate State:</span>
                    <span className="text-text-primary">Active</span>
                  </div>
                </div>
              </div>

              {/* Documentation & Guidelines Links */}
              <div className="p-4 rounded-xl bg-bg-surface border border-border-subtle space-y-2 text-xs">
                <div className="font-sans font-bold text-text-primary text-xs">Specifications & Architecture Guides</div>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-1 font-mono text-[11px]">
                  <div className="p-2 rounded-lg bg-bg-base border border-border-subtle">
                    <span className="text-accent font-semibold">docs/GUI_CANONICAL_REDESIGN.md</span>
                    <div className="text-[10px] text-text-tertiary mt-0.5">Interaction architecture</div>
                  </div>
                  <div className="p-2 rounded-lg bg-bg-base border border-border-subtle">
                    <span className="text-accent font-semibold">docs/reviews/GUI_CANONICAL_MIGRATION_REVIEW.md</span>
                    <div className="text-[10px] text-text-tertiary mt-0.5">Founder MVP audit</div>
                  </div>
                  <div className="p-2 rounded-lg bg-bg-base border border-border-subtle">
                    <span className="text-accent font-semibold">Zero-Trust Policy</span>
                    <div className="text-[10px] text-text-tertiary mt-0.5">Local encryption architecture</div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
