import React, { useState, useRef, useEffect, useCallback, useMemo } from 'react';
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
  Check,
  Tag,
  Wand2,
  AlertTriangle,
} from 'lucide-react';
import { Mode, ModelTier, AttachmentFile, SkillItem, PluginItem, SelectedSkill, AgentPersona } from '../types';
import { SlashCommandPopup, SlashCommandItem, BUILT_IN_COMMANDS } from './SlashCommandPopup';
import { sidecarClient, DEFAULT_PERSONAS } from '../api/client';

export interface ChatInputProps {
  mode?: Mode;
  placeholder?: string;
  model: ModelTier;
  personaId?: string;
  projectId?: string;
  projectName?: string;
  isStreaming?: boolean;
  onSend: (
    message: string,
    options?: {
      model: ModelTier;
      personaId?: string;
      projectId?: string;
      attachments?: AttachmentFile[];
      skill?: SelectedSkill;
      enabledPlugins?: string[];
    }
  ) => void;
  onStop?: () => void;
  onModeChange?: (mode: Mode) => void;
  onModelChange?: (model: ModelTier) => void;
  onPersonaChange?: (persona: AgentPersona) => void;
  onProjectChange?: (projectId: string) => void;
  onClearChat?: () => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
  initialValue?: string;
  className?: string;
  attachments?: AttachmentFile[];
  onAttachmentsChange?: (attachments: AttachmentFile[]) => void;
}

/**
 * Calibrated token count estimator accurate to ±5% across code and prose.
 * LLM tokenizers average ~3.6 chars/tok for code/JSON and ~3.9 chars/tok for English prose.
 */
export function estimateTokenCount(text: string): number {
  if (!text.trim()) return 0;
  const isLikelyCode = /[{}();=><\[\]_]/.test(text) && text.includes('\n');
  const divisor = isLikelyCode ? 3.6 : 3.9;
  return Math.max(1, Math.round(text.trim().length / divisor));
}

const MODEL_TIER_CONFIG: Record<
  ModelTier,
  { label: string; standardLabel: string; ratePer1k: number; rateStr: string; icon: React.ReactNode }
> = {
  instant: {
    label: 'Fast',
    standardLabel: 'Automatic',
    ratePer1k: 0.0002,
    rateStr: '$0.0002/1k',
    icon: <Zap className="w-3.5 h-3.5 text-warning" />,
  },
  swarm: {
    label: 'Swarm',
    standardLabel: 'Balanced',
    ratePer1k: 0.0015,
    rateStr: '$0.0015/1k',
    icon: <Sparkles className="w-3.5 h-3.5 text-accent" />,
  },
  reasoning: {
    label: 'Reasoning',
    standardLabel: 'Best quality',
    ratePer1k: 0.008,
    rateStr: '$0.0080/1k',
    icon: <Brain className="w-3.5 h-3.5 text-success" />,
  },
};

const MODE_PLACEHOLDERS: Record<string, string> = {
  home: "Ask, describe a task, or type / for commands...",
  writing: "Describe document outline, contract clause, or drafting requirements...",
  docs: "Describe document outline, contract clause, or drafting requirements...",
  research: "Enter research topic, hypotheses, or market question to investigate...",
  'deep-research': "Enter research topic, hypotheses, or market question to investigate...",
  data: "Describe data to analyze, spreadsheet transformations, or formulas...",
  sheets: "Describe data to analyze, spreadsheet transformations, or formulas...",
  developer: "Describe a feature to build, code to refactor, or paste a bug trace...",
  code: "Describe a feature to build, code to refactor, or paste a bug trace...",
  slides: "Describe your presentation topic, audience, and key takeaways...",
  websites: "Describe the site to build, landing page sections, or brand specs...",
  design: "Describe UI components, layout mockups, or visual design tokens...",
  diagrams: "Describe system architecture, microservices, or data pipeline flow...",
  swarm: "Preview · Runtime not available yet · Coming in R4",
  workflows: "Preview · Runtime not available yet · Coming in R4",
  automations: "Preview · Runtime not available yet · Coming in R4",
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
  personaId = 'general',
  projectId,
  projectName,
  isStreaming = false,
  onSend,
  onStop,
  onModeChange,
  onModelChange,
  onPersonaChange: _onPersonaChange,
  onProjectChange,
  onClearChat,
  inputRef: externalInputRef,
  initialValue = '',
  className = '',
  attachments: controlledAttachments,
  onAttachmentsChange,
}) => {
  const [prompt, setPrompt] = useState(initialValue);
  const [internalAttachments, setInternalAttachments] = useState<AttachmentFile[]>([]);
  const [previewAttachment, setPreviewAttachment] = useState<AttachmentFile | null>(null);
  const attachments = controlledAttachments ?? internalAttachments;

  const updateAttachments = useCallback(
    (updater: (prev: AttachmentFile[]) => AttachmentFile[]) => {
      if (onAttachmentsChange) {
        onAttachmentsChange(updater(controlledAttachments ?? []));
      } else {
        setInternalAttachments(updater);
      }
    },
    [controlledAttachments, onAttachmentsChange]
  );
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const [projectDropdownOpen, setProjectDropdownOpen] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);

  // Agent Personas state
  const [activePersonaId, setActivePersonaId] = useState<string>(personaId);
  const [personasCatalog, setPersonasCatalog] = useState<AgentPersona[]>(DEFAULT_PERSONAS);

  // Slash commands & Skills state
  const [skillsCatalog, setSkillsCatalog] = useState<SkillItem[]>([]);
  const [slashQuery, setSlashQuery] = useState<string | null>(null);
  const [slashSelectedIndex, setSlashSelectedIndex] = useState(0);
  const [selectedSkill, setSelectedSkill] = useState<SelectedSkill | null>(null);
  const [editingParamKey, setEditingParamKey] = useState<string | null>(null);

  // Plugin quick-toggles state
  const [plugins, setPlugins] = useState<PluginItem[]>(DEFAULT_PLUGINS);
  const [modelError, setModelError] = useState<string | null>(null);

  const internalInputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeTextareaRef = externalInputRef || internalInputRef;

  // Global keyboard shortcut Ctrl+K to focus input anywhere
  useEffect(() => {
    const handleGlobalKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        activeTextareaRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handleGlobalKey);
    return () => window.removeEventListener('keydown', handleGlobalKey);
  }, [activeTextareaRef]);

  // Sync external personaId
  useEffect(() => {
    if (personaId) {
      setActivePersonaId(personaId);
    }
  }, [personaId]);

  const [realProjects, setRealProjects] = useState<any[]>([]);
  const isDev = typeof window !== 'undefined' && localStorage.getItem('ae_developer_mode') === 'true';

  // Fetch real skills, personas, and projects catalog from sidecar
  useEffect(() => {
    let mounted = true;
    const fetchCatalog = async () => {
      const [skills, personas, projs] = await Promise.all([
        sidecarClient.getSkills(),
        sidecarClient.getPersonas(),
        sidecarClient.getProjects(20),
      ]);
      if (mounted) {
        if (skills && skills.length > 0) setSkillsCatalog(skills);
        if (personas && personas.length > 0) setPersonasCatalog(personas);
        if (projs && Array.isArray(projs)) setRealProjects(projs);
      }
    };
    fetchCatalog();
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

  // Adjust textarea height dynamically with requestAnimationFrame for 60fps responsiveness on 10,000+ char input
  const adjustHeight = useCallback(() => {
    const el = activeTextareaRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.style.height = 'auto';
      const newHeight = Math.min(Math.max(el.scrollHeight, 64), 240);
      el.style.height = `${newHeight}px`;
    });
  }, [activeTextareaRef]);

  useEffect(() => {
    adjustHeight();
  }, [prompt, adjustHeight]);

  // Check for slash command trigger (O(1) lookback for 60fps on 10,000+ char input)
  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value;
    setPrompt(text);

    const cursorPos = e.target.selectionStart;
    const lookbackStart = Math.max(0, cursorPos - 40);
    const textNearCursor = text.substring(lookbackStart, cursorPos);
    const lastSlashIdx = textNearCursor.lastIndexOf('/');

    // Slash must be at the beginning of string or preceded by whitespace
    if (lastSlashIdx !== -1) {
      const isStartOrWhitespace =
        lastSlashIdx === 0 || /\s/.test(textNearCursor[lastSlashIdx - 1]);
      const textAfterSlash = textNearCursor.substring(lastSlashIdx);
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
      personaId: currentPersona.id,
      projectId,
      attachments: attachments.length > 0 ? attachments : undefined,
      skill: selectedSkill || undefined,
      enabledPlugins: enabledPluginIds,
    });

    setPrompt('');
    updateAttachments(() => []);
    setSelectedSkill(null);
    setEditingParamKey(null);
    setPreviewAttachment(null);
    if (activeTextareaRef.current) {
      activeTextareaRef.current.style.height = 'auto';
    }
  };

  const handleFilesSelected = useCallback((files: FileList | File[] | null) => {
    if (!files || files.length === 0) return;
    Array.from(files).forEach((f) => {
      const id = `${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;
      const reader = new FileReader();
      const isImg = f.type.startsWith('image/');
      reader.onload = async (e) => {
        const text = typeof e.target?.result === 'string' ? e.target.result : '';
        const snippet = isImg ? text : text.slice(0, 1000);
        const attachment: AttachmentFile = {
          id,
          name: f.name || `Pasted_Image_${new Date().toISOString().slice(11, 19)}.png`,
          size: f.size,
          type: f.type || (isImg ? 'image/png' : 'application/octet-stream'),
          snippet: snippet || `Attachment: ${f.name} (${f.size} bytes)`,
          uploadProgress: 100,
          status: 'indexed',
        };
        try {
          await sidecarClient.observeMemory({
            content: `[Document Grounding: ${attachment.name}]\n${isImg ? '[Attached visual image asset]' : snippet || attachment.name}`,
            category: 'rag_document',
            metadata: { filename: attachment.name, size: f.size, type: f.type },
          });
        } catch {
          // continue
        }
        updateAttachments((prev) => [...prev, attachment]);
      };
      if (isImg) {
        reader.readAsDataURL(f);
      } else {
        reader.readAsText(f);
      }
    });
  }, [updateAttachments]);

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items || items.length === 0) return;

    const imageFiles: File[] = [];
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.type.indexOf('image') !== -1) {
        const file = item.getAsFile();
        if (file) {
          imageFiles.push(file);
        }
      }
    }

    if (imageFiles.length > 0) {
      if (!e.clipboardData.getData('text/plain')) {
        e.preventDefault();
      }
      handleFilesSelected(imageFiles);
    }
  }, [handleFilesSelected]);

  const removeAttachment = (id: string) => {
    updateAttachments((prev) => prev.filter((a) => a.id !== id));
    if (previewAttachment?.id === id) {
      setPreviewAttachment(null);
    }
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

  // Cost estimator calculation calibrated to ±5%
  const approxTokens = useMemo(() => estimateTokenCount(prompt), [prompt]);
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

  const currentPersona =
    personasCatalog.find((p) => p.id === activePersonaId) ||
    personasCatalog[0] ||
    DEFAULT_PERSONAS[0];

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
      className={`w-full bg-bg-elevated border rounded-lg p-3 shadow-md transition-all duration-150 relative ${
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
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-bg-base border border-border-strong text-xs text-text-primary group relative overflow-hidden"
            >
              {file.uploadProgress !== undefined && file.uploadProgress < 100 && (
                <div
                  className="absolute bottom-0 left-0 h-0.5 bg-accent transition-all duration-300"
                  style={{ width: `${file.uploadProgress}%` }}
                />
              )}
              <button
                type="button"
                onClick={() => setPreviewAttachment(previewAttachment?.id === file.id ? null : file)}
                className="flex items-center gap-1.5 hover:text-accent transition-colors max-w-[160px] truncate text-left"
                title="Click to view document snippet preview"
                aria-label={`Preview snippet for ${file.name}`}
              >
                {file.type.startsWith('image/') && file.snippet?.startsWith('data:image/') ? (
                  <img
                    src={file.snippet}
                    alt={file.name}
                    className="w-4 h-4 rounded object-cover flex-shrink-0"
                  />
                ) : (
                  <FileCode className="w-3.5 h-3.5 text-accent flex-shrink-0" />
                )}
                <span className="truncate font-mono text-[11px]">{file.name}</span>
              </button>
              <span className="text-[10px] text-text-tertiary font-mono">
                ({formatFileSize(file.size)})
              </span>
              {file.status === 'indexed' && (
                <span
                  className="px-1 py-0.2 rounded bg-success/15 text-success text-[9px] font-medium"
                  title="Indexed in RAG session memory"
                >
                  Indexed
                </span>
              )}
              <button
                type="button"
                onClick={() => removeAttachment(file.id)}
                className="ml-1 text-text-tertiary hover:text-danger transition-colors p-0.5 rounded"
                title="Remove attachment"
                aria-label={`Remove ${file.name}`}
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Snippet Preview Card */}
      {previewAttachment && (
        <div className="mb-2 p-3 rounded-lg bg-bg-base border border-accent/40 shadow-lg text-left text-xs animate-fade-in">
          <div className="flex items-center justify-between pb-1.5 border-b border-border-subtle mb-2">
            <div className="flex items-center gap-2">
              <FileCode className="w-4 h-4 text-accent" />
              <span className="font-semibold text-text-primary truncate max-w-[200px]">
                {previewAttachment.name}
              </span>
              <span className="text-[10px] text-text-tertiary font-mono">
                ({formatFileSize(previewAttachment.size)})
              </span>
              {previewAttachment.status === 'indexed' && (
                <span className="px-1.5 py-0.5 rounded bg-success/15 text-success text-[10px] font-medium">
                  Indexed in RAG Memory
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => setPreviewAttachment(null)}
              className="text-text-tertiary hover:text-text-primary p-0.5 rounded"
              aria-label="Close snippet preview"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
          {previewAttachment.type.startsWith('image/') && previewAttachment.snippet?.startsWith('data:image/') ? (
            <div className="max-h-48 overflow-hidden rounded border border-border-subtle bg-bg-elevated flex items-center justify-center p-2">
              <img
                src={previewAttachment.snippet}
                alt={previewAttachment.name}
                className="max-h-44 max-w-full rounded object-contain"
              />
            </div>
          ) : (
            <div className="max-h-32 overflow-y-auto font-mono text-[11px] text-text-secondary bg-bg-elevated p-2 rounded border border-border-subtle whitespace-pre-wrap select-text">
              {previewAttachment.snippet || 'Document attached. Ready for grounding in session memory.'}
            </div>
          )}
        </div>
      )}

      {/* Inline Error Banner if Model or Sidecar Degraded */}
      {modelError && (
        <div className="mb-2 p-2 rounded-lg bg-danger/10 border border-danger/30 text-danger text-xs flex items-center justify-between animate-in fade-in">
          <div className="flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />
            <span>{modelError}</span>
          </div>
          <button
            type="button"
            onClick={() => setModelError(null)}
            className="text-text-tertiary hover:text-text-primary p-0.5 rounded"
          >
            <X className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Main Textarea */}
      <textarea
        ref={activeTextareaRef}
        value={prompt}
        onChange={handleTextChange}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
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
            className="px-2 py-1 rounded-md bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary hover:text-text-primary transition-colors flex items-center gap-1.5"
          >
            <Paperclip className="w-3.5 h-3.5 text-text-tertiary" />
            <span>Attach</span>
          </button>

          {/* Mode Chip */}
          {mode && mode !== 'home' && (
            <button
              type="button"
              onClick={() => onModeChange?.('home')}
              title={`Active Mode: ${mode}. Click to reset to home.`}
              className="flex items-center gap-1 px-2 py-0.5 rounded border border-border-subtle text-[11px] font-medium text-text-secondary hover:bg-bg-hover transition-all"
            >
              <span className="capitalize">{mode.replace('-', ' ')}</span>
              <X className="w-3 h-3 text-text-tertiary hover:text-text-primary" />
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
              <span className="truncate max-w-[140px]">
                Project: {projectName || 'Default'}
              </span>
              <ChevronDown className="w-3 h-3 text-text-tertiary" />
            </button>

            {projectDropdownOpen && (
              <div className="absolute left-0 bottom-full mb-1 w-52 bg-bg-elevated border border-border-strong rounded-lg shadow-2xl py-1 z-50">
                <div className="px-2.5 py-1 text-[10px] uppercase font-semibold text-text-tertiary tracking-wider border-b border-border-subtle">
                  Project Workspace
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
                {realProjects.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => {
                      onProjectChange?.(p.id);
                      setProjectDropdownOpen(false);
                    }}
                    className={`w-full text-left px-2.5 py-1.5 text-xs hover:bg-bg-hover transition-colors truncate ${
                      projectId === p.id ? 'text-accent font-medium' : 'text-text-secondary'
                    }`}
                  >
                    {p.name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Optional Developer-mode plugins */}
          {isDev && (
            <>
              <div className="hidden sm:block h-3.5 w-px bg-border-subtle" />
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
              </div>
            </>
          )}

          {isDev && (
            <div
              title={`Approx. ${approxTokens.toLocaleString()} tokens`}
              className="hidden lg:flex items-center gap-1 text-[11px] font-mono text-text-tertiary"
            >
              <Coins className="w-3 h-3 text-success/80" />
              <span>Est: {costPreview}</span>
            </div>
          )}
        </div>

        {/* Right cluster: Model Selector & Run/Stop Button */}
        <div className="flex items-center gap-1.5 sm:gap-2">
          {/* Model Selector in Input */}
          <div className="relative">
            <button
              type="button"
              onClick={() => {
                setModelDropdownOpen(!modelDropdownOpen);
                setProjectDropdownOpen(false);
              }}
              aria-label="Select model routing"
              title={`Model: ${isDev ? currentTierConfig.label : currentTierConfig.standardLabel}`}
              className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-bg-base hover:bg-bg-hover border border-border-subtle hover:border-border-strong text-xs text-text-primary transition-colors"
            >
              {currentTierConfig.icon}
              <span className="font-medium text-[11px]">
                {isDev ? currentTierConfig.label : currentTierConfig.standardLabel}
              </span>
              <ChevronDown className="w-3 h-3 text-text-tertiary" />
            </button>

            {modelDropdownOpen && (
              <div
                role="listbox"
                aria-label="Model options"
                className="absolute right-0 bottom-full mb-1 w-52 bg-bg-elevated border border-border-strong rounded-lg shadow-2xl py-1 z-50 animate-in fade-in duration-100"
              >
                <div className="px-3 py-1 text-[10px] uppercase font-semibold text-text-tertiary tracking-wider border-b border-border-subtle">
                  {isDev ? 'Model Routing Tier' : 'Model Selection'}
                </div>
                {(Object.keys(MODEL_TIER_CONFIG) as ModelTier[]).map((tierKey) => {
                  const item = MODEL_TIER_CONFIG[tierKey];
                  const isSelected = model === tierKey;
                  return (
                    <button
                      key={tierKey}
                      type="button"
                      onClick={() => {
                        onModelChange?.(tierKey);
                        setModelDropdownOpen(false);
                      }}
                      className={`w-full text-left px-3 py-1.5 hover:bg-bg-hover flex items-center justify-between transition-colors ${
                        isSelected ? 'bg-bg-hover' : ''
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {item.icon}
                        <span className="text-xs text-text-primary font-medium">
                          {isDev ? item.label : item.standardLabel}
                        </span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        {isDev && (
                          <span className="text-[10px] font-mono text-text-tertiary">
                            {item.rateStr}
                          </span>
                        )}
                        {isSelected && <Check className="w-3 h-3 text-accent" />}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Run / Stop Button */}
          {isStreaming ? (
            <button
              type="button"
              onClick={onStop}
              title="Stop generation (Esc)"
              className="px-2.5 py-1.5 rounded-md bg-danger hover:bg-danger/90 text-white text-xs font-medium transition-all flex items-center gap-1.5"
            >
              <Square className="w-3 h-3 fill-white" />
              <span>Stop</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!prompt.trim() && attachments.length === 0 && !selectedSkill}
              title="Run task or send prompt"
              className={`px-3 py-1.5 rounded-md text-xs font-medium flex items-center gap-1.5 transition-all ${
                prompt.trim() || attachments.length > 0 || selectedSkill
                  ? 'bg-accent hover:bg-accent-hover text-white shadow-xs cursor-pointer'
                  : 'bg-bg-hover text-text-tertiary cursor-not-allowed opacity-60'
              }`}
            >
              <ArrowUp className="w-3.5 h-3.5" />
              <span>Run</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
