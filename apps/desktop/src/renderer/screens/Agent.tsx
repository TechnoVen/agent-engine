import React, { useState, useEffect } from 'react';
import {
  User,
  Brain,
  Sliders,
  FileText,
  ShieldCheck,
  Plus,
  RefreshCw,
  Check,
  Save,
} from 'lucide-react';
import { sidecarClient } from '../api/client';
import { Mode, PrivacyBoundary, ModelTier } from '../types';

export interface AgentScreenProps {
  onSelectMode?: (mode: Mode) => void;
  activeModel?: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
}

export type ProfileTab = 'preferences' | 'memory' | 'instructions' | 'privacy';

export const Agent: React.FC<AgentScreenProps> = () => {
  const [activeTab, setActiveTab] = useState<ProfileTab>('preferences');
  const [memories, setMemories] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [newMemory, setNewMemory] = useState('');
  const [instructions, setInstructions] = useState(() => {
    const raw = localStorage.getItem('agent_engine_user_instructions');
    if (raw) {
      return raw.replace(/\s*\(Law\s*3\)/gi, '');
    }
    return (
      'You are Agent Engine, a deterministic engineering assistant. Prioritize local models and zero-trust safety guardrails. Never produce sycophantic or marketing language.'
    );
  });
  const [privacyBoundary, setPrivacyBoundary] = useState<PrivacyBoundary>(() => {
    return (localStorage.getItem('agent_engine_privacy_boundary') as PrivacyBoundary) || 'local_only';
  });
  const [savedNotice, setSavedNotice] = useState(false);

  const loadMemories = async () => {
    setIsLoading(true);
    try {
      const results = await sidecarClient.queryObservations(searchQuery.trim() || 'preference instruction fact', 50);
      setMemories(results || []);
    } catch {
      setMemories([]);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadMemories();
  }, [searchQuery]);

  const handleAddMemory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newMemory.trim()) return;

    try {
      await sidecarClient.observeMemory({
        content: newMemory.trim(),
        category: 'user_preference',
        importance: 0.9,
      });
      setNewMemory('');
      await loadMemories();
    } catch (err) {
      console.error('Failed to record memory', err);
    }
  };

  const handleSaveInstructions = () => {
    localStorage.setItem('agent_engine_user_instructions', instructions);
    setSavedNotice(true);
    setTimeout(() => setSavedNotice(false), 2000);
  };

  const handleSavePrivacy = (boundary: PrivacyBoundary) => {
    setPrivacyBoundary(boundary);
    localStorage.setItem('agent_engine_privacy_boundary', boundary);
  };

  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden" data-testid="profile-memory-screen">
      {/* Header */}
      <div className="h-12 border-b border-border-subtle bg-bg-elevated px-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <User className="w-4 h-4 text-accent" />
          <h1 className="text-sm font-semibold tracking-tight text-text-primary">Profile & Memory</h1>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-text-tertiary uppercase">
            User Workspace Context
          </span>
        </div>
      </div>

      {/* Tabs */}
      <div className="px-4 py-2 border-b border-border-subtle bg-bg-elevated/50 flex items-center gap-1 text-xs">
        {[
          { id: 'preferences', label: 'Preferences', icon: Sliders },
          { id: 'memory', label: 'Memory', icon: Brain },
          { id: 'instructions', label: 'Instructions', icon: FileText },
          { id: 'privacy', label: 'Privacy Boundary', icon: ShieldCheck },
        ].map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id as ProfileTab)}
              className={`flex items-center gap-1.5 px-3 py-1 rounded font-medium transition-colors ${
                activeTab === tab.id
                  ? 'bg-bg-elevated text-text-primary shadow-xs border border-border-subtle'
                  : 'text-text-tertiary hover:text-text-secondary'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Main Tab Content */}
      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6 max-w-4xl">
        {activeTab === 'preferences' && (
          <div className="space-y-4">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-text-primary">Default Operator Preferences</h2>
              <p className="text-xs text-text-secondary">
                Configure persistent system behavior and execution preferences across sessions.
              </p>
            </div>

            <div className="border border-border-subtle rounded-lg bg-bg-elevated/40 divide-y divide-border-subtle text-xs">
              <div className="p-4 flex items-center justify-between">
                <div>
                  <div className="font-semibold text-text-primary">Model Routing Preference</div>
                  <div className="text-[11px] text-text-tertiary">Select default routing bias for universal prompt composer</div>
                </div>
                <span className="font-mono text-accent">Balanced (Cost vs Quality)</span>
              </div>

              <div className="p-4 flex items-center justify-between">
                <div>
                  <div className="font-semibold text-text-primary">Zero-Trust Approval Threshold</div>
                  <div className="text-[11px] text-text-tertiary">Require operator token on disk mutations and shell execution</div>
                </div>
                <span className="font-mono text-emerald-400">Strict (Zero-Trust Active)</span>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'memory' && (
          <div className="space-y-4">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-text-primary">Observational Memory</h2>
              <p className="text-xs text-text-secondary">
                Verified user facts and workspace constraints learned by the local observation kernel.
              </p>
            </div>

            {/* Filter and Add Memory Form */}
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search observational memories..."
                className="w-full sm:w-1/3 px-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
              />
            </div>

            <form onSubmit={handleAddMemory} className="flex gap-2">
              <input
                type="text"
                value={newMemory}
                onChange={(e) => setNewMemory(e.target.value)}
                placeholder="Add verified user fact or preference..."
                className="flex-1 px-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
              />
              <button
                type="submit"
                className="px-3 py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium flex items-center gap-1.5 transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Add Memory</span>
              </button>
            </form>

            {/* Memories List */}
            {isLoading ? (
              <div className="py-12 text-center text-xs text-text-tertiary">
                <RefreshCw className="w-5 h-5 mx-auto animate-spin mb-2 text-accent" />
                Querying memory database...
              </div>
            ) : memories.length === 0 ? (
              <div className="py-12 text-center border border-border-subtle rounded-lg bg-bg-elevated/30 text-xs text-text-tertiary">
                No memories recorded yet.
              </div>
            ) : (
              <div className="border border-border-subtle rounded-lg bg-bg-elevated/40 divide-y divide-border-subtle">
                {memories.map((m) => (
                  <div key={m.id} className="p-3.5 flex items-center justify-between text-xs font-mono">
                    <div className="space-y-0.5 max-w-xl">
                      <div className="text-text-primary">{m.content}</div>
                      <div className="text-[10px] text-text-tertiary">Category: {m.category} · Score: {m.relevance_score?.toFixed(2) || '1.0'}</div>
                    </div>
                    <span className="text-[10px] text-text-tertiary">{m.created_at ? new Date(m.created_at).toLocaleDateString() : 'Recent'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'instructions' && (
          <div className="space-y-4">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-text-primary">System Instructions</h2>
              <p className="text-xs text-text-secondary">
                Custom system prompt instructions automatically injected into every prompt completion.
              </p>
            </div>

            <div className="space-y-2">
              <textarea
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                rows={6}
                className="w-full p-3 bg-bg-base border border-border-subtle rounded-lg text-xs font-mono text-text-primary focus:outline-none focus:border-accent leading-relaxed resize-none"
              />
              <div className="flex items-center justify-between">
                <span className="text-[11px] text-text-tertiary font-mono">
                  {instructions.length} characters
                </span>
                <button
                  type="button"
                  onClick={handleSaveInstructions}
                  className="px-3 py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium flex items-center gap-1.5 transition-colors"
                >
                  {savedNotice ? <Check className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />}
                  <span>{savedNotice ? 'Saved!' : 'Save Instructions'}</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'privacy' && (
          <div className="space-y-4">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-text-primary">Data Routing Privacy Boundary</h2>
              <p className="text-xs text-text-secondary">
                Enforce strict physical boundary controls on where token payloads and session context may travel.
              </p>
            </div>

            <div className="space-y-2 text-xs">
              {[
                { id: 'local_only', title: 'Local Only (Airgapped)', desc: 'Denies all outbound external cloud API calls. Strictly runs on local GGUF models.' },
                { id: 'anonymized_cloud', title: 'Anonymized Cloud Allowed', desc: 'Allows cloud API execution with PII, IP, and credential stripping.' },
                { id: 'full_cloud', title: 'Full Cloud Allowed', desc: 'Allows direct frontier model execution (OpenAI, Anthropic, Gemini).' },
              ].map((p) => (
                <div
                  key={p.id}
                  onClick={() => handleSavePrivacy(p.id as PrivacyBoundary)}
                  className={`p-3.5 rounded-lg border cursor-pointer transition-all ${
                    privacyBoundary === p.id
                      ? 'bg-accent/10 border-accent text-text-primary'
                      : 'bg-bg-elevated/40 border-border-subtle hover:border-border-strong text-text-secondary'
                  }`}
                >
                  <div className="font-semibold text-sm flex items-center justify-between">
                    <span>{p.title}</span>
                    {privacyBoundary === p.id && <Check className="w-4 h-4 text-accent" />}
                  </div>
                  <p className="text-[11px] text-text-tertiary mt-1 leading-relaxed">{p.desc}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
