import React, { useState, useEffect, useMemo } from 'react';
import {
  Sparkles,
  Brain,
  TrendingUp,
  Database,
  Coins,
  Search,
  Plus,
  Edit2,
  Trash2,
  Check,
  X,
  Flame,
  Calendar,
  Activity,
  Award,
  Zap,
  ShieldCheck,
} from 'lucide-react';
import { Mode, ModelTier } from '../types';
import { ChatInput } from '../components/ChatInput';
import { sidecarClient } from '../api/client';

export interface AgentScreenProps {
  onSelectMode: (mode: Mode) => void;
  activeModel: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
}

type TabType = 'closeness' | 'growth' | 'memory' | 'cost';

interface MemoryItem {
  id: string;
  content: string;
  category: string;
  importance: number;
  createdAt: string;
}

const INITIAL_MEMORIES: MemoryItem[] = [
  {
    id: 'm1',
    content: 'Prefers local-first execution with zero cloud calls whenever latency < 500ms.',
    category: 'preference',
    importance: 0.95,
    createdAt: '2026-03-10',
  },
  {
    id: 'm2',
    content: 'Uses Tauri v2 + React 18 + Tailwind CSS as the standard desktop GUI architecture.',
    category: 'fact',
    importance: 0.9,
    createdAt: '2026-03-08',
  },
  {
    id: 'm3',
    content: 'Always enforces 90/9/1 routing discipline to prevent frontier model cost overrun.',
    category: 'preference',
    importance: 0.98,
    createdAt: '2026-03-05',
  },
  {
    id: 'm4',
    content: 'Workspace data directory lives canonically under ~/code/agent_engine/data.',
    category: 'fact',
    importance: 0.85,
    createdAt: '2026-03-01',
  },
  {
    id: 'm5',
    content: 'Automates PR reviews with high-assurance security policies and AST sanity checks.',
    category: 'workflow',
    importance: 0.88,
    createdAt: '2026-02-28',
  },
];

export const Agent: React.FC<AgentScreenProps> = ({
  onSelectMode,
  activeModel,
  onSelectModel,
  inputRef,
}) => {
  const [activeTab, setActiveTab] = useState<TabType>('closeness');
  const [selfGrowthEnabled, setSelfGrowthEnabled] = useState<boolean>(() => {
    return localStorage.getItem('agent-engine-self-growth') !== 'false';
  });

  // Observational memory table state
  const [memories, setMemories] = useState<MemoryItem[]>(INITIAL_MEMORIES);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [newMemoryContent, setNewMemoryContent] = useState('');
  const [newMemoryCategory, setNewMemoryCategory] = useState('preference');
  const [isAddingMemory, setIsAddingMemory] = useState(false);

  // Toggle self-growth persistence
  const handleToggleSelfGrowth = () => {
    const next = !selfGrowthEnabled;
    setSelfGrowthEnabled(next);
    localStorage.setItem('agent-engine-self-growth', String(next));
  };

  // Fetch real-time observations from sidecar
  useEffect(() => {
    let mounted = true;
    const loadObservations = async () => {
      try {
        const obs = await sidecarClient.queryObservations('user preferences and project facts', 15);
        if (mounted && obs.length > 0) {
          const mapped: MemoryItem[] = obs.map((o: any) => ({
            id: o.id || `${Date.now()}-${Math.random()}`,
            content: o.content,
            category: o.category || 'general',
            importance: o.importance ?? 0.8,
            createdAt: o.created_at ? o.created_at.slice(0, 10) : 'Recent',
          }));
          setMemories((prev) => {
            const ids = new Set(prev.map((m) => m.id));
            const fresh = mapped.filter((m) => !ids.has(m.id));
            return [...fresh, ...prev];
          });
        }
      } catch {
        // Fallback to initial memories if offline
      }
    };
    loadObservations();
    return () => {
      mounted = false;
    };
  }, []);

  // Filtered memories
  const filteredMemories = useMemo(() => {
    return memories.filter((m) => {
      const matchesSearch =
        m.content.toLowerCase().includes(searchQuery.toLowerCase()) ||
        m.category.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesCat = selectedCategory === 'all' || m.category === selectedCategory;
      return matchesSearch && matchesCat;
    });
  }, [memories, searchQuery, selectedCategory]);

  // Inline memory edits
  const handleStartEdit = (m: MemoryItem) => {
    setEditingMemoryId(m.id);
    setEditContent(m.content);
  };

  const handleSaveEdit = (id: string) => {
    setMemories((prev) =>
      prev.map((m) => (m.id === id ? { ...m, content: editContent.trim() } : m))
    );
    setEditingMemoryId(null);
  };

  const handleDeleteMemory = (id: string) => {
    setMemories((prev) => prev.filter((m) => m.id !== id));
  };

  const handleCreateMemory = async () => {
    if (!newMemoryContent.trim()) return;
    const newEntry: MemoryItem = {
      id: `m-${Date.now()}`,
      content: newMemoryContent.trim(),
      category: newMemoryCategory,
      importance: 0.9,
      createdAt: new Date().toISOString().slice(0, 10),
    };
    setMemories((prev) => [newEntry, ...prev]);
    setNewMemoryContent('');
    setIsAddingMemory(false);

    try {
      await sidecarClient.observeMemory({
        content: newEntry.content,
        category: newEntry.category,
        importance: newEntry.importance,
      });
    } catch {
      // offline dev fallback
    }
  };

  // Generate deterministic 365-day heatmap
  const heatmapData = useMemo(() => {
    const days: { date: string; count: number; level: number }[] = [];
    const today = new Date();
    for (let i = 364; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(d.getDate() - i);
      const iso = d.toISOString().slice(0, 10);
      const hash = Array.from(iso).reduce((acc, char) => acc + char.charCodeAt(0), 0);
      const count = (hash % 7 === 0 || hash % 11 === 0) ? (hash % 12) + 1 : 0;
      let level = 0;
      if (count > 0 && count <= 2) level = 1;
      else if (count > 2 && count <= 5) level = 2;
      else if (count > 5 && count <= 8) level = 3;
      else if (count > 8) level = 4;
      days.push({ date: iso, count, level });
    }
    return days;
  }, []);

  return (
    <div className="h-full flex flex-col justify-between overflow-hidden bg-bg-base relative select-none">
      {/* Scrollable Main Area */}
      <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 scrollbar-thin">
        <div className="w-full max-w-[880px] mx-auto space-y-6">
          {/* Header & Identity Card */}
          <div className="p-6 rounded-2xl bg-bg-elevated border border-border-subtle shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="flex items-center gap-4">
              <div className="relative">
                <div className="w-16 h-16 rounded-2xl bg-accent/15 border border-accent/40 flex items-center justify-center text-accent shadow-inner">
                  <Brain className="w-8 h-8" />
                </div>
                <span className="absolute bottom-0 right-0 w-3.5 h-3.5 rounded-full bg-success ring-4 ring-bg-elevated" />
              </div>
              <div className="space-y-1 text-left">
                <div className="flex items-center gap-2">
                  <h1 className="text-xl font-bold text-text-primary tracking-tight">
                    Nadir&apos;s Agent
                  </h1>
                  <span className="px-2 py-0.5 rounded-full bg-accent/10 border border-accent/20 text-[11px] font-medium text-accent">
                    Level 14 · Autonomous Specialist
                  </span>
                </div>
                <p className="text-xs text-text-secondary max-w-md leading-relaxed">
                  Self-evolving local intelligence grounded in your private observations, AST code
                  maps, and 90/9/1 cost-routed workflows.
                </p>
              </div>
            </div>

            {/* Self-Growth Toggle */}
            <div className="flex items-center gap-3 self-start md:self-center p-3 rounded-xl bg-bg-base border border-border-subtle text-left">
              <div className="space-y-0.5">
                <div className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-accent" />
                  <span>Self-Growth</span>
                </div>
                <div className="text-[10px] text-text-tertiary max-w-[140px]">
                  Learns preferences across sessions
                </div>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={selfGrowthEnabled}
                aria-label="Toggle agent self-growth learning"
                onClick={handleToggleSelfGrowth}
                className={`w-11 h-6 rounded-full transition-colors relative p-0.5 focus:outline-none ${
                  selfGrowthEnabled ? 'bg-accent' : 'bg-border-strong'
                }`}
              >
                <div
                  className={`w-5 h-5 rounded-full bg-white transition-transform ${
                    selfGrowthEnabled ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
          </div>

          {/* Stats Strip */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-left">
            <div className="p-3.5 rounded-xl bg-bg-elevated border border-border-subtle">
              <div className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary">
                Age
              </div>
              <div className="text-lg font-bold text-text-primary mt-0.5">271 days</div>
              <div className="text-[10px] text-text-tertiary">Since birth</div>
            </div>
            <div className="p-3.5 rounded-xl bg-bg-elevated border border-border-subtle">
              <div className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary">
                Conversations
              </div>
              <div className="text-lg font-bold text-text-primary mt-0.5">142 chats</div>
              <div className="text-[10px] text-text-tertiary">1,840 messages</div>
            </div>
            <div className="p-3.5 rounded-xl bg-bg-elevated border border-border-subtle">
              <div className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary flex items-center gap-1">
                <Flame className="w-3 h-3 text-warning" />
                <span>Streak</span>
              </div>
              <div className="text-lg font-bold text-warning mt-0.5">12 days</div>
              <div className="text-[10px] text-text-tertiary">Active daily</div>
            </div>
            <div className="p-3.5 rounded-xl bg-bg-elevated border border-border-subtle">
              <div className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary flex items-center gap-1">
                <Coins className="w-3 h-3 text-success" />
                <span>Cost Saved</span>
              </div>
              <div className="text-lg font-bold text-success mt-0.5">$18.42</div>
              <div className="text-[10px] text-text-tertiary">Via 90/9/1 split</div>
            </div>
            <div className="p-3.5 rounded-xl bg-bg-elevated border border-border-subtle">
              <div className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary flex items-center gap-1">
                <Database className="w-3 h-3 text-accent" />
                <span>Memories</span>
              </div>
              <div className="text-lg font-bold text-accent mt-0.5">{memories.length} facts</div>
              <div className="text-[10px] text-text-tertiary">Observational items</div>
            </div>
          </div>

          {/* GitHub-Style 365-Day Contribution Heatmap */}
          <div className="p-5 rounded-2xl bg-bg-elevated border border-border-subtle text-left space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Calendar className="w-4 h-4 text-accent" />
                <h3 className="text-xs font-semibold uppercase tracking-wider text-text-primary">
                  365-Day Collaboration Heatmap
                </h3>
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-text-tertiary">
                <span>Less</span>
                <span className="w-2.5 h-2.5 rounded-sm bg-border-subtle/50 inline-block" />
                <span className="w-2.5 h-2.5 rounded-sm bg-accent/30 inline-block" />
                <span className="w-2.5 h-2.5 rounded-sm bg-accent/60 inline-block" />
                <span className="w-2.5 h-2.5 rounded-sm bg-accent/90 inline-block" />
                <span className="w-2.5 h-2.5 rounded-sm bg-accent inline-block" />
                <span>More</span>
              </div>
            </div>

            {/* Heatmap Grid */}
            <div
              data-testid="agent-heatmap-grid"
              className="overflow-x-auto pb-1 scrollbar-thin"
            >
              <div className="grid grid-rows-7 grid-flow-col gap-1 w-max">
                {heatmapData.map((cell, index) => {
                  let bgClass = 'bg-border-subtle/30';
                  if (cell.level === 1) bgClass = 'bg-accent/30';
                  if (cell.level === 2) bgClass = 'bg-accent/60';
                  if (cell.level === 3) bgClass = 'bg-accent/90';
                  if (cell.level === 4) bgClass = 'bg-accent';

                  return (
                    <div
                      key={index}
                      title={`${cell.count} interactions on ${cell.date}`}
                      className={`w-2.5 h-2.5 rounded-sm transition-transform hover:scale-125 cursor-pointer ${bgClass}`}
                    />
                  );
                })}
              </div>
            </div>
          </div>

          {/* Tab Navigation */}
          <div className="flex items-center gap-2 border-b border-border-subtle pb-2">
            {[
              { id: 'closeness' as TabType, label: 'Closeness & Network', icon: Activity },
              { id: 'growth' as TabType, label: 'Growth & Skills', icon: TrendingUp },
              { id: 'memory' as TabType, label: 'Observational Memory', icon: Database },
              { id: 'cost' as TabType, label: 'Cost Efficiency', icon: Coins },
            ].map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-medium transition-all ${
                    isActive
                      ? 'bg-accent/15 text-accent border border-accent/30'
                      : 'text-text-secondary hover:text-text-primary hover:bg-bg-elevated'
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>

          {/* Tab 1: Closeness & Network */}
          {activeTab === 'closeness' && (
            <div className="space-y-4 animate-fade-in text-left">
              {/* Animated Memory Network Dots Visualizer */}
              <div className="p-6 rounded-2xl bg-bg-elevated border border-border-subtle relative overflow-hidden">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                      Dynamic Memory Network
                    </h3>
                    <p className="text-[11px] text-text-secondary">
                      Real-time neural topology of indexed preferences and grounded workspace entities.
                    </p>
                  </div>
                  <span className="px-2 py-0.5 rounded-md bg-accent/10 text-accent text-[10px] font-mono">
                    28 Connected Nodes
                  </span>
                </div>

                <div
                  data-testid="animated-memory-dots"
                  className="h-44 w-full rounded-xl bg-bg-base/60 border border-border-subtle relative flex items-center justify-center overflow-hidden"
                >
                  {/* Subtle animated SVG memory nodes */}
                  <svg className="w-full h-full absolute inset-0 pointer-events-none opacity-80">
                    <line x1="20%" y1="30%" x2="50%" y2="50%" stroke="var(--accent)" strokeWidth="1" strokeDasharray="3 3" opacity="0.4" />
                    <line x1="50%" y1="50%" x2="80%" y2="35%" stroke="var(--accent)" strokeWidth="1" strokeDasharray="3 3" opacity="0.4" />
                    <line x1="50%" y1="50%" x2="35%" y2="75%" stroke="var(--accent)" strokeWidth="1" strokeDasharray="3 3" opacity="0.4" />
                    <line x1="50%" y1="50%" x2="70%" y2="70%" stroke="var(--accent)" strokeWidth="1" strokeDasharray="3 3" opacity="0.4" />
                    <line x1="20%" y1="30%" x2="35%" y2="75%" stroke="var(--accent)" strokeWidth="0.5" opacity="0.2" />
                    <line x1="80%" y1="35%" x2="70%" y2="70%" stroke="var(--accent)" strokeWidth="0.5" opacity="0.2" />
                  </svg>

                  {/* Pulsating memory dots */}
                  <div className="absolute top-[28%] left-[19%] flex flex-col items-center">
                    <div className="w-3.5 h-3.5 rounded-full bg-accent animate-ping opacity-40 absolute" />
                    <div className="w-3.5 h-3.5 rounded-full bg-accent shadow-md shadow-accent/50" />
                    <span className="text-[9px] font-mono text-text-tertiary mt-1">code_rules</span>
                  </div>

                  <div className="absolute top-[46%] left-[48%] flex flex-col items-center">
                    <div className="w-5 h-5 rounded-full bg-accent animate-pulse opacity-60 absolute" />
                    <div className="w-5 h-5 rounded-full bg-accent flex items-center justify-center text-white text-[10px] font-bold shadow-lg shadow-accent/60">
                      ★
                    </div>
                    <span className="text-[10px] font-semibold text-text-primary mt-1">Core Self</span>
                  </div>

                  <div className="absolute top-[32%] left-[78%] flex flex-col items-center">
                    <div className="w-3 h-3 rounded-full bg-success shadow-md shadow-success/40" />
                    <span className="text-[9px] font-mono text-text-tertiary mt-1">user_pref</span>
                  </div>

                  <div className="absolute top-[72%] left-[33%] flex flex-col items-center">
                    <div className="w-3 h-3 rounded-full bg-warning shadow-md shadow-warning/40" />
                    <span className="text-[9px] font-mono text-text-tertiary mt-1">workflows</span>
                  </div>

                  <div className="absolute top-[67%] left-[68%] flex flex-col items-center">
                    <div className="w-3 h-3 rounded-full bg-accent shadow-md shadow-accent/40" />
                    <span className="text-[9px] font-mono text-text-tertiary mt-1">rag_docs</span>
                  </div>
                </div>
              </div>

              {/* Collaboration Domains */}
              <div className="p-5 rounded-2xl bg-bg-elevated border border-border-subtle space-y-3">
                <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                  Top Collaboration Domains
                </h3>
                <div className="space-y-2 text-xs">
                  {[
                    { domain: 'Code & Refactoring', pct: 45, color: 'bg-accent' },
                    { domain: 'Deep Research & Synthesis', pct: 25, color: 'bg-success' },
                    { domain: 'Automated Workflows', pct: 18, color: 'bg-warning' },
                    { domain: 'Spreadsheets & Finance', pct: 12, color: 'bg-text-secondary' },
                  ].map((item, idx) => (
                    <div key={idx} className="space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="text-text-primary">{item.domain}</span>
                        <span className="font-mono text-text-secondary">{item.pct}%</span>
                      </div>
                      <div className="h-1.5 w-full bg-bg-base rounded-full overflow-hidden">
                        <div className={`h-full ${item.color}`} style={{ width: `${item.pct}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Tab 2: Growth & Skills */}
          {activeTab === 'growth' && (
            <div className="space-y-4 animate-fade-in text-left">
              <div className="p-5 rounded-2xl bg-bg-elevated border border-border-subtle space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                    Specialist Skill Proficiencies
                  </h3>
                  <span className="text-xs text-accent font-medium">94.8% Overall Reliability</span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {[
                    { name: 'AST Deterministic Patch Repair', score: '98%', level: 'Master' },
                    { name: 'Exact L1 Semantic Cache Match', score: '99.4%', level: 'Master' },
                    { name: 'Observational Memory Scoring', score: '94%', level: 'Expert' },
                    { name: 'Multi-Agent Swarm Orchestration', score: '89%', level: 'Advanced' },
                    { name: 'Policy Interception & Guardrails', score: '100%', level: 'Zero-Trust' },
                    { name: 'Frontier CoT Distillation', score: '91%', level: 'Expert' },
                  ].map((s, idx) => (
                    <div
                      key={idx}
                      className="p-3 rounded-xl bg-bg-base border border-border-subtle flex items-center justify-between"
                    >
                      <div>
                        <div className="text-xs font-medium text-text-primary">{s.name}</div>
                        <div className="text-[10px] text-accent font-mono">{s.level}</div>
                      </div>
                      <span className="text-xs font-bold font-mono text-success">{s.score}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Milestones Unlocked */}
              <div className="p-5 rounded-2xl bg-bg-elevated border border-border-subtle space-y-3">
                <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider flex items-center gap-1.5">
                  <Award className="w-4 h-4 text-warning" />
                  <span>Milestones Unlocked</span>
                </h3>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
                  <div className="p-3 rounded-lg bg-bg-base border border-border-subtle flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4 text-success flex-shrink-0" />
                    <div>
                      <div className="font-medium text-text-primary">Zero Plaintext</div>
                      <div className="text-[10px] text-text-tertiary">Keyring credential vault</div>
                    </div>
                  </div>
                  <div className="p-3 rounded-lg bg-bg-base border border-border-subtle flex items-center gap-2">
                    <Zap className="w-4 h-4 text-warning flex-shrink-0" />
                    <div>
                      <div className="font-medium text-text-primary">90/9/1 Architect</div>
                      <div className="text-[10px] text-text-tertiary">&lt;10% frontier calls</div>
                    </div>
                  </div>
                  <div className="p-3 rounded-lg bg-bg-base border border-border-subtle flex items-center gap-2">
                    <Sparkles className="w-4 h-4 text-accent flex-shrink-0" />
                    <div>
                      <div className="font-medium text-text-primary">Local-First Soul</div>
                      <div className="text-[10px] text-text-tertiary">Chroma vector grounded</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Tab 3: Observational Memory Table */}
          {activeTab === 'memory' && (
            <div className="space-y-4 animate-fade-in text-left">
              <div className="p-5 rounded-2xl bg-bg-elevated border border-border-subtle space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                      Observational Memory Ledger
                    </h3>
                    <p className="text-[11px] text-text-secondary">
                      Atomic observations extracted by your agent. Searchable, verifiable, and editable.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsAddingMemory(!isAddingMemory)}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium transition-all shadow-sm self-start sm:self-auto"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Teach Observation</span>
                  </button>
                </div>

                {/* Add Observation Form */}
                {isAddingMemory && (
                  <div className="p-3.5 rounded-xl bg-bg-base border border-accent/30 space-y-2.5 animate-fade-in">
                    <div className="text-xs font-medium text-text-primary">Teach New Observation</div>
                    <textarea
                      value={newMemoryContent}
                      onChange={(e) => setNewMemoryContent(e.target.value)}
                      placeholder="Enter a preference, architectural convention, or project fact..."
                      rows={2}
                      className="w-full bg-bg-elevated border border-border-strong rounded-lg p-2.5 text-xs text-text-primary focus:outline-none focus:border-accent"
                    />
                    <div className="flex items-center justify-between">
                      <select
                        value={newMemoryCategory}
                        onChange={(e) => setNewMemoryCategory(e.target.value)}
                        className="bg-bg-elevated border border-border-strong text-xs text-text-secondary rounded-lg px-2.5 py-1"
                      >
                        <option value="preference">User Preference</option>
                        <option value="fact">Project Fact</option>
                        <option value="workflow">Workflow Habit</option>
                        <option value="rag_document">Document Grounding</option>
                      </select>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setIsAddingMemory(false)}
                          className="px-2.5 py-1 text-xs text-text-tertiary hover:text-text-primary"
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={handleCreateMemory}
                          className="px-3 py-1 bg-accent text-white rounded-md text-xs font-medium"
                        >
                          Save Memory
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Search & Category Filter Bar */}
                <div className="flex flex-col sm:flex-row items-center justify-between gap-2.5 pt-1">
                  <div className="relative w-full sm:w-64">
                    <Search className="w-3.5 h-3.5 text-text-tertiary absolute left-2.5 top-1/2 -translate-y-1/2" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search memory entries..."
                      className="w-full pl-8 pr-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
                    />
                  </div>

                  <div className="flex items-center gap-1 self-start sm:self-auto overflow-x-auto">
                    {['all', 'preference', 'fact', 'workflow', 'rag_document'].map((cat) => (
                      <button
                        key={cat}
                        onClick={() => setSelectedCategory(cat)}
                        className={`px-2.5 py-1 rounded-md text-[11px] capitalize transition-colors ${
                          selectedCategory === cat
                            ? 'bg-accent/15 text-accent font-medium'
                            : 'text-text-tertiary hover:text-text-secondary hover:bg-bg-base'
                        }`}
                      >
                        {cat.replace('_', ' ')}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Memory Table */}
                <div className="border border-border-subtle rounded-xl overflow-hidden bg-bg-base">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-border-subtle bg-bg-elevated/60 text-text-tertiary text-[10px] uppercase font-semibold">
                        <th className="py-2.5 px-3">Observation</th>
                        <th className="py-2.5 px-3">Category</th>
                        <th className="py-2.5 px-3">Importance</th>
                        <th className="py-2.5 px-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-subtle">
                      {filteredMemories.length === 0 ? (
                        <tr>
                          <td colSpan={4} className="py-6 text-center text-text-tertiary text-xs">
                            No observations match your search criteria.
                          </td>
                        </tr>
                      ) : (
                        filteredMemories.map((m) => {
                          const isEditing = editingMemoryId === m.id;
                          return (
                            <tr key={m.id} className="hover:bg-bg-elevated/40 transition-colors">
                              <td className="py-2.5 px-3 text-text-primary">
                                {isEditing ? (
                                  <input
                                    type="text"
                                    value={editContent}
                                    onChange={(e) => setEditContent(e.target.value)}
                                    className="w-full bg-bg-elevated border border-accent rounded px-2 py-1 text-xs text-text-primary"
                                  />
                                ) : (
                                  <span>{m.content}</span>
                                )}
                              </td>
                              <td className="py-2.5 px-3">
                                <span className="px-2 py-0.5 rounded-full bg-accent/10 text-accent font-mono text-[10px] capitalize">
                                  {m.category.replace('_', ' ')}
                                </span>
                              </td>
                              <td className="py-2.5 px-3">
                                <span className="font-mono text-xs font-semibold text-success">
                                  {(m.importance * 100).toFixed(0)}%
                                </span>
                              </td>
                              <td className="py-2.5 px-3 text-right">
                                {isEditing ? (
                                  <div className="flex items-center justify-end gap-1">
                                    <button
                                      type="button"
                                      onClick={() => handleSaveEdit(m.id)}
                                      className="p-1 text-success hover:bg-bg-hover rounded"
                                      title="Save"
                                    >
                                      <Check className="w-3.5 h-3.5" />
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => setEditingMemoryId(null)}
                                      className="p-1 text-text-tertiary hover:bg-bg-hover rounded"
                                      title="Cancel"
                                    >
                                      <X className="w-3.5 h-3.5" />
                                    </button>
                                  </div>
                                ) : (
                                  <div className="flex items-center justify-end gap-1">
                                    <button
                                      type="button"
                                      onClick={() => handleStartEdit(m)}
                                      className="p-1 text-text-tertiary hover:text-text-primary hover:bg-bg-hover rounded"
                                      title="Edit observation"
                                    >
                                      <Edit2 className="w-3.5 h-3.5" />
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => handleDeleteMemory(m.id)}
                                      className="p-1 text-text-tertiary hover:text-danger hover:bg-bg-hover rounded"
                                      title="Delete observation"
                                    >
                                      <Trash2 className="w-3.5 h-3.5" />
                                    </button>
                                  </div>
                                )}
                              </td>
                            </tr>
                          );
                        })
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* Tab 4: Cost Efficiency */}
          {activeTab === 'cost' && (
            <div className="space-y-4 animate-fade-in text-left">
              <div className="p-5 rounded-2xl bg-bg-elevated border border-border-subtle space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold text-text-primary uppercase tracking-wider">
                    90/9/1 Execution Tier Alignment
                  </h3>
                  <span className="text-xs font-mono text-success font-semibold">
                    1.2% Frontier Ratio (Compliant)
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs">
                  <div className="p-3 rounded-xl bg-bg-base border border-border-subtle">
                    <span className="text-[10px] text-text-tertiary font-mono">CODE TIER</span>
                    <div className="text-base font-bold text-text-primary mt-1">84.2%</div>
                    <span className="text-[10px] text-success">0 token AST execution</span>
                  </div>
                  <div className="p-3 rounded-xl bg-bg-base border border-border-subtle">
                    <span className="text-[10px] text-text-tertiary font-mono">CACHE TIER</span>
                    <div className="text-base font-bold text-text-primary mt-1">7.8%</div>
                    <span className="text-[10px] text-success">0 token semantic hit</span>
                  </div>
                  <div className="p-3 rounded-xl bg-bg-base border border-border-subtle">
                    <span className="text-[10px] text-text-tertiary font-mono">SMALL/MID</span>
                    <div className="text-base font-bold text-text-primary mt-1">6.8%</div>
                    <span className="text-[10px] text-text-tertiary">Fast local classification</span>
                  </div>
                  <div className="p-3 rounded-xl bg-bg-base border border-border-subtle">
                    <span className="text-[10px] text-text-tertiary font-mono">FRONTIER</span>
                    <div className="text-base font-bold text-accent mt-1">1.2%</div>
                    <span className="text-[10px] text-text-tertiary">Strict &lt;10% ceiling</span>
                  </div>
                </div>

                <div className="p-3.5 rounded-xl bg-bg-base border border-border-subtle flex items-center justify-between text-xs">
                  <div>
                    <span className="font-semibold text-text-primary">
                      Average Cost per Solved Task:
                    </span>
                    <span className="font-mono text-accent font-bold ml-2">$0.0003</span>
                  </div>
                  <div className="text-text-tertiary">
                    Versus $0.0350 cloud frontier baseline (
                    <span className="text-success font-semibold">116× cheaper</span>)
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Bottom Universal ChatInput for Direct Conversation with Agent */}
      <div className="border-t border-border-subtle bg-bg-base/95 backdrop-blur-md px-4 py-3">
        <div className="w-full max-w-[880px] mx-auto">
          <ChatInput
            mode="agent"
            model={activeModel}
            onSend={(_msg) => {
              // Direct instruction to agent
              onSelectMode('home');
            }}
            onModeChange={onSelectMode}
            onModelChange={onSelectModel}
            inputRef={inputRef}
            placeholder="Teach your agent a new observation or ask about its memory..."
          />
        </div>
      </div>
    </div>
  );
};
