import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  ArrowUp,
  Square,
  Paperclip,
  Folder,
  Sparkles,
  Zap,
  Brain,
  X,
  FileCode,
  ChevronDown,
  Coins,
  Globe,
  Database,
  ShieldCheck,
  Terminal,
  FolderTree,
  SlidersHorizontal,
  Check,
  Tag,
  Wand2,
} from 'lucide-react';
import { Mode, ModelTier, AttachmentFile, SkillItem, PluginItem, SelectedSkill } from '../types';
import { SlashCommandPopup, SlashCommandItem, BUILT_IN_COMMANDS } from './SlashCommandPopup';
import { sidecarClient } from '../api/client';

export interface ChatInputProps {
  mode?: Mode;
  placeholder?: string;
  model: ModelTier;
  projectId?: string;
  projectName?: string;
  isStreaming?: boolean;
  onSend: (
    message: string,
    options?: {
      model: ModelTier;
      projectId?: string;
      attachments?: AttachmentFile[];
      skill?: SelectedSkill;
      enabledPlugins?: string[];
    }
  ) => void;
  onStop?: () => void;
  onModeChange?: (mode: Mode) => void;
  onModelChange?: (model: ModelTier) => void;
  onProjectChange?: (projectId: string) => void;
  onClearChat?: () => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
  initialValue?: string;
  className?: string;
}

const MODEL_TIER_CONFIG: Record<
  ModelTier,
  { label: string; ratePer1k: number; rateStr: string; icon: React.ReactNode }
> = {
  instant: {
    label: 'Instant High',
    ratePer1k: 0.0002,
    rateStr: '$0.0002/1k',
    icon: <Zap className="w-3.5 h-3.5 text-warning" />,
  },
  swarm: {
    label: 'K3 Swarm High',
    ratePer1k: 0.0015,
    rateStr: '$0.0015/1k',
    icon: <Sparkles className="w-3.5 h-3.5 text-accent" />,
  },
  reasoning: {
    label: 'K3 High',
    ratePer1k: 0.008,
    rateStr: '$0.0080/1k',
    icon: <Brain className="w-3.5 h-3.5 text-success" />,
  },
};

const MODE_PLACEHOLDERS: Record<string, string> = {
  home: "Type '/' to invoke plugins and skills, or ask anything...",
  code: "Describe a feature to build, code to refactor, or paste a bug trace...",
  'deep-research': "Enter research topic, hypotheses, or market question to investigate...",
  docs: "Describe document outline, contract clause, or drafting requirements...",
  sheets: "Describe data to analyze, spreadsheet transformations, or formulas...",
  slides: "Describe your presentation topic, audience, and key takeaways...",
  websites: "Describe the site to build, landing page sections, or brand specs...",
  design: "Describe UI components, layout mockups, or visual design tokens...",
  diagrams: "Describe system architecture, microservices, or data pipeline flow...",
  swarm: "Assign a complex multi-agent parallel mission to your AI team...",
  workflows: "Describe workflow nodes, approval gates, and deterministic steps...",
};

const DEFAULT_PLUGINS: PluginItem[] = [
  {
    id: 'web-search',
    name: 'Web Search',
    description: 'Live web grounding and citation synthesis',
    iconName: 'globe',
    enabled: true,
    tier: 'free',
  },
  {
    id: 'rag-memory',
    name: 'RAG Memory',
    description: 'Semantic retrieval across observational memories',
    iconName: 'database',
    enabled: true,
    tier: 'free',
  },
  {
    id: 'guardrails',
    name: 'Safety Guardrails',
    description: 'High-assurance zero-trust policy checks (ADR-008)',
    iconName: 'shield',
    enabled: true,
    tier: 'free',
  },
  {
    id: 'sandbox',
    name: 'Python Sandbox',
    description: 'Local deterministic AST code execution',
    iconName: 'terminal',
    enabled: false,
    tier: 'pro',
  },
  {
    id: 'file-context',
    name: 'File Context',
    description: 'Workspace AST code maps and project grounding',
    iconName: 'folder-tree',
    enabled: false,
    tier: 'free',
  },
];

export const ChatInput: React.FC<ChatInputProps> = ({
  mode = 'home',
  placeholder,
  model,
  projectId,
  projectName,
  isStreaming = false,
  onSend,
  onStop,
  onModeChange,
  onModelChange,
  onProjectChange,
  onClearChat,
  inputRef: externalInputRef,
  initialValue = '',
  className = '',
}) => {
  const [prompt, setPrompt] = useState(initialValue);
  const [attachments, setAttachments] = useState<AttachmentFile[]>([]);
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const [projectDropdownOpen, setProjectDropdownOpen] = useState(false);
  const [pluginsDropdownOpen, setPluginsDropdownOpen] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);

  // Slash commands & Skills state
  const [skillsCatalog, setSkillsCatalog] = useState<SkillItem[]>([]);
  const [slashQuery, setSlashQuery] = useState<string | null>(null);
  const [slashSelectedIndex, setSlashSelectedIndex] = useState(0);
  const [selectedSkill, setSelectedSkill] = useState<SelectedSkill | null>(null);
  const [editingParamKey, setEditingParamKey] = useState<string | null>(null);

  // Plugin quick-toggles state
  const [plugins, setPlugins] = useState<PluginItem[]>(DEFAULT_PLUGINS);

  const internalInputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeTextareaRef = externalInputRef || internalInputRef;

  // Load skills catalog on mount
  useEffect(() => {
    let mounted = true;
    const fetchSkills = async () => {
      const list = await sidecarClient.getSkills();
      if (mounted) {
        setSkillsCatalog(list);
      }
    };
    fetchSkills();
    return () => {
      mounted = false;
    };
  }, []);

  // Sync external initialValue
  useEffect(() => {
    if (initialValue && initialValue !== prompt) {
      setPrompt(initialValue);
      adjustHeight();
    }
  }, [initialValue]);

  // Adjust textarea height dynamically
  const adjustHeight = useCallback(() => {
    const el = activeTextareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    const newHeight = Math.min(Math.max(el.scrollHeight, 64), 220);
    el.style.height = `${newHeight}px`;
  }, [activeTextareaRef]);

  useEffect(() => {
    adjustHeight();
  }, [prompt, adjustHeight]);

  // Check for slash command trigger
  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value;
    setPrompt(text);

    const cursorPos = e.target.selectionStart;
    const textUpToCursor = text.substring(0, cursorPos);
    const lastSlashIdx = textUpToCursor.lastIndexOf('/');

    // Slash must be at the beginning of string or preceded by whitespace
    if (lastSlashIdx !== -1) {
      const isStartOrWhitespace =
        lastSlashIdx === 0 || /\s/.test(textUpToCursor[lastSlashIdx - 1]);
      const textAfterSlash = textUpToCursor.substring(lastSlashIdx);
      // Ensure no spaces between slash and cursor
      if (isStartOrWhitespace && !/\s/.test(textAfterSlash)) {
        setSlashQuery(textAfterSlash);
        setSlashSelectedIndex(0);
        return;
      }
    }

    setSlashQuery(null);
  };

  // Toggle active plugin
  const togglePlugin = (id: string) => {
    setPlugins((prev) =>
      prev.map((p) => (p.id === id ? { ...p, enabled: !p.enabled } : p))
    );
  };

  // Handle slash item selection
  const handleSelectSlashItem = (item: SlashCommandItem) => {
    setSlashQuery(null);

    // Remove the slash command text from prompt
    const el = activeTextareaRef.current;
    if (el) {
      const cursorPos = el.selectionStart;
      const textUpToCursor = prompt.substring(0, cursorPos);
      const lastSlashIdx = textUpToCursor.lastIndexOf('/');
      if (lastSlashIdx !== -1) {
        const textBefore = prompt.substring(0, lastSlashIdx);
        const textAfter = prompt.substring(cursorPos);
        setPrompt((textBefore + textAfter).trim());
      }
    }

    // Handle Built-in Commands
    if (item.category === 'Command') {
      if (item.command === '/clear') {
        onClearChat?.();
        setSelectedSkill(null);
        setPrompt('');
        return;
      }
      if (item.command === '/mode') {
        onModeChange?.('code');
        return;
      }
      if (item.command === '/workflow') {
        onModeChange?.('workflows');
        return;
      }
    }

    // Handle Plugins
    if (item.category === 'Plugin') {
      if (item.command === '/web-search') togglePlugin('web-search');
      if (item.command === '/memory') togglePlugin('rag-memory');
      if (item.command === '/sandbox') togglePlugin('sandbox');
      return;
    }

    // Handle Skills: Set selectedSkill with structured parameter chips
    if (item.skill) {
      const initialParams: Record<string, string> = {};
      item.skill.inputs.forEach((inp) => {
        initialParams[inp] = item.skill?.sampleInputs?.[inp] || '';
      });

      setSelectedSkill({
        skill: item.skill,
        parameters: initialParams,
      });

      // Focus first parameter or prompt
      if (item.skill.inputs.length > 0) {
        setEditingParamKey(item.skill.inputs[0]);
      }
    }
  };

  // Pre-calculate visible slash commands for keyboard navigation
  const getFilteredSlashItems = () => {
    if (!slashQuery) return [];
    const cleanQuery = slashQuery.replace(/^\//, '').toLowerCase().trim();

    const skillCommands: SlashCommandItem[] = skillsCatalog.map((s) => ({
      id: `skill-${s.id}`,
      command: s.command.startsWith('/') ? s.command : `/${s.command}`,
      name: s.name,
      description: s.description,
      category: 'Skill',
      icon: <Sparkles className="w-4 h-4 text-accent" />,
      inputs: s.inputs,
      skill: s,
    }));

    const all = [...skillCommands, ...BUILT_IN_COMMANDS];
    if (!cleanQuery) return all;

    return all.filter((item) => {
      const matchCmd = item.command.toLowerCase().includes(cleanQuery);
      const matchName = item.name.toLowerCase().includes(cleanQuery);
      const matchDesc = item.description.toLowerCase().includes(cleanQuery);
      const matchCat = item.category.toLowerCase().includes(cleanQuery);
      return matchCmd || matchName || matchDesc || matchCat;
    });
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // If slash command popup is open, intercept keyboard navigation
    if (slashQuery !== null) {
      const items = getFilteredSlashItems();
      if (items.length > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          setSlashSelectedIndex((prev) => (prev + 1) % items.length);
          return;
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          setSlashSelectedIndex((prev) => (prev - 1 + items.length) % items.length);
          return;
        }
        if (e.key === 'Enter' || e.key === 'Tab') {
          e.preventDefault();
          const chosen = items[slashSelectedIndex] || items[0];
          if (chosen) {
            handleSelectSlashItem(chosen);
          }
          return;
        }
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        setSlashQuery(null);
        return;
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSubmit = () => {
    if (isStreaming) {
      onStop?.();
      return;
    }
    const cleanText = prompt.trim();
    if (!cleanText && attachments.length === 0 && !selectedSkill) return;

    const enabledPluginIds = plugins.filter((p) => p.enabled).map((p) => p.id);

    onSend(cleanText, {
      model,
      projectId,
      attachments: attachments.length > 0 ? attachments : undefined,
      skill: selectedSkill || undefined,
      enabledPlugins: enabledPluginIds,
    });

    setPrompt('');
    setAttachments([]);
    setSelectedSkill(null);
    setEditingParamKey(null);
    if (activeTextareaRef.current) {
      activeTextareaRef.current.style.height = 'auto';
    }
  };

  const handleFilesSelected = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    const newAttachments: AttachmentFile[] = Array.from(files).map((f) => ({
      id: `${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
      name: f.name,
      size: f.size,
      type: f.type || 'application/octet-stream',
    }));
    setAttachments((prev) => [...prev, ...newAttachments]);
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const updateSkillParam = (key: string, value: string) => {
    if (!selectedSkill) return;
    setSelectedSkill({
      ...selectedSkill,
      parameters: {
        ...selectedSkill.parameters,
        [key]: value,
      },
    });
  };

  const fillSampleInputs = () => {
    if (!selectedSkill?.skill.sampleInputs) return;
    setSelectedSkill({
      ...selectedSkill,
      parameters: { ...selectedSkill.skill.sampleInputs },
    });
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  // Cost estimator calculation
  const approxTokens = Math.max(1, Math.ceil(prompt.trim().length / 4));
  const currentTierConfig = MODEL_TIER_CONFIG[model] || MODEL_TIER_CONFIG.instant;
  const rawCost = (approxTokens / 1000) * currentTierConfig.ratePer1k;
  const costPreview =
    prompt.trim().length === 0
      ? '$0.00 (Cache/Code)'
      : rawCost < 0.0001
      ? '<$0.0001 (CODE Tier)'
      : `$${rawCost.toFixed(4)}`;

  const currentPlaceholder =
    placeholder || MODE_PLACEHOLDERS[mode] || MODE_PLACEHOLDERS.home;

  const renderPluginIcon = (iconName: string) => {
    switch (iconName) {
      case 'globe':
        return <Globe className="w-3.5 h-3.5" />;
      case 'database':
        return <Database className="w-3.5 h-3.5" />;
      case 'shield':
        return <ShieldCheck className="w-3.5 h-3.5" />;
      case 'terminal':
        return <Terminal className="w-3.5 h-3.5" />;
      case 'folder-tree':
        return <FolderTree className="w-3.5 h-3.5" />;
      default:
        return <Zap className="w-3.5 h-3.5" />;
    }
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragOver(false);
        handleFilesSelected(e.dataTransfer.files);
      }}
      className={`w-full bg-bg-elevated border rounded-xl p-3 shadow-2xl transition-all duration-150 relative ${
        isDragOver
          ? 'border-accent bg-accent/5 ring-1 ring-accent'
          : 'border-border-strong focus-within:border-accent/80 focus-within:ring-1 focus-within:ring-accent/40'
      } ${className}`}
    >
      {/* Floating Slash Command Popup */}
      {slashQuery !== null && (
        <SlashCommandPopup
          query={slashQuery}
          skills={skillsCatalog}
          selectedIndex={slashSelectedIndex}
          onSelect={handleSelectSlashItem}
          onClose={() => setSlashQuery(null)}
        />
      )}

      {/* Structured Selected Skill & Parameter Chips Header */}
      {selectedSkill && (
        <div className="mb-2.5 pb-2 border-b border-border-subtle bg-bg-base/60 -mx-1 px-2 py-1.5 rounded-lg text-left">
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-1.5">
              <span className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-accent/20 border border-accent/40 text-xs font-semibold text-accent">
                <Sparkles className="w-3.5 h-3.5" />
                <span>{selectedSkill.skill.name}</span>
                <span className="text-[10px] font-mono text-accent/80 ml-1">
                  ({selectedSkill.skill.command})
                </span>
              </span>
              {selectedSkill.skill.sampleInputs && (
                <button
                  type="button"
                  onClick={fillSampleInputs}
                  className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono text-text-tertiary hover:text-accent hover:bg-bg-hover transition-colors"
                  title="Auto-populate with template sample inputs"
                >
                  <Wand2 className="w-3 h-3" />
                  <span>Auto-fill</span>
                </button>
              )}
            </div>
            <button
              type="button"
              onClick={() => {
                setSelectedSkill(null);
                setEditingParamKey(null);
              }}
              className="text-text-tertiary hover:text-danger p-1 rounded transition-colors"
              title="Remove skill"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Interactive Parameter Chips */}
          <div className="flex flex-wrap gap-1.5 items-center">
            <span className="text-[10px] font-mono uppercase text-text-tertiary flex items-center gap-1">
              <Tag className="w-3 h-3" />
              <span>Inputs:</span>
            </span>
            {selectedSkill.skill.inputs.map((paramKey) => {
              const val = selectedSkill.parameters[paramKey] || '';
              const isEditing = editingParamKey === paramKey;
              return (
                <div
                  key={paramKey}
                  className={`flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-mono transition-all ${
                    isEditing
                      ? 'bg-bg-elevated border-accent text-accent ring-1 ring-accent/30'
                      : val
                      ? 'bg-bg-base border-border-strong text-text-primary'
                      : 'bg-bg-base border-border-subtle text-text-tertiary'
                  }`}
                >
                  <span className="text-[11px] font-semibold text-text-secondary">
                    {paramKey}:
                  </span>
                  {isEditing ? (
                    <input
                      type="text"
                      autoFocus
                      value={val}
                      onChange={(e) => updateSkillParam(paramKey, e.target.value)}
                      onBlur={() => setEditingParamKey(null)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          setEditingParamKey(null);
                        }
                      }}
                      placeholder="enter value..."
                      className="bg-transparent outline-none text-xs text-text-primary min-w-[80px] max-w-[160px]"
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => setEditingParamKey(paramKey)}
                      className="hover:underline max-w-[140px] truncate text-left"
                      title={`Click to edit parameter '${paramKey}'`}
                    >
                      {val || <span className="italic text-[10px]">edit...</span>}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Attachment Chips row */}
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-2 pb-2 mb-2 border-b border-border-subtle text-left">
          {attachments.map((file) => (
            <div
              key={file.id}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-bg-base border border-border-strong text-xs text-text-primary group"
            >
              <FileCode className="w-3.5 h-3.5 text-accent flex-shrink-0" />
              <span className="truncate max-w-[140px] font-mono text-[11px]">{file.name}</span>
              <span className="text-[10px] text-text-tertiary font-mono">
                ({formatFileSize(file.size)})
              </span>
              <button
                type="button"
                onClick={() => removeAttachment(file.id)}
                className="ml-1 text-text-tertiary hover:text-danger transition-colors"
                title="Remove attachment"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Main Textarea */}
      <textarea
        ref={activeTextareaRef}
        value={prompt}
        onChange={handleTextChange}
        onKeyDown={handleKeyDown}
        placeholder={
          selectedSkill
            ? `Additional prompt instructions for ${selectedSkill.skill.name}...`
            : currentPlaceholder
        }
        rows={2}
        className="w-full bg-transparent resize-none outline-none text-sm text-text-primary placeholder:text-text-tertiary leading-relaxed min-h-[52px]"
      />

      {/* Hidden File Input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => handleFilesSelected(e.target.files)}
      />

      {/* Bottom Controls Bar */}
      <div className="pt-2 mt-1 border-t border-border-subtle flex items-center justify-between gap-2 select-none">
        {/* Left cluster: Attachments, Mode Chip, Project, Plugins Row */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* File Attachment Button */}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            title="Attach documents, CSVs, or code files"
            className="p-1.5 rounded-md hover:bg-bg-hover text-text-tertiary hover:text-text-primary transition-colors flex items-center gap-1"
          >
            <Paperclip className="w-4 h-4" />
          </button>

          {/* Mode Chip */}
          {mode && mode !== 'home' && (
            <button
              type="button"
              onClick={() => onModeChange?.('home')}
              title={`Active Mode: ${mode}. Click to reset to default chat.`}
              className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-accent/15 border border-accent/30 text-[11px] font-medium text-accent hover:bg-accent/25 transition-all"
            >
              <span className="capitalize">{mode.replace('-', ' ')}</span>
              <X className="w-3 h-3 text-accent/80 hover:text-accent" />
            </button>
          )}

          {/* Project Selector */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setProjectDropdownOpen(!projectDropdownOpen)}
              className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary hover:text-text-primary transition-colors"
            >
              <Folder className="w-3.5 h-3.5 text-text-tertiary" />
              <span className="truncate max-w-[120px]">
                {projectName || 'Select project'}
              </span>
              <ChevronDown className="w-3 h-3 text-text-tertiary" />
            </button>

            {projectDropdownOpen && (
              <div className="absolute left-0 bottom-full mb-1 w-48 bg-bg-elevated border border-border-strong rounded-lg shadow-2xl py-1 z-50">
                <div className="px-2.5 py-1 text-[10px] uppercase font-semibold text-text-tertiary tracking-wider border-b border-border-subtle">
                  Bind Chat to Workspace
                </div>
                <button
                  type="button"
                  onClick={() => {
                    onProjectChange?.('');
                    setProjectDropdownOpen(false);
                  }}
                  className={`w-full text-left px-2.5 py-1.5 text-xs hover:bg-bg-hover transition-colors ${
                    !projectId ? 'text-accent font-medium' : 'text-text-secondary'
                  }`}
                >
                  None (Global Scratchpad)
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onProjectChange?.('1');
                    setProjectDropdownOpen(false);
                  }}
                  className={`w-full text-left px-2.5 py-1.5 text-xs hover:bg-bg-hover transition-colors ${
                    projectId === '1' ? 'text-accent font-medium' : 'text-text-secondary'
                  }`}
                >
                  Organiser Workspace
                </button>
                <button
                  type="button"
                  onClick={() => {
                    onProjectChange?.('2');
                    setProjectDropdownOpen(false);
                  }}
                  className={`w-full text-left px-2.5 py-1.5 text-xs hover:bg-bg-hover transition-colors ${
                    projectId === '2' ? 'text-accent font-medium' : 'text-text-secondary'
                  }`}
                >
                  Client Website
                </button>
              </div>
            )}
          </div>

          <div className="hidden sm:block h-3.5 w-px bg-border-subtle" />

          {/* Plugin Quick-Toggles Strip */}
          <div className="flex items-center gap-1 bg-bg-base/80 border border-border-subtle rounded-lg p-0.5">
            {plugins.map((plugin) => (
              <button
                key={plugin.id}
                type="button"
                onClick={() => togglePlugin(plugin.id)}
                title={`${plugin.name} (${plugin.enabled ? 'Enabled' : 'Disabled'})`}
                className={`p-1 rounded transition-all ${
                  plugin.enabled
                    ? 'text-accent bg-accent/15 border border-accent/30 shadow-xs'
                    : 'text-text-tertiary hover:text-text-secondary hover:bg-bg-hover border border-transparent'
                }`}
              >
                {renderPluginIcon(plugin.iconName)}
              </button>
            ))}

            {/* Plugins Dropdown Trigger */}
            <div className="relative">
              <button
                type="button"
                onClick={() => setPluginsDropdownOpen(!pluginsDropdownOpen)}
                className="p-1 rounded text-text-tertiary hover:text-text-primary hover:bg-bg-hover transition-colors flex items-center"
                title="Manage Plugins & Grounding Tools"
              >
                <SlidersHorizontal className="w-3.5 h-3.5" />
              </button>

              {pluginsDropdownOpen && (
                <div className="absolute left-0 bottom-full mb-1 w-64 bg-bg-elevated border border-border-strong rounded-xl shadow-2xl py-1.5 z-50 text-left">
                  <div className="px-3 py-1 text-[10px] uppercase font-semibold text-text-tertiary tracking-wider border-b border-border-subtle flex items-center justify-between">
                    <span>Active Grounding Plugins</span>
                    <span className="font-mono text-accent">
                      {plugins.filter((p) => p.enabled).length}/{plugins.length} ON
                    </span>
                  </div>
                  <div className="p-1 space-y-1">
                    {plugins.map((plugin) => (
                      <div
                        key={plugin.id}
                        onClick={() => togglePlugin(plugin.id)}
                        className="px-2.5 py-1.5 rounded-lg hover:bg-bg-hover flex items-center justify-between cursor-pointer transition-colors"
                      >
                        <div className="flex items-center gap-2">
                          <div
                            className={`p-1 rounded ${
                              plugin.enabled
                                ? 'bg-accent/15 text-accent'
                                : 'bg-bg-base text-text-tertiary'
                            }`}
                          >
                            {renderPluginIcon(plugin.iconName)}
                          </div>
                          <div>
                            <div className="text-xs font-medium text-text-primary">
                              {plugin.name}
                            </div>
                            <div className="text-[10px] text-text-tertiary">
                              {plugin.description}
                            </div>
                          </div>
                        </div>
                        {plugin.enabled && (
                          <Check className="w-4 h-4 text-accent flex-shrink-0" />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="hidden lg:block h-3.5 w-px bg-border-subtle" />

          {/* Pre-execution Cost Estimate */}
          <div
            title={`Approx. ${approxTokens} tokens on ${currentTierConfig.label}`}
            className="hidden lg:flex items-center gap-1 text-[11px] font-mono text-text-tertiary"
          >
            <Coins className="w-3 h-3 text-success/80" />
            <span>Est: {costPreview}</span>
          </div>
        </div>

        {/* Right cluster: Model Tier Dropdown & Send/Stop Button */}
        <div className="flex items-center gap-2">
          {/* Quick Model Selector in Input */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
              className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-bg-base hover:bg-bg-hover border border-border-subtle hover:border-border-strong text-xs text-text-primary transition-colors"
            >
              {currentTierConfig.icon}
              <span className="hidden md:inline font-medium text-[11px]">
                {currentTierConfig.label}
              </span>
              <ChevronDown className="w-3 h-3 text-text-tertiary" />
            </button>

            {modelDropdownOpen && (
              <div className="absolute right-0 bottom-full mb-1 w-56 bg-bg-elevated border border-border-strong rounded-lg shadow-2xl py-1 z-50">
                <div className="px-3 py-1 text-[10px] uppercase font-semibold text-text-tertiary tracking-wider border-b border-border-subtle">
                  Model Routing Tier
                </div>
                {(Object.keys(MODEL_TIER_CONFIG) as ModelTier[]).map((tierKey) => {
                  const item = MODEL_TIER_CONFIG[tierKey];
                  return (
                    <button
                      key={tierKey}
                      type="button"
                      onClick={() => {
                        onModelChange?.(tierKey);
                        setModelDropdownOpen(false);
                      }}
                      className={`w-full text-left px-3 py-1.5 hover:bg-bg-hover flex items-center justify-between transition-colors ${
                        model === tierKey ? 'bg-bg-hover' : ''
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {item.icon}
                        <span className="text-xs text-text-primary font-medium">
                          {item.label}
                        </span>
                      </div>
                      <span className="text-[10px] font-mono text-text-tertiary">
                        {item.rateStr}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Send / Stop Button */}
          {isStreaming ? (
            <button
              type="button"
              onClick={onStop}
              title="Stop generation (Esc)"
              className="p-2 rounded-lg bg-danger hover:bg-danger/90 text-white shadow-md transition-all flex items-center justify-center animate-pulse"
            >
              <Square className="w-4 h-4 fill-white" />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!prompt.trim() && attachments.length === 0 && !selectedSkill}
              title={
                !prompt.trim() && attachments.length === 0 && !selectedSkill
                  ? 'Enter a prompt or type / for skills'
                  : 'Send message (Enter)'
              }
              className={`p-2 rounded-lg flex items-center justify-center transition-all ${
                prompt.trim() || attachments.length > 0 || selectedSkill
                  ? 'bg-accent hover:bg-accent-hover text-white shadow-md cursor-pointer'
                  : 'bg-bg-hover text-text-tertiary cursor-not-allowed opacity-60'
              }`}
            >
              <ArrowUp className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
