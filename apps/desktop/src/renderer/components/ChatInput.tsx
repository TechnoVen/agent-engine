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
} from 'lucide-react';
import { Mode, ModelTier, AttachmentFile } from '../types';

export interface ChatInputProps {
  mode?: Mode;
  placeholder?: string;
  model: ModelTier;
  projectId?: string;
  projectName?: string;
  isStreaming?: boolean;
  onSend: (message: string, options?: { model: ModelTier; projectId?: string; attachments?: AttachmentFile[] }) => void;
  onStop?: () => void;
  onModeChange?: (mode: Mode) => void;
  onModelChange?: (model: ModelTier) => void;
  onProjectChange?: (projectId: string) => void;
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
  inputRef: externalInputRef,
  initialValue = '',
  className = '',
}) => {
  const [prompt, setPrompt] = useState(initialValue);
  const [attachments, setAttachments] = useState<AttachmentFile[]>([]);
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const [projectDropdownOpen, setProjectDropdownOpen] = useState(false);
  const [isDragOver, setIsDragOver] = useState(false);

  const internalInputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeTextareaRef = externalInputRef || internalInputRef;

  // Auto-sync initialValue if provided or changed externally
  useEffect(() => {
    if (initialValue && initialValue !== prompt) {
      setPrompt(initialValue);
      adjustHeight();
    }
  }, [initialValue]);

  // Adjust textarea height dynamically to content
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

  // Calculate pre-execution token and cost estimate
  const approxTokens = Math.max(1, Math.ceil(prompt.trim().length / 4));
  const currentTierConfig = MODEL_TIER_CONFIG[model] || MODEL_TIER_CONFIG.instant;
  const rawCost = (approxTokens / 1000) * currentTierConfig.ratePer1k;
  const costPreview =
    prompt.trim().length === 0
      ? '$0.00 (Cache/Code)'
      : rawCost < 0.0001
      ? '<$0.0001 (CODE Tier)'
      : `$${rawCost.toFixed(4)}`;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
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
    if (!cleanText && attachments.length === 0) return;

    onSend(cleanText, {
      model,
      projectId,
      attachments: attachments.length > 0 ? attachments : undefined,
    });

    setPrompt('');
    setAttachments([]);
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

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const currentPlaceholder =
    placeholder || MODE_PLACEHOLDERS[mode] || MODE_PLACEHOLDERS.home;

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
      {/* Attachment Chips row */}
      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-2 pb-2 mb-2 border-b border-border-subtle">
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
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={currentPlaceholder}
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
        {/* Left cluster: Attachments, Mode Chip, Project Selector */}
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

          {/* Pre-execution Cost Estimate */}
          <div
            title={`Approx. ${approxTokens} tokens on ${currentTierConfig.label}`}
            className="hidden sm:flex items-center gap-1 text-[11px] font-mono text-text-tertiary"
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
              disabled={!prompt.trim() && attachments.length === 0}
              title={
                !prompt.trim() && attachments.length === 0
                  ? 'Enter a prompt or attach files'
                  : 'Send message (Enter)'
              }
              className={`p-2 rounded-lg flex items-center justify-center transition-all ${
                prompt.trim() || attachments.length > 0
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
