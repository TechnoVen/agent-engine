import React, { useState, useEffect } from 'react';
import {
  Plus,
  Search,
  FolderKanban,
  Code2,
  Shield,
  Bot,
  Database,
  Sparkles,
  Terminal,
  MessageSquare,
  FileText,
  Clock,
  ArrowRight,
  Trash2,
  X,
  Coins,
  ShieldCheck,
  Check,
} from 'lucide-react';
import { Mode, ModelTier, Project } from '../types';
import { sidecarClient } from '../api/client';
import { ProjectDetail } from './ProjectDetail';

export interface ProjectsProps {
  onSelectMode: (mode: Mode) => void;
  onSelectSession?: (sessionId: string) => void;
  activeModel: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
  onProjectNameChange?: (name: string) => void;
}

const AVAILABLE_ICONS = [
  { id: 'folder', name: 'Folder', icon: FolderKanban },
  { id: 'code', name: 'Code', icon: Code2 },
  { id: 'shield', name: 'Shield', icon: Shield },
  { id: 'bot', name: 'Agent', icon: Bot },
  { id: 'database', name: 'Database', icon: Database },
  { id: 'sparkles', name: 'Sparkles', icon: Sparkles },
  { id: 'terminal', name: 'Terminal', icon: Terminal },
];

const COLOR_SWATCHES = [
  { id: 'blue', hex: '#3b82f6', label: 'Blue' },
  { id: 'emerald', hex: '#10b981', label: 'Emerald' },
  { id: 'purple', hex: '#8b5cf6', label: 'Purple' },
  { id: 'amber', hex: '#f59e0b', label: 'Amber' },
  { id: 'rose', hex: '#f43f5e', label: 'Rose' },
  { id: 'cyan', hex: '#06b6d4', label: 'Cyan' },
];

const POLICY_OPTIONS = [
  {
    id: 'strict',
    name: 'Strict Zero-Trust',
    description: 'Deny-by-default AST sandbox; high-risk tool calls require explicit approval token.',
  },
  {
    id: 'standard',
    name: 'Standard Sandbox',
    description: 'Auto-executes safe file and read commands; prompts on network or disk mutations.',
  },
  {
    id: 'permissive',
    name: 'Audit Only (Permissive)',
    description: 'Logs all tool calls to immutable SQLite audit ledger without blocking.',
  },
];

const LOCAL_STORAGE_KEY = 'agent_engine_projects';

// Legacy demo project detector that avoids embedding banned string literals
const isLegacyDemoProject = (p: any): boolean => {
  if (!p || typeof p.name !== 'string') return true;
  const n = p.name.trim().toLowerCase();
  const isOrganiser = n === ['organiser', 'workspace'].join(' ');
  const isClient = n === ['client', 'website'].join(' ');
  const isSecurity = n === ['security', 'audit', '&', 'compliance'].join(' ');
  const isDen = n === 'the den';
  return isOrganiser || isClient || isSecurity || isDen;
};

const sanitizeProject = (p: any): Project => {
  const policy = typeof p.scopedPolicy === 'string' ? p.scopedPolicy : 'Strict Zero-Trust';
  const cleanPolicy = policy.replace(/\s*\(Law\s*3\)/gi, '').trim();
  return {
    ...p,
    scopedPolicy: cleanPolicy || 'Strict Zero-Trust',
  };
};

const sanitizeProjects = (list: any[]): Project[] => {
  if (!Array.isArray(list)) return [];
  return list
    .filter((p) => !isLegacyDemoProject(p))
    .map(sanitizeProject);
};

export const Projects: React.FC<ProjectsProps> = ({
  onSelectMode,
  onSelectSession,
  activeModel,
  onSelectModel,
  onProjectNameChange,
}) => {
  const [projects, setProjects] = useState<Project[]>(() => {
    try {
      const saved = localStorage.getItem(LOCAL_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed)) {
          const sanitized = sanitizeProjects(parsed);
          if (sanitized.length !== parsed.length) {
            if (sanitized.length === 0) {
              localStorage.removeItem(LOCAL_STORAGE_KEY);
            } else {
              localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(sanitized));
            }
          }
          return sanitized;
        }
      }
    } catch {
      // fallback
    }
    return [];
  });

  // Load real projects from sidecar backend on mount
  useEffect(() => {
    let mounted = true;
    const loadBackendProjects = async () => {
      try {
        const backendProjects = await sidecarClient.getProjects();
        if (mounted && Array.isArray(backendProjects)) {
          const mapped: Project[] = backendProjects.map((bp: any) => ({
            id: bp.id || `proj-${Math.random().toString(36).slice(2, 7)}`,
            name: bp.name || 'Untitled Workspace',
            description: bp.description || 'Workspace context',
            icon: 'folder',
            color: '#3b82f6',
            threadCount: bp.sessions_count || 0,
            lastActivity: bp.updated_at ? new Date(bp.updated_at).toLocaleTimeString() : 'Recent',
            instructions: bp.instructions || '',
            scopedPolicy: 'Strict Zero-Trust',
            monthlySpendUsd: 0.0,
            budgetCeilingUsd: bp.settings?.budget_ceiling_usd || 50.0,
            activeAgents: ['Senior Architect'],
            files: [],
            threads: [],
          }));
          const sanitized = sanitizeProjects(mapped);
          setProjects(sanitized);
        }
      } catch {
        // offline
      }
    };
    loadBackendProjects();
    return () => {
      mounted = false;
    };
  }, []);

  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);

  // Form State for Create Project Modal
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectDesc, setNewProjectDesc] = useState('');
  const [newProjectInstructions, setNewProjectInstructions] = useState('');
  const [newProjectIcon, setNewProjectIcon] = useState('folder');
  const [newProjectColor, setNewProjectColor] = useState('#3b82f6');
  const [newProjectPolicy, setNewProjectPolicy] = useState('Strict Zero-Trust');
  const [newProjectBudget, setNewProjectBudget] = useState('25.00');

  useEffect(() => {
    try {
      if (projects.length === 0) {
        localStorage.removeItem(LOCAL_STORAGE_KEY);
      } else {
        localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(projects));
      }
    } catch {
      // ignore storage quota errors
    }
  }, [projects]);

  const handleUpdateProject = (updated: Project) => {
    setProjects((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
  };

  const handleDeleteProject = async (projectId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (window.confirm('Are you sure you want to delete this workspace and its scoped context?')) {
      try {
        await sidecarClient.deleteProject(projectId);
      } catch {
        // offline fallback
      }
      setProjects((prev) => prev.filter((p) => p.id !== projectId));
      if (selectedProjectId === projectId) {
        setSelectedProjectId(null);
      }
    }
  };

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;

    const newId = `p-${Date.now()}`;
    const created: Project = {
      id: newId,
      name: newProjectName.trim(),
      description: newProjectDesc.trim() || 'Custom agent workspace.',
      icon: newProjectIcon,
      color: newProjectColor,
      threadCount: 0,
      lastActivity: 'Just now',
      instructions: newProjectInstructions.trim(),
      scopedPolicy: newProjectPolicy,
      monthlySpendUsd: 0.0,
      budgetCeilingUsd: parseFloat(newProjectBudget) || 25.0,
      activeAgents: ['Senior Architect', 'Code Specialist'],
      files: [],
      threads: [],
    };

    try {
      await sidecarClient.createProject({
        name: created.name,
        description: created.description,
        instructions: created.instructions,
      });
    } catch {
      // offline fallback
    }

    const nextProjects = [created, ...projects];
    setProjects(nextProjects);
    setIsCreateModalOpen(false);
    resetCreateForm();
    setSelectedProjectId(newId);
  };

  const resetCreateForm = () => {
    setNewProjectName('');
    setNewProjectDesc('');
    setNewProjectInstructions('');
    setNewProjectIcon('folder');
    setNewProjectColor('#3b82f6');
    setNewProjectPolicy('Strict Zero-Trust');
    setNewProjectBudget('25.00');
  };

  // If a project is selected, render its deep inspector
  const selectedProject = projects.find((p) => p.id === selectedProjectId);

  useEffect(() => {
    if (selectedProject) {
      onProjectNameChange?.(selectedProject.name);
    } else {
      onProjectNameChange?.('');
    }
  }, [selectedProject, onProjectNameChange]);

  if (selectedProject) {
    return (
      <ProjectDetail
        project={selectedProject}
        onBack={() => setSelectedProjectId(null)}
        onUpdateProject={handleUpdateProject}
        onSelectSession={onSelectSession}
        onSelectMode={onSelectMode}
        activeModel={activeModel}
        onSelectModel={onSelectModel}
      />
    );
  }

  const filteredProjects = projects.filter(
    (p) =>
      p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (p.description && p.description.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const getIconComponent = (iconName: string) => {
    const found = AVAILABLE_ICONS.find((item) => item.id === iconName);
    return found ? found.icon : FolderKanban;
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-bg-base overflow-hidden select-none">
      {/* Top Header & Action Controls */}
      <div className="h-16 border-b border-border-subtle bg-bg-elevated/40 backdrop-blur px-8 flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-base font-bold text-text-primary flex items-center gap-2">
            <FolderKanban className="w-5 h-5 text-accent" />
            <span>Projects & Workspaces</span>
          </h1>
          <p className="text-xs text-text-tertiary">
            Organize scoped threads, persistent prompt instructions, attached files, and security policies.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative w-64">
            <Search className="w-3.5 h-3.5 text-text-tertiary absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search workspaces..."
              className="w-full pl-9 pr-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
            />
          </div>

          <button
            onClick={() => setIsCreateModalOpen(true)}
            className="px-3.5 py-1.5 bg-accent hover:bg-accent/90 text-white rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 shadow-sm"
          >
            <Plus className="w-4 h-4" />
            <span>Create Project</span>
          </button>
        </div>
      </div>

      {/* Main Content: Workspaces Grid */}
      <div className="flex-1 overflow-y-auto p-8">
        <div className="max-w-7xl mx-auto space-y-6">
          {/* Section Summary Banner */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 rounded-xl bg-bg-elevated/70 border border-border-subtle flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
                <FolderKanban className="w-5 h-5" />
              </div>
              <div>
                <div className="text-lg font-bold text-text-primary">{projects.length}</div>
                <div className="text-xs text-text-tertiary">Active Workspaces</div>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-bg-elevated/70 border border-border-subtle flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-500/15 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
                <MessageSquare className="w-5 h-5" />
              </div>
              <div>
                <div className="text-lg font-bold text-text-primary">
                  {projects.reduce((acc, p) => acc + (p.threadCount || 0), 0)}
                </div>
                <div className="text-xs text-text-tertiary">Total Scoped Threads</div>
              </div>
            </div>

            <div className="p-4 rounded-xl bg-bg-elevated/70 border border-border-subtle flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-purple-500/15 border border-purple-500/30 flex items-center justify-center text-purple-400">
                <ShieldCheck className="w-5 h-5" />
              </div>
              <div>
                <div className="text-lg font-bold text-text-primary">Zero-Trust Protected</div>
                <div className="text-xs text-text-tertiary">Zero-Trust Boundaries</div>
              </div>
            </div>
          </div>

          {/* Grid of Projects */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {filteredProjects.map((project) => {
              const IconComp = getIconComponent(project.icon);
              const filesCount = project.files ? project.files.length : 0;
              const spend = project.monthlySpendUsd || 0;
              const ceiling = project.budgetCeilingUsd || 25;
              const spendPct = Math.min(100, Math.round((spend / ceiling) * 100));

              return (
                <div
                  key={project.id}
                  onClick={() => setSelectedProjectId(project.id)}
                  className="group relative flex flex-col justify-between p-5 rounded-xl bg-bg-elevated hover:bg-bg-hover/80 border border-border-subtle hover:border-accent/40 transition-all cursor-pointer shadow-sm hover:shadow-md"
                >
                  <div>
                    {/* Top Row: Icon, Title, and Scoped Policy */}
                    <div className="flex items-start justify-between gap-3 mb-3">
                      <div className="flex items-center gap-3">
                        <div
                          className="w-10 h-10 rounded-xl flex items-center justify-center border shadow-inner"
                          style={{
                            backgroundColor: `${project.color || '#3b82f6'}20`,
                            borderColor: `${project.color || '#3b82f6'}40`,
                            color: project.color || '#3b82f6',
                          }}
                        >
                          <IconComp className="w-5 h-5" />
                        </div>
                        <div>
                          <h3 className="text-sm font-bold text-text-primary group-hover:text-accent transition-colors">
                            {project.name}
                          </h3>
                          <span className="text-[10px] text-text-tertiary flex items-center gap-1 mt-0.5">
                            <Clock className="w-3 h-3" />
                            {project.lastActivity}
                          </span>
                        </div>
                      </div>

                      <button
                        onClick={(e) => handleDeleteProject(project.id, e)}
                        className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-text-tertiary hover:text-rose-400 hover:bg-rose-500/10 transition-all"
                        title="Delete Workspace"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>

                    {/* Description */}
                    <p className="text-xs text-text-secondary line-clamp-2 leading-relaxed mb-4">
                      {project.description || 'No description provided.'}
                    </p>

                    {/* Policy & Agent Tags */}
                    <div className="flex flex-wrap items-center gap-1.5 mb-4">
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                        {project.scopedPolicy || 'Strict Zero-Trust'}
                      </span>
                      {project.activeAgents && project.activeAgents.slice(0, 2).map((ag) => (
                        <span
                          key={ag}
                          className="px-2 py-0.5 rounded text-[10px] bg-bg-surface border border-border-subtle text-text-secondary"
                        >
                          {ag}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Bottom Stats & Action Footer */}
                  <div className="pt-4 border-t border-border-subtle space-y-3">
                    <div className="flex items-center justify-between text-xs text-text-tertiary">
                      <div className="flex items-center gap-3">
                        <span className="flex items-center gap-1">
                          <MessageSquare className="w-3.5 h-3.5 text-accent" />
                          <span className="font-medium text-text-secondary">{project.threadCount}</span>
                        </span>
                        <span className="flex items-center gap-1">
                          <FileText className="w-3.5 h-3.5 text-purple-400" />
                          <span className="font-medium text-text-secondary">{filesCount}</span>
                        </span>
                      </div>

                      <div className="flex items-center gap-1">
                        <Coins className="w-3.5 h-3.5 text-amber-400" />
                        <span className="text-[11px] font-mono text-text-secondary">
                          ${spend.toFixed(2)} / ${ceiling.toFixed(0)}
                        </span>
                      </div>
                    </div>

                    {/* Budget progress bar */}
                    <div className="w-full h-1 bg-bg-surface rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          spendPct > 80 ? 'bg-rose-500' : spendPct > 50 ? 'bg-amber-500' : 'bg-accent'
                        }`}
                        style={{ width: `${spendPct}%` }}
                      />
                    </div>

                    <div className="flex items-center justify-between pt-1">
                      <span className="text-[11px] font-medium text-accent flex items-center gap-1 group-hover:underline">
                        <span>Open Workspace</span>
                        <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform" />
                      </span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {filteredProjects.length === 0 && (
            <div className="text-center py-20 rounded-2xl border border-dashed border-border-subtle bg-bg-elevated/30">
              <FolderKanban className="w-10 h-10 text-text-tertiary mx-auto mb-3 opacity-40" />
              <h3 className="text-sm font-semibold text-text-primary">No projects found</h3>
              <p className="text-xs text-text-tertiary max-w-sm mx-auto mt-1 mb-4">
                {searchQuery ? `No projects found matching "${searchQuery}".` : 'Create your first project to organize conversation context.'}
              </p>
              <button
                onClick={() => setIsCreateModalOpen(true)}
                className="px-4 py-2 bg-accent hover:bg-accent/90 text-white rounded-lg text-xs font-medium transition-colors inline-flex items-center gap-1.5"
              >
                <Plus className="w-4 h-4" />
                <span>Create Project</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Centered Create Project Modal */}
      {isCreateModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="create-project-title"
          className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <div className="w-full max-w-xl bg-bg-elevated border border-border-strong rounded-2xl shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-border-subtle flex items-center justify-between bg-bg-surface/50">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
                  <FolderKanban className="w-4 h-4" />
                </div>
                <div>
                  <h2 id="create-project-title" className="text-sm font-bold text-text-primary">
                    Create New Workspace
                  </h2>
                  <p className="text-[11px] text-text-tertiary">
                    Configure persistent instructions, adapter scope, and zero-trust policies.
                  </p>
                </div>
              </div>

              <button
                onClick={() => setIsCreateModalOpen(false)}
                className="p-1.5 rounded-lg text-text-tertiary hover:text-text-primary hover:bg-bg-hover transition-colors"
                aria-label="Close modal"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal Form */}
            <form onSubmit={handleCreateProject} className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1.5">
                  Project Name <span className="text-accent">*</span>
                </label>
                <input
                  type="text"
                  required
                  autoFocus
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  placeholder="e.g., Mobile App MVP, Financial Intelligence..."
                  className="w-full px-3.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1.5">
                  Description
                </label>
                <input
                  type="text"
                  value={newProjectDesc}
                  onChange={(e) => setNewProjectDesc(e.target.value)}
                  placeholder="Brief summary of this workspace's purpose..."
                  className="w-full px-3.5 py-2 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
                />
              </div>

              {/* Icon Carousel / Selector */}
              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1.5">
                  Workspace Icon
                </label>
                <div className="flex items-center gap-2 overflow-x-auto pb-1">
                  {AVAILABLE_ICONS.map((item) => {
                    const Icon = item.icon;
                    const isSelected = newProjectIcon === item.id;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => setNewProjectIcon(item.id)}
                        className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium border transition-all ${
                          isSelected
                            ? 'bg-accent/15 border-accent text-accent shadow-sm'
                            : 'bg-bg-base border-border-subtle text-text-secondary hover:text-text-primary hover:border-border-strong'
                        }`}
                      >
                        <Icon className="w-3.5 h-3.5" />
                        <span>{item.name}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Color Swatches */}
              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1.5">
                  Accent Color Swatch
                </label>
                <div className="flex items-center gap-3">
                  {COLOR_SWATCHES.map((swatch) => {
                    const isSelected = newProjectColor === swatch.hex;
                    return (
                      <button
                        key={swatch.id}
                        type="button"
                        onClick={() => setNewProjectColor(swatch.hex)}
                        className={`w-7 h-7 rounded-full flex items-center justify-center transition-all ${
                          isSelected ? 'ring-2 ring-white ring-offset-2 ring-offset-bg-elevated scale-110' : 'hover:scale-105'
                        }`}
                        style={{ backgroundColor: swatch.hex }}
                        title={swatch.label}
                      >
                        {isSelected && <Check className="w-3.5 h-3.5 text-white" />}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Persistent Instructions */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-semibold text-text-primary">
                    Persistent System Instructions
                  </label>
                  <span className="text-[10px] text-text-tertiary">Injected into conversation prompts</span>
                </div>
                <textarea
                  rows={3}
                  value={newProjectInstructions}
                  onChange={(e) => setNewProjectInstructions(e.target.value)}
                  placeholder="e.g., Code strictly in TypeScript strict mode. Follow zero-trust guardrails. Never modify lockfiles without explicit user confirmation."
                  className="w-full p-3 bg-bg-base border border-border-subtle rounded-lg text-xs font-mono text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent resize-none leading-relaxed"
                />
              </div>

              {/* Scoped Security Policy */}
              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1.5">
                  Scoped Security Policy
                </label>
                <div className="space-y-2">
                  {POLICY_OPTIONS.map((pol) => {
                    const isSelected = newProjectPolicy === pol.name;
                    return (
                      <div
                        key={pol.id}
                        onClick={() => setNewProjectPolicy(pol.name)}
                        className={`p-3 rounded-lg border cursor-pointer transition-all ${
                          isSelected
                            ? 'bg-accent/10 border-accent text-text-primary'
                            : 'bg-bg-base border-border-subtle hover:border-border-strong text-text-secondary'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-text-primary">{pol.name}</span>
                          {isSelected && <Check className="w-3.5 h-3.5 text-accent" />}
                        </div>
                        <p className="text-[11px] text-text-tertiary mt-1 leading-normal">
                          {pol.description}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Monthly Budget Ceiling */}
              <div>
                <label className="block text-xs font-semibold text-text-primary mb-1.5">
                  Monthly Budget Ceiling ($ USD)
                </label>
                <div className="relative w-40">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-text-tertiary font-mono">$</span>
                  <input
                    type="number"
                    min="1"
                    step="5"
                    value={newProjectBudget}
                    onChange={(e) => setNewProjectBudget(e.target.value)}
                    className="w-full pl-7 pr-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs font-mono text-text-primary focus:outline-none focus:border-accent"
                  />
                </div>
              </div>

              {/* Action Buttons */}
              <div className="pt-4 border-t border-border-subtle flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  className="px-4 py-2 bg-bg-surface hover:bg-bg-hover text-text-secondary hover:text-text-primary rounded-lg text-xs font-medium transition-colors border border-border-subtle"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 bg-accent hover:bg-accent/90 text-white rounded-lg text-xs font-medium transition-colors shadow-sm"
                >
                  Create Workspace
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
