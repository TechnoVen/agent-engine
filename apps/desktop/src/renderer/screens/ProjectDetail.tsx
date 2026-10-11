import React, { useState } from 'react';
import {
  ArrowLeft,
  Plus,
  MessageSquare,
  FileText,
  Shield,
  Bot,
  Coins,
  Search,
  Upload,
  Trash2,
  Save,
  CheckCircle2,
  Sparkles,
  FolderKanban,
  ChevronRight,
  Clock,
} from 'lucide-react';
import { Mode, ModelTier, Project, ProjectFile, ProjectThread } from '../types';

export interface ProjectDetailProps {
  project: Project;
  onBack: () => void;
  onUpdateProject: (updated: Project) => void;
  onSelectSession?: (sessionId: string) => void;
  onSelectMode: (mode: Mode) => void;
  activeModel?: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
}

export const ProjectDetail: React.FC<ProjectDetailProps> = ({
  project,
  onBack,
  onUpdateProject,
  onSelectSession,
  onSelectMode,
  activeModel = 'instant',
}) => {
  const [activeTab, setActiveTab] = useState<'instructions' | 'files' | 'agents' | 'policy' | 'cost'>('instructions');
  const [instructionsText, setInstructionsText] = useState(project.instructions || '');
  const [saveToast, setSaveToast] = useState(false);
  const [searchThreadQuery, setSearchThreadQuery] = useState('');
  const [threads, setThreads] = useState<ProjectThread[]>(project.threads || []);
  const [files, setFiles] = useState<ProjectFile[]>(project.files || []);
  const [activeAgents, setActiveAgents] = useState<string[]>(project.activeAgents || []);

  const [scopedPolicy, setScopedPolicy] = useState<string>(
    project.scopedPolicy || 'Strict Zero-Trust'
  );

  const [budgetCeiling, setBudgetCeiling] = useState<number>(project.budgetCeilingUsd || 15.0);

  const handleSaveInstructions = () => {
    const updated: Project = {
      ...project,
      instructions: instructionsText,
      files,
      threads,
      activeAgents,
      scopedPolicy,
      budgetCeilingUsd: budgetCeiling,
    };
    onUpdateProject(updated);
    setSaveToast(true);
    setTimeout(() => setSaveToast(false), 2000);
  };

  const handleCreateNewThread = () => {
    const newThreadId = `th-${project.id}-${Date.now().toString().slice(-4)}`;
    const newThread: ProjectThread = {
      id: newThreadId,
      title: `New Thread #${threads.length + 1}`,
      updatedAt: 'Just now',
      messageCount: 0,
      snippet: 'Started new conversation in project context.',
      status: 'active',
    };
    const nextThreads = [newThread, ...threads];
    setThreads(nextThreads);
    onUpdateProject({
      ...project,
      threadCount: nextThreads.length,
      threads: nextThreads,
    });
    if (onSelectSession) {
      onSelectSession(newThreadId);
    }
    onSelectMode('home');
  };

  const handleOpenThread = (th: ProjectThread) => {
    if (onSelectSession) {
      onSelectSession(th.id);
    }
    onSelectMode('home');
  };

  const handleAddSimulatedFile = () => {
    const newFile: ProjectFile = {
      id: `f-${Date.now()}`,
      name: `document-${files.length + 1}.md`,
      size: '18.4 KB',
      type: 'markdown',
      uploadedAt: 'Just now',
    };
    const nextFiles = [...files, newFile];
    setFiles(nextFiles);
    onUpdateProject({
      ...project,
      files: nextFiles,
    });
  };

  const handleDeleteFile = (fileId: string) => {
    const nextFiles = files.filter((f) => f.id !== fileId);
    setFiles(nextFiles);
    onUpdateProject({
      ...project,
      files: nextFiles,
    });
  };

  const handleToggleAgent = (agentName: string) => {
    const next = activeAgents.includes(agentName)
      ? activeAgents.filter((a) => a !== agentName)
      : [...activeAgents, agentName];
    setActiveAgents(next);
    onUpdateProject({
      ...project,
      activeAgents: next,
    });
  };

  const filteredThreads = threads.filter(
    (t) =>
      t.title.toLowerCase().includes(searchThreadQuery.toLowerCase()) ||
      (t.snippet && t.snippet.toLowerCase().includes(searchThreadQuery.toLowerCase()))
  );

  return (
    <div className="flex-1 flex flex-col h-full bg-bg-base overflow-hidden select-none">
      {/* Top Breadcrumb & Actions Bar */}
      <div className="h-14 border-b border-border-subtle bg-bg-elevated/40 backdrop-blur px-6 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-1.5 rounded-lg text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors flex items-center gap-1.5 text-xs font-medium"
            title="Back to All Projects"
            aria-label="Back to All Projects"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Projects</span>
          </button>
          <span className="text-text-tertiary">/</span>
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
              <FolderKanban className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-sm font-semibold text-text-primary">{project.name}</h1>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-bg-surface border border-border-subtle text-text-secondary">
                  {threads.length} threads
                </span>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                  {scopedPolicy}
                </span>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-accent/10 border border-accent/20 text-accent uppercase">
                  {activeModel}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleCreateNewThread}
            className="px-3 py-1.5 bg-accent hover:bg-accent/90 text-white rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 shadow-sm"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>New Thread</span>
          </button>
        </div>
      </div>

      {/* Main Split Body */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Side: Thread List & Project Feed */}
        <div className="flex-1 flex flex-col border-r border-border-subtle bg-bg-base overflow-hidden">
          {/* Thread Filter Bar */}
          <div className="p-4 border-b border-border-subtle bg-bg-surface/30 flex items-center justify-between gap-3">
            <div className="flex-1 relative">
              <Search className="w-3.5 h-3.5 text-text-tertiary absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchThreadQuery}
                onChange={(e) => setSearchThreadQuery(e.target.value)}
                placeholder="Search threads in this workspace..."
                className="w-full pl-9 pr-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
              />
            </div>
            <div className="text-[11px] text-text-tertiary">
              Showing {filteredThreads.length} of {threads.length}
            </div>
          </div>

          {/* Threads List */}
          <div className="flex-1 overflow-y-auto p-4 space-y-2.5">
            {filteredThreads.length === 0 ? (
              <div className="text-center py-16">
                <MessageSquare className="w-8 h-8 text-text-tertiary mx-auto mb-2 opacity-50" />
                <p className="text-xs text-text-secondary font-medium">No threads matching filter</p>
                <p className="text-[11px] text-text-tertiary mt-1">
                  Start a new conversation to scope context under this project.
                </p>
              </div>
            ) : (
              filteredThreads.map((th) => (
                <div
                  key={th.id}
                  onClick={() => handleOpenThread(th)}
                  className="group p-3.5 rounded-xl bg-bg-elevated hover:bg-bg-hover/80 border border-border-subtle hover:border-accent/40 transition-all cursor-pointer"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <div className="w-6 h-6 rounded-md bg-accent/10 border border-accent/20 flex items-center justify-center text-accent">
                        <MessageSquare className="w-3.5 h-3.5" />
                      </div>
                      <h3 className="text-xs font-semibold text-text-primary group-hover:text-accent transition-colors">
                        {th.title}
                      </h3>
                    </div>
                    <span className="text-[10px] text-text-tertiary flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {th.updatedAt}
                    </span>
                  </div>

                  {th.snippet && (
                    <p className="text-xs text-text-secondary mt-2 line-clamp-2 leading-relaxed">
                      {th.snippet}
                    </p>
                  )}

                  <div className="mt-3 flex items-center justify-between pt-2 border-t border-border-subtle/50 text-[11px]">
                    <span className="text-text-tertiary">
                      {th.messageCount} messages
                    </span>
                    <span className="text-accent group-hover:translate-x-0.5 transition-transform flex items-center gap-1 font-medium text-[11px]">
                      Open thread <ChevronRight className="w-3 h-3" />
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right Side: Inspector Panel */}
        <div className="w-96 flex flex-col bg-bg-elevated/20 shrink-0 overflow-hidden">
          {/* Inspector Tabs */}
          <div className="flex border-b border-border-subtle bg-bg-surface/50 p-1 gap-1">
            <button
              onClick={() => setActiveTab('instructions')}
              className={`flex-1 py-1.5 rounded-md text-[11px] font-medium transition-colors flex items-center justify-center gap-1 ${
                activeTab === 'instructions'
                  ? 'bg-bg-elevated text-accent shadow-sm border border-border-subtle'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <Sparkles className="w-3 h-3" />
              <span>Prompt</span>
            </button>
            <button
              onClick={() => setActiveTab('files')}
              className={`flex-1 py-1.5 rounded-md text-[11px] font-medium transition-colors flex items-center justify-center gap-1 ${
                activeTab === 'files'
                  ? 'bg-bg-elevated text-accent shadow-sm border border-border-subtle'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <FileText className="w-3 h-3" />
              <span>Files ({files.length})</span>
            </button>
            <button
              onClick={() => setActiveTab('agents')}
              className={`flex-1 py-1.5 rounded-md text-[11px] font-medium transition-colors flex items-center justify-center gap-1 ${
                activeTab === 'agents'
                  ? 'bg-bg-elevated text-accent shadow-sm border border-border-subtle'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <Bot className="w-3 h-3" />
              <span>Agents</span>
            </button>
            <button
              onClick={() => setActiveTab('policy')}
              className={`flex-1 py-1.5 rounded-md text-[11px] font-medium transition-colors flex items-center justify-center gap-1 ${
                activeTab === 'policy'
                  ? 'bg-bg-elevated text-accent shadow-sm border border-border-subtle'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <Shield className="w-3 h-3" />
              <span>Policy</span>
            </button>
            <button
              onClick={() => setActiveTab('cost')}
              className={`flex-1 py-1.5 rounded-md text-[11px] font-medium transition-colors flex items-center justify-center gap-1 ${
                activeTab === 'cost'
                  ? 'bg-bg-elevated text-accent shadow-sm border border-border-subtle'
                  : 'text-text-secondary hover:text-text-primary'
              }`}
            >
              <Coins className="w-3 h-3" />
              <span>Cost</span>
            </button>
          </div>

          {/* Inspector Content */}
          <div className="flex-1 overflow-y-auto p-4">
            {activeTab === 'instructions' && (
              <div className="space-y-4">
                <div>
                  <h4 className="text-xs font-semibold text-text-primary mb-1">
                    Persistent Project Instructions
                  </h4>
                  <p className="text-[11px] text-text-tertiary leading-relaxed mb-3">
                    These instructions are automatically injected into the system prompt prefix for every thread in this workspace.
                  </p>
                  <textarea
                    value={instructionsText}
                    onChange={(e) => setInstructionsText(e.target.value)}
                    rows={12}
                    placeholder="Enter permanent system instructions for this project (e.g. coding guidelines, domain rules, required architectural patterns)..."
                    className="w-full p-3 bg-bg-base border border-border-subtle rounded-lg text-xs font-mono text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent resize-none leading-relaxed"
                  />
                </div>

                <div className="flex items-center justify-between">
                  {saveToast ? (
                    <span className="text-xs text-emerald-400 flex items-center gap-1">
                      <CheckCircle2 className="w-3.5 h-3.5" /> Saved to project!
                    </span>
                  ) : (
                    <span className="text-[10px] text-text-tertiary">
                      Auto-scopes all future runs
                    </span>
                  )}
                  <button
                    onClick={handleSaveInstructions}
                    className="px-3 py-1.5 bg-accent hover:bg-accent/90 text-white rounded-lg text-xs font-medium flex items-center gap-1.5 shadow-sm transition-colors"
                  >
                    <Save className="w-3.5 h-3.5" />
                    <span>Save Instructions</span>
                  </button>
                </div>
              </div>
            )}

            {activeTab === 'files' && (
              <div className="space-y-3">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <h4 className="text-xs font-semibold text-text-primary">Attached Project Files</h4>
                    <p className="text-[11px] text-text-tertiary">Indexed into ChromaDB vector memory for this project.</p>
                  </div>
                  <button
                    onClick={handleAddSimulatedFile}
                    className="px-2.5 py-1 bg-bg-surface hover:bg-bg-hover border border-border-subtle text-text-primary rounded-lg text-xs font-medium flex items-center gap-1 transition-colors"
                  >
                    <Upload className="w-3 h-3" />
                    <span>Upload</span>
                  </button>
                </div>

                <div className="space-y-2">
                  {files.map((file) => (
                    <div
                      key={file.id}
                      className="p-2.5 rounded-lg bg-bg-surface border border-border-subtle flex items-center justify-between group"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <div className="w-6 h-6 rounded bg-accent/10 text-accent flex items-center justify-center shrink-0">
                          <FileText className="w-3.5 h-3.5" />
                        </div>
                        <div className="min-w-0">
                          <div className="text-xs font-medium text-text-primary truncate">{file.name}</div>
                          <div className="text-[10px] text-text-tertiary flex items-center gap-2">
                            <span>{file.size}</span>
                            <span>•</span>
                            <span>{file.uploadedAt}</span>
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={() => handleDeleteFile(file.id)}
                        className="text-text-tertiary hover:text-red-400 p-1 opacity-0 group-hover:opacity-100 transition-opacity"
                        title="Remove file"
                        aria-label="Remove file"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {activeTab === 'agents' && (
              <div className="space-y-3">
                <div>
                  <h4 className="text-xs font-semibold text-text-primary">Active Agent Adapters</h4>
                  <p className="text-[11px] text-text-tertiary mb-3">
                    Configure specialized agent personas and tool capabilities enabled for this project.
                  </p>
                </div>

                {['Senior Architect', 'Security Auditor', 'Code Specialist', 'Deep Researcher', 'Executive Drafter'].map(
                  (agent) => {
                    const isEnabled = activeAgents.includes(agent);
                    return (
                      <div
                        key={agent}
                        onClick={() => handleToggleAgent(agent)}
                        className="p-2.5 rounded-lg bg-bg-surface border border-border-subtle flex items-center justify-between cursor-pointer hover:bg-bg-hover transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <Bot className={`w-4 h-4 ${isEnabled ? 'text-accent' : 'text-text-tertiary'}`} />
                          <span className="text-xs font-medium text-text-primary">{agent}</span>
                        </div>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium ${
                            isEnabled
                              ? 'bg-accent/15 text-accent border border-accent/30'
                              : 'bg-bg-base text-text-tertiary border border-border-subtle'
                          }`}
                        >
                          {isEnabled ? 'ENABLED' : 'DISABLED'}
                        </span>
                      </div>
                    );
                  }
                )}
              </div>
            )}

            {activeTab === 'policy' && (
              <div className="space-y-4">
                <div>
                  <h4 className="text-xs font-semibold text-text-primary">Scoped Safety Policy</h4>
                  <p className="text-[11px] text-text-tertiary mb-3">
                    Safety rules applied strictly to all executions under this workspace.
                  </p>
                </div>

                <div className="space-y-2">
                  {[
                    {
                      name: 'Strict Zero-Trust',
                      desc: 'Requires inline operator approval on all shell, filesystem modifications, and SQL drops.',
                    },
                    {
                      name: 'Standard Developer Safeguard',
                      desc: 'Blocks destructive root commands and prompts only on critical external network mutations.',
                    },
                    {
                      name: 'Code Sandbox Restricted',
                      desc: 'Read-only repository access; all patches staged to AST review queue without auto-write.',
                    },
                  ].map((pol) => {
                    const isSelected = scopedPolicy === pol.name;
                    return (
                      <div
                        key={pol.name}
                        onClick={() => {
                          setScopedPolicy(pol.name);
                          onUpdateProject({ ...project, scopedPolicy: pol.name });
                        }}
                        className={`p-3 rounded-lg border cursor-pointer transition-all ${
                          isSelected
                            ? 'bg-accent/10 border-accent text-text-primary'
                            : 'bg-bg-surface border-border-subtle text-text-secondary hover:bg-bg-hover'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-semibold">{pol.name}</span>
                          {isSelected && <CheckCircle2 className="w-3.5 h-3.5 text-accent" />}
                        </div>
                        <p className="text-[11px] text-text-tertiary leading-relaxed">{pol.desc}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {activeTab === 'cost' && (
              <div className="space-y-4">
                <div>
                  <h4 className="text-xs font-semibold text-text-primary">Scoped Spend & 90/9/1 Compliance</h4>
                  <p className="text-[11px] text-text-tertiary mb-3">
                    Monthly token spend tracking and budget limits for this workspace.
                  </p>
                </div>

                <div className="p-3 rounded-lg bg-bg-surface border border-border-subtle space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-text-secondary">Current Monthly Spend</span>
                    <span className="font-mono font-semibold text-text-primary">
                      ${(project.monthlySpendUsd || 1.42).toFixed(2)}
                    </span>
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-text-secondary">Budget Ceiling ($)</span>
                    <input
                      type="number"
                      min="1"
                      step="5"
                      value={budgetCeiling}
                      onChange={(e) => {
                        const val = parseFloat(e.target.value) || 1;
                        setBudgetCeiling(val);
                        onUpdateProject({ ...project, budgetCeilingUsd: val });
                      }}
                      className="w-20 px-2 py-0.5 bg-bg-base border border-border-subtle rounded text-right font-mono font-semibold text-text-primary text-xs focus:outline-none focus:border-accent"
                    />
                  </div>
                  <div className="w-full bg-bg-base rounded-full h-1.5 overflow-hidden">
                    <div
                      className="bg-accent h-1.5 rounded-full"
                      style={{
                        width: `${Math.min(100, ((project.monthlySpendUsd || 1.42) / budgetCeiling) * 100)}%`,
                      }}
                    />
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-bg-surface border border-border-subtle space-y-2">
                  <div className="text-xs font-medium text-text-primary">90/9/1 Routing Compliance</div>
                  <div className="space-y-1.5 text-[11px]">
                    <div className="flex justify-between">
                      <span className="text-text-secondary">Local / Cache / Deterministic (90% target)</span>
                      <span className="font-mono text-emerald-400">92.4%</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-secondary">Mid-Tier Router (9% target)</span>
                      <span className="font-mono text-accent">6.8%</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-secondary">Frontier Reasoner (1% target)</span>
                      <span className="font-mono text-warning">0.8%</span>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
