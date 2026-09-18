import React, { useState, useEffect, useCallback } from 'react';
import {
  Puzzle,
  Search,
  Plus,
  RefreshCw,
  FolderPlus,
  Download,
  Trash2,
  CheckCircle2,
  AlertCircle,
  ShieldCheck,
  Save,
  Globe,
  X,
  Loader2,
} from 'lucide-react';
import { Mode, ModelTier, SkillDetailed, SkillRegistryPackage, SkillCollectionItem } from '../types';
import { sidecarClient } from '../api/client';

export interface SkillsScreenProps {
  onSelectMode: (mode: Mode) => void;
  activeModel?: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
}

export type SkillTab = 'installed' | 'registry' | 'collections';

const TOOL_FILTERS = [
  { id: 'all', label: 'All Tools' },
  { id: 'agent-engine', label: 'Agent Engine' },
  { id: 'claude-code', label: 'Claude Code' },
  { id: 'cursor', label: 'Cursor' },
  { id: 'codex', label: 'Codex' },
  { id: 'goose', label: 'Goose' },
];

export const Skills: React.FC<SkillsScreenProps> = () => {
  // Tabs & Search
  const [activeTab, setActiveTab] = useState<SkillTab>('installed');
  const [selectedTool, setSelectedTool] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTag, setSelectedTag] = useState<string | null>(null);

  // Data
  const [skills, setSkills] = useState<SkillDetailed[]>([]);
  const [registryPackages, setRegistryPackages] = useState<SkillRegistryPackage[]>([]);
  const [collections, setCollections] = useState<SkillCollectionItem[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<SkillDetailed | null>(null);
  const [selectedCollection, setSelectedCollection] = useState<SkillCollectionItem | null>(null);

  // Editor State
  const [editorContent, setEditorContent] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    errors: string[];
    warnings: string[];
  } | null>(null);

  // Modals & Remote Discovery
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showRemoteModal, setShowRemoteModal] = useState(false);
  const [showCreateCollModal, setShowCreateCollModal] = useState(false);
  const [remoteEndpoint, setRemoteEndpoint] = useState('https://');
  const [remoteToken, setRemoteToken] = useState('');
  const [remoteDiscovered, setRemoteDiscovered] = useState<SkillDetailed[]>([]);
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [remoteError, setRemoteError] = useState<string | null>(null);

  // New Skill Form
  const [newSkillName, setNewSkillName] = useState('');
  const [newSkillDesc, setNewSkillDesc] = useState('');
  const [newSkillTool, setNewSkillTool] = useState('agent-engine');
  const [newSkillContent, setNewSkillContent] = useState(
    '---\nname: My Custom Skill\ndescription: A useful workflow skill\nversion: 1.0.0\ntags: [custom]\n---\n\n# Instructions\nDescribe skill actions here.\n'
  );

  // New Collection Form
  const [newCollName, setNewCollName] = useState('');
  const [newCollDesc, setNewCollDesc] = useState('');
  const [newCollTags, setNewCollTags] = useState('automation, engineering');

  // Loading & Messages
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Fetch installed skills
  const loadSkills = useCallback(async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const toolParam = selectedTool === 'all' ? undefined : selectedTool;
      const data = await sidecarClient.getSkillsDetailed(searchQuery || undefined, toolParam, selectedTag || undefined);
      setSkills(data);
      if (data.length > 0 && !selectedSkill) {
        // Load details for first skill
        const first = await sidecarClient.getSkillContent(data[0].id);
        setSelectedSkill(first || data[0]);
        setEditorContent(first?.content || '');
      }
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to load skills');
    } finally {
      setIsLoading(false);
    }
  }, [selectedTool, searchQuery, selectedTag, selectedSkill]);

  // Fetch registry packages
  const loadRegistry = useCallback(async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const data = await sidecarClient.getSkillRegistryPackages(searchQuery || undefined);
      setRegistryPackages(data);
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to load registry packages');
    } finally {
      setIsLoading(false);
    }
  }, [searchQuery]);

  // Fetch collections
  const loadCollections = useCallback(async () => {
    setIsLoading(true);
    setErrorMsg(null);
    try {
      const data = await sidecarClient.getSkillCollections();
      setCollections(data);
      if (data.length > 0 && !selectedCollection) {
        setSelectedCollection(data[0]);
      }
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to load collections');
    } finally {
      setIsLoading(false);
    }
  }, [selectedCollection]);

  // Trigger loads on tab change
  useEffect(() => {
    if (activeTab === 'installed') {
      loadSkills();
    } else if (activeTab === 'registry') {
      loadRegistry();
    } else if (activeTab === 'collections') {
      loadCollections();
    }
  }, [activeTab, loadSkills, loadRegistry, loadCollections]);

  // Select skill and fetch full content
  const handleSelectSkill = async (skill: SkillDetailed) => {
    setSelectedSkill(skill);
    try {
      const full = await sidecarClient.getSkillContent(skill.id);
      if (full) {
        setSelectedSkill(full);
        setEditorContent(full.content || '');
        validateContent(full.content || '');
      }
    } catch {
      setEditorContent(skill.content || '');
    }
  };

  // Live validator for editor content
  const validateContent = async (content: string) => {
    const res = await sidecarClient.validateSkillContent(content);
    setValidationResult(res);
  };

  // Save skill changes
  const handleSaveSkill = async () => {
    if (!selectedSkill || selectedSkill.is_readonly) return;
    setIsSaving(true);
    setSaveSuccess(false);
    try {
      const updated = await sidecarClient.updateSkillContent(selectedSkill.id, editorContent);
      setSelectedSkill(updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
      loadSkills();
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to update skill');
    } finally {
      setIsSaving(false);
    }
  };

  // Install from registry
  const handleInstallPackage = async (packageId: string) => {
    try {
      await sidecarClient.installRegistryPackage(packageId);
      loadRegistry();
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to install package');
    }
  };

  // Uninstall from registry
  const handleUninstallPackage = async (packageId: string) => {
    try {
      await sidecarClient.uninstallRegistryPackage(packageId);
      loadRegistry();
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to uninstall package');
    }
  };

  // Discover Remote
  const handleDiscoverRemote = async () => {
    if (!remoteEndpoint) return;
    setIsDiscovering(true);
    setRemoteError(null);
    try {
      const results = await sidecarClient.discoverRemoteSkills(remoteEndpoint, remoteToken || undefined);
      setRemoteDiscovered(results);
    } catch (e: any) {
      setRemoteError(e.message || 'Remote discovery failed');
    } finally {
      setIsDiscovering(false);
    }
  };

  // Import Remote Skill
  const handleImportRemoteSkill = async (skillId: string) => {
    try {
      await sidecarClient.importRemoteSkill(remoteEndpoint, skillId, 'agent-engine', remoteToken || undefined);
      setShowRemoteModal(false);
      loadSkills();
    } catch (e: any) {
      setRemoteError(e.message || 'Remote import failed');
    }
  };

  // Create Skill
  const handleCreateSkillSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSkillName.trim()) return;
    try {
      await sidecarClient.createSkill({
        name: newSkillName.trim(),
        description: newSkillDesc.trim(),
        content: newSkillContent,
        source_tool: newSkillTool,
      });
      setShowCreateModal(false);
      setNewSkillName('');
      setNewSkillDesc('');
      loadSkills();
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to create skill');
    }
  };

  // Create Collection
  const handleCreateCollectionSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newCollName.trim()) return;
    try {
      const tags = newCollTags.split(',').map((t) => t.trim()).filter(Boolean);
      await sidecarClient.createSkillCollection({
        name: newCollName.trim(),
        description: newCollDesc.trim(),
        tags,
      });
      setShowCreateCollModal(false);
      setNewCollName('');
      setNewCollDesc('');
      loadCollections();
    } catch (err: any) {
      setErrorMsg(err.message || 'Failed to create collection');
    }
  };

  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary overflow-hidden select-none">
      {/* Top Header Bar */}
      <div className="h-14 border-b border-border-subtle px-6 flex items-center justify-between shrink-0 bg-bg-elevated/40 backdrop-blur">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
            <Puzzle className="w-4 h-4" />
          </div>
          <div>
            <h1 className="text-base font-semibold leading-none">Skills Library</h1>
            <p className="text-xs text-text-secondary mt-0.5">
              Multi-tool discovery, local editor, community registry & collections
            </p>
          </div>
        </div>

        {/* Top Tabs */}
        <div className="flex items-center gap-1 bg-bg-base p-1 rounded-lg border border-border-subtle">
          <button
            onClick={() => setActiveTab('installed')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'installed'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            Installed ({skills.length})
          </button>
          <button
            onClick={() => setActiveTab('registry')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'registry'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            Registry
          </button>
          <button
            onClick={() => setActiveTab('collections')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
              activeTab === 'collections'
                ? 'bg-accent text-white shadow-sm'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            Collections ({collections.length})
          </button>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-2">
          {activeTab === 'installed' && (
            <>
              <button
                onClick={() => setShowRemoteModal(true)}
                className="px-3 py-1.5 bg-bg-elevated hover:bg-bg-hover border border-border-subtle rounded-lg text-xs font-medium text-text-primary transition-all flex items-center gap-1.5"
              >
                <Globe className="w-3.5 h-3.5 text-accent" />
                <span>Remote Discovery</span>
              </button>
              <button
                onClick={() => setShowCreateModal(true)}
                className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 shadow-sm"
              >
                <Plus className="w-3.5 h-3.5" />
                <span>New Skill</span>
              </button>
            </>
          )}

          {activeTab === 'collections' && (
            <button
              onClick={() => setShowCreateCollModal(true)}
              className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 shadow-sm"
            >
              <FolderPlus className="w-3.5 h-3.5" />
              <span>New Collection</span>
            </button>
          )}

          <button
            onClick={() => {
              if (activeTab === 'installed') loadSkills();
              else if (activeTab === 'registry') loadRegistry();
              else loadCollections();
            }}
            title="Refresh"
            className="p-1.5 text-text-secondary hover:text-text-primary rounded-lg border border-border-subtle hover:bg-bg-hover transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Error alert */}
      {errorMsg && (
        <div className="bg-destructive/10 border-b border-destructive/20 px-6 py-2 flex items-center justify-between text-destructive text-xs">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
          <button onClick={() => setErrorMsg(null)} className="p-1 hover:bg-destructive/20 rounded">
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Filter & Search Sidebar */}
        <div className="w-64 border-r border-border-subtle bg-bg-elevated/30 flex flex-col shrink-0">
          {/* Search Box */}
          <div className="p-3 border-b border-border-subtle">
            <div className="relative">
              <Search className="w-3.5 h-3.5 text-text-tertiary absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search skills, tags, prompt..."
                className="w-full bg-bg-base border border-border-subtle rounded-md pl-8 pr-3 py-1.5 text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-text-tertiary hover:text-text-primary"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>

          {/* Tool Sources List */}
          {activeTab === 'installed' && (
            <div className="p-3 space-y-1 border-b border-border-subtle">
              <div className="text-[10px] font-semibold text-text-tertiary uppercase tracking-wider px-2 mb-2">
                Tool Sources
              </div>
              {TOOL_FILTERS.map((f) => {
                const isActive = selectedTool === f.id;
                return (
                  <button
                    key={f.id}
                    onClick={() => setSelectedTool(f.id)}
                    className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-md text-xs transition-colors ${
                      isActive
                        ? 'bg-accent/15 text-accent font-medium'
                        : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover'
                    }`}
                  >
                    <span>{f.label}</span>
                    {f.id === 'all' ? (
                      <span className="text-[10px] text-text-tertiary">{skills.length}</span>
                    ) : (
                      <span className="text-[10px] text-text-tertiary">
                        {skills.filter((s) => s.source_tool === f.id).length}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          {/* Tag Quick Filters */}
          <div className="p-3 flex-1 overflow-y-auto">
            <div className="text-[10px] font-semibold text-text-tertiary uppercase tracking-wider px-2 mb-2 flex items-center justify-between">
              <span>Tags</span>
              {selectedTag && (
                <button
                  onClick={() => setSelectedTag(null)}
                  className="text-accent hover:underline lowercase font-normal"
                >
                  clear
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-1 px-2">
              {Array.from(new Set(skills.flatMap((s) => s.tags || [])))
                .slice(0, 15)
                .map((t) => (
                  <button
                    key={t}
                    onClick={() => setSelectedTag(selectedTag === t ? null : t)}
                    className={`px-2 py-0.5 text-[10px] rounded-full transition-colors ${
                      selectedTag === t
                        ? 'bg-accent text-white'
                        : 'bg-bg-base border border-border-subtle text-text-secondary hover:border-accent/40'
                    }`}
                  >
                    #{t}
                  </button>
                ))}
            </div>
          </div>
        </div>

        {/* Central View & Detail Editor depending on active tab */}
        {activeTab === 'installed' && (
          <div className="flex-1 flex overflow-hidden">
            {/* Skill Cards Grid / List */}
            <div className="w-[380px] border-r border-border-subtle flex flex-col bg-bg-base shrink-0 overflow-y-auto">
              <div className="p-3 text-xs text-text-tertiary border-b border-border-subtle flex items-center justify-between">
                <span>{skills.length} Skills Discovered</span>
                <span className="text-[10px]">ADR-013 Local First</span>
              </div>
              <div className="divide-y divide-border-subtle">
                {skills.map((skill) => {
                  const isSelected = selectedSkill?.id === skill.id;
                  return (
                    <div
                      key={skill.id}
                      onClick={() => handleSelectSkill(skill)}
                      className={`p-3.5 cursor-pointer transition-all ${
                        isSelected
                          ? 'bg-accent/10 border-l-4 border-accent'
                          : 'hover:bg-bg-hover'
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-1.5 truncate">
                          <span className="text-xs font-medium text-text-primary truncate">
                            {skill.name}
                          </span>
                        </div>
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-bg-elevated border border-border-subtle text-text-secondary uppercase">
                          {skill.source_tool}
                        </span>
                      </div>
                      <p className="text-[11px] text-text-secondary line-clamp-2 mt-1 leading-relaxed">
                        {skill.description || 'No description provided.'}
                      </p>
                      <div className="flex items-center gap-2 mt-2 text-[10px] text-text-tertiary">
                        <span>v{skill.version || '1.0.0'}</span>
                        <span>•</span>
                        <span>{skill.category || 'General'}</span>
                        {skill.is_readonly && (
                          <>
                            <span>•</span>
                            <span className="text-amber-500 font-medium">Built-in</span>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Right Editor & Inspector Panel */}
            <div className="flex-1 flex flex-col bg-bg-elevated/20 overflow-hidden">
              {selectedSkill ? (
                <>
                  {/* Skill Metadata Banner */}
                  <div className="p-4 border-b border-border-subtle bg-bg-elevated/50 flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <h2 className="text-sm font-semibold text-text-primary">
                          {selectedSkill.name}
                        </h2>
                        <span className="px-2 py-0.5 text-[10px] rounded bg-bg-base border border-border-subtle font-mono text-text-tertiary">
                          {selectedSkill.id}
                        </span>
                        {selectedSkill.is_readonly ? (
                          <span className="px-2 py-0.5 text-[10px] rounded bg-amber-500/15 border border-amber-500/30 text-amber-500 font-medium">
                            Read-Only Template
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 text-[10px] rounded bg-emerald-500/15 border border-emerald-500/30 text-emerald-500 font-medium">
                            Editable
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-text-secondary mt-0.5">
                        {selectedSkill.description}
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      {saveSuccess && (
                        <div className="flex items-center gap-1 text-emerald-500 text-xs mr-2">
                          <CheckCircle2 className="w-3.5 h-3.5" />
                          <span>Saved!</span>
                        </div>
                      )}
                      <button
                        onClick={handleSaveSkill}
                        disabled={selectedSkill.is_readonly || isSaving}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 ${
                          selectedSkill.is_readonly
                            ? 'bg-bg-base text-text-tertiary cursor-not-allowed border border-border-subtle'
                            : 'bg-accent hover:bg-accent-hover text-white shadow-sm'
                        }`}
                      >
                        <Save className="w-3.5 h-3.5" />
                        <span>{isSaving ? 'Saving...' : 'Save Changes'}</span>
                      </button>
                    </div>
                  </div>

                  {/* Validation Alerts Bar */}
                  {validationResult && (
                    <div className="px-4 py-1.5 bg-bg-base border-b border-border-subtle flex items-center justify-between text-[11px]">
                      <div className="flex items-center gap-2">
                        {validationResult.valid ? (
                          <span className="flex items-center gap-1 text-emerald-500">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            <span>Frontmatter schema valid</span>
                          </span>
                        ) : (
                          <span className="flex items-center gap-1 text-destructive">
                            <AlertCircle className="w-3.5 h-3.5" />
                            <span>{validationResult.errors.join('; ')}</span>
                          </span>
                        )}
                      </div>
                      <span className="text-text-tertiary font-mono text-[10px]">
                        Target: {selectedSkill.path || 'Local file'}
                      </span>
                    </div>
                  )}

                  {/* Editor Canvas */}
                  <div className="flex-1 p-4 overflow-hidden flex flex-col">
                    <textarea
                      value={editorContent}
                      readOnly={selectedSkill.is_readonly}
                      onChange={(e) => {
                        setEditorContent(e.target.value);
                        validateContent(e.target.value);
                      }}
                      className="w-full flex-1 bg-bg-base border border-border-subtle rounded-lg p-4 font-mono text-xs text-text-primary leading-relaxed resize-none focus:outline-none focus:border-accent selection:bg-accent/20"
                      spellCheck={false}
                    />
                  </div>
                </>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
                  <Puzzle className="w-10 h-10 text-text-tertiary mb-3 opacity-40" />
                  <h3 className="text-sm font-medium text-text-secondary">No skill selected</h3>
                  <p className="text-xs text-text-tertiary max-w-sm mt-1">
                    Select a skill from the list to preview its YAML frontmatter, execution instructions, and edit content.
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Registry Tab View */}
        {activeTab === 'registry' && (
          <div className="flex-1 p-6 overflow-y-auto bg-bg-base">
            <div className="max-w-5xl mx-auto space-y-6">
              <div>
                <h2 className="text-base font-semibold text-text-primary">Curated Skill Registry</h2>
                <p className="text-xs text-text-secondary mt-0.5">
                  Verified community and core packages. SHA-256 verified, security scanned, installed in &lt;10s.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {registryPackages.map((pkg) => (
                  <div
                    key={pkg.id}
                    className="p-4 bg-bg-elevated border border-border-subtle rounded-xl flex flex-col justify-between hover:border-border-strong transition-all shadow-sm"
                  >
                    <div>
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-text-primary">{pkg.name}</span>
                          {pkg.verified && (
                            <span className="flex items-center gap-1 text-[10px] text-emerald-500 font-medium px-1.5 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20">
                              <ShieldCheck className="w-3 h-3" />
                              <span>Verified</span>
                            </span>
                          )}
                        </div>
                        <span className="text-[10px] text-text-tertiary font-mono">v{pkg.version}</span>
                      </div>

                      <p className="text-xs text-text-secondary mt-2 leading-relaxed">
                        {pkg.description}
                      </p>

                      <div className="flex flex-wrap gap-1.5 mt-3">
                        {pkg.tags.map((t) => (
                          <span
                            key={t}
                            className="px-2 py-0.5 text-[10px] rounded-md bg-bg-base border border-border-subtle text-text-tertiary"
                          >
                            #{t}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="mt-4 pt-3 border-t border-border-subtle flex items-center justify-between">
                      <div className="text-[10px] text-text-tertiary">
                        <span>By {pkg.author}</span>
                        <span className="mx-1">•</span>
                        <span>{pkg.installs} installs</span>
                      </div>

                      {pkg.is_installed ? (
                        <div className="flex items-center gap-2">
                          <span className="text-[11px] text-emerald-500 font-medium flex items-center gap-1">
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            <span>Installed</span>
                          </span>
                          <button
                            onClick={() => handleUninstallPackage(pkg.id)}
                            className="px-2.5 py-1 text-xs text-destructive hover:bg-destructive/10 rounded-md transition-colors"
                          >
                            Uninstall
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => handleInstallPackage(pkg.id)}
                          className="px-3 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 shadow-sm"
                        >
                          <Download className="w-3.5 h-3.5" />
                          <span>Install</span>
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Collections Tab View */}
        {activeTab === 'collections' && (
          <div className="flex-1 flex overflow-hidden">
            {/* Collections List */}
            <div className="w-72 border-r border-border-subtle bg-bg-base overflow-y-auto p-3 space-y-2 shrink-0">
              <div className="text-[10px] font-semibold text-text-tertiary uppercase tracking-wider px-2 mb-2">
                Curated Collections
              </div>
              {collections.map((c) => {
                const isSelected = selectedCollection?.id === c.id;
                return (
                  <div
                    key={c.id}
                    onClick={() => setSelectedCollection(c)}
                    className={`p-3 rounded-lg cursor-pointer transition-all ${
                      isSelected
                        ? 'bg-accent/15 border-l-4 border-accent'
                        : 'hover:bg-bg-hover border border-border-subtle'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-text-primary">{c.name}</span>
                      <span className="text-[10px] text-text-tertiary font-mono">
                        {c.skill_ids.length} skills
                      </span>
                    </div>
                    <p className="text-[11px] text-text-secondary line-clamp-2 mt-1">
                      {c.description || 'Collection of related skills.'}
                    </p>
                  </div>
                );
              })}
            </div>

            {/* Collection Details */}
            <div className="flex-1 p-6 overflow-y-auto bg-bg-elevated/20">
              {selectedCollection ? (
                <div className="max-w-3xl space-y-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <h2 className="text-base font-semibold text-text-primary">
                        {selectedCollection.name}
                      </h2>
                      <p className="text-xs text-text-secondary mt-0.5">
                        {selectedCollection.description}
                      </p>
                    </div>
                    <button
                      onClick={async () => {
                        await sidecarClient.deleteSkillCollection(selectedCollection.id);
                        setSelectedCollection(null);
                        loadCollections();
                      }}
                      className="px-2.5 py-1.5 text-destructive hover:bg-destructive/10 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 border border-destructive/20"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>Delete Collection</span>
                    </button>
                  </div>

                  <div className="border border-border-subtle rounded-xl bg-bg-base overflow-hidden">
                    <div className="p-3 bg-bg-elevated border-b border-border-subtle text-xs font-medium text-text-primary">
                      Member Skills ({selectedCollection.skill_ids.length})
                    </div>
                    <div className="divide-y divide-border-subtle">
                      {selectedCollection.skill_ids.map((id) => (
                        <div key={id} className="p-3 flex items-center justify-between text-xs">
                          <div className="flex items-center gap-2">
                            <Puzzle className="w-4 h-4 text-accent" />
                            <span className="font-mono text-text-primary">{id}</span>
                          </div>
                          <button
                            onClick={async () => {
                              await sidecarClient.removeSkillFromCollection(selectedCollection.id, id);
                              loadCollections();
                            }}
                            className="text-text-tertiary hover:text-destructive p-1 rounded transition-colors"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      ))}
                      {selectedCollection.skill_ids.length === 0 && (
                        <div className="p-6 text-center text-xs text-text-tertiary">
                          No skills in this collection yet.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
                  <FolderPlus className="w-10 h-10 text-text-tertiary mb-3 opacity-40" />
                  <h3 className="text-sm font-medium text-text-secondary">No collection selected</h3>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Remote Discovery Modal */}
      {showRemoteModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="w-full max-w-xl bg-bg-elevated border border-border-strong rounded-xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-border-subtle pb-3">
              <div className="flex items-center gap-2">
                <Globe className="w-4 h-4 text-accent" />
                <h3 className="text-sm font-semibold text-text-primary">Remote Skill Discovery</h3>
              </div>
              <button onClick={() => setShowRemoteModal(false)} className="text-text-tertiary hover:text-text-primary">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-text-secondary block mb-1">
                  Remote Host Endpoint (HTTP/HTTPS or SSH)
                </label>
                <input
                  type="text"
                  value={remoteEndpoint}
                  onChange={(e) => setRemoteEndpoint(e.target.value)}
                  placeholder="https://my-team-agent.internal or ssh://user@box"
                  className="w-full bg-bg-base border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="text-xs text-text-secondary block mb-1">
                  API Token / Passkey (Optional)
                </label>
                <input
                  type="password"
                  value={remoteToken}
                  onChange={(e) => setRemoteToken(e.target.value)}
                  placeholder="sk-..."
                  className="w-full bg-bg-base border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent"
                />
              </div>

              <button
                onClick={handleDiscoverRemote}
                disabled={isDiscovering || !remoteEndpoint.trim()}
                className="w-full py-2 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium transition-all flex items-center justify-center gap-2 shadow-sm"
              >
                {isDiscovering ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Search className="w-3.5 h-3.5" />}
                <span>{isDiscovering ? 'Discovering...' : 'Discover Remote Skills'}</span>
              </button>

              {remoteError && (
                <div className="p-2.5 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-xs">
                  {remoteError}
                </div>
              )}

              {remoteDiscovered.length > 0 && (
                <div className="mt-4 border border-border-subtle rounded-lg max-h-56 overflow-y-auto divide-y divide-border-subtle">
                  {remoteDiscovered.map((s) => (
                    <div key={s.id} className="p-3 flex items-center justify-between text-xs hover:bg-bg-hover">
                      <div>
                        <div className="font-medium text-text-primary">{s.name}</div>
                        <div className="text-[11px] text-text-secondary line-clamp-1">{s.description}</div>
                      </div>
                      <button
                        onClick={() => handleImportRemoteSkill(s.id)}
                        className="px-2.5 py-1 bg-accent/20 hover:bg-accent/30 text-accent rounded text-[11px] font-medium transition-colors"
                      >
                        Import
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* New Skill Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <form
            onSubmit={handleCreateSkillSubmit}
            className="w-full max-w-lg bg-bg-elevated border border-border-strong rounded-xl p-6 shadow-2xl space-y-4"
          >
            <div className="flex items-center justify-between border-b border-border-subtle pb-3">
              <h3 className="text-sm font-semibold text-text-primary">Create New Custom Skill</h3>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="text-text-tertiary hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-text-secondary block mb-1">Skill Name</label>
                <input
                  type="text"
                  required
                  value={newSkillName}
                  onChange={(e) => setNewSkillName(e.target.value)}
                  placeholder="e.g., Pull Request Reviewer"
                  className="w-full bg-bg-base border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="text-xs text-text-secondary block mb-1">Description</label>
                <input
                  type="text"
                  value={newSkillDesc}
                  onChange={(e) => setNewSkillDesc(e.target.value)}
                  placeholder="Summarize git diff and write review comments"
                  className="w-full bg-bg-base border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="text-xs text-text-secondary block mb-1">Target Tool</label>
                <select
                  value={newSkillTool}
                  onChange={(e) => setNewSkillTool(e.target.value)}
                  className="w-full bg-bg-base border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent"
                >
                  <option value="agent-engine">Agent Engine (data/skills/)</option>
                  <option value="claude-code">Claude Code (~/.claude/commands/)</option>
                  <option value="cursor">Cursor (.cursor/rules/)</option>
                  <option value="codex">Codex (.codex/skills/)</option>
                  <option value="goose">Goose (~/.config/goose/skills/)</option>
                </select>
              </div>

              <div>
                <label className="text-xs text-text-secondary block mb-1">Markdown / Frontmatter Body</label>
                <textarea
                  rows={6}
                  value={newSkillContent}
                  onChange={(e) => setNewSkillContent(e.target.value)}
                  className="w-full bg-bg-base border border-border-subtle rounded-lg p-3 font-mono text-xs text-text-primary focus:outline-none focus:border-accent resize-none"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-border-subtle">
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="px-3 py-1.5 bg-bg-base hover:bg-bg-hover text-text-secondary rounded-lg text-xs"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium shadow-sm"
              >
                Create Skill
              </button>
            </div>
          </form>
        </div>
      )}

      {/* New Collection Modal */}
      {showCreateCollModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <form
            onSubmit={handleCreateCollectionSubmit}
            className="w-full max-w-md bg-bg-elevated border border-border-strong rounded-xl p-6 shadow-2xl space-y-4"
          >
            <div className="flex items-center justify-between border-b border-border-subtle pb-3">
              <h3 className="text-sm font-semibold text-text-primary">Create Skill Collection</h3>
              <button
                type="button"
                onClick={() => setShowCreateCollModal(false)}
                className="text-text-tertiary hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-xs text-text-secondary block mb-1">Collection Name</label>
                <input
                  type="text"
                  required
                  value={newCollName}
                  onChange={(e) => setNewCollName(e.target.value)}
                  placeholder="e.g., DevOps Essentials"
                  className="w-full bg-bg-base border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="text-xs text-text-secondary block mb-1">Description</label>
                <input
                  type="text"
                  value={newCollDesc}
                  onChange={(e) => setNewCollDesc(e.target.value)}
                  placeholder="Skills for containerization, CI/CD, and deployments"
                  className="w-full bg-bg-base border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent"
                />
              </div>

              <div>
                <label className="text-xs text-text-secondary block mb-1">Tags (comma separated)</label>
                <input
                  type="text"
                  value={newCollTags}
                  onChange={(e) => setNewCollTags(e.target.value)}
                  placeholder="devops, docker, ci"
                  className="w-full bg-bg-base border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-border-subtle">
              <button
                type="button"
                onClick={() => setShowCreateCollModal(false)}
                className="px-3 py-1.5 bg-bg-base hover:bg-bg-hover text-text-secondary rounded-lg text-xs"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium shadow-sm"
              >
                Create Collection
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};
