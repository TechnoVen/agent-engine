import React, { useEffect, useRef } from 'react';
import {
  Code2,
  Database,
  FileCheck,
  GraduationCap,
  FileText,
  Workflow,
  Sparkles,
  Bot,
  Zap,
  Globe,
  Brain,
  Terminal,
  Eraser,
  Sliders,
} from 'lucide-react';
import { SkillItem } from '../types';

export interface SlashCommandItem {
  id: string;
  command: string;
  name: string;
  description: string;
  category: 'Skill' | 'Command' | 'Plugin';
  icon: React.ReactNode;
  inputs?: string[];
  action?: () => void;
  skill?: SkillItem;
}

export interface SlashCommandPopupProps {
  query: string;
  skills: SkillItem[];
  selectedIndex: number;
  onSelect: (item: SlashCommandItem) => void;
  onClose: () => void;
  className?: string;
}

export const BUILT_IN_COMMANDS: SlashCommandItem[] = [
  {
    id: 'cmd-skill',
    command: '/skill',
    name: 'Invoke Skill Template',
    description: 'Select and auto-fill an OpenClaw template with parameter chips',
    category: 'Command',
    icon: <Sparkles className="w-4 h-4 text-accent" />,
    inputs: ['skill_name'],
  },
  {
    id: 'cmd-agent',
    command: '/agent',
    name: 'Switch Agent Persona',
    description: 'Change the primary agent specialist (Architect, Coder, Reviewer)',
    category: 'Command',
    icon: <Bot className="w-4 h-4 text-warning" />,
    inputs: ['persona'],
  },
  {
    id: 'cmd-workflow',
    command: '/workflow',
    name: 'Run Graph Workflow',
    description: 'Execute a pre-configured multi-step deterministic DAG pipeline',
    category: 'Command',
    icon: <Workflow className="w-4 h-4 text-success" />,
    inputs: ['workflow_id'],
  },
  {
    id: 'cmd-mode',
    command: '/mode',
    name: 'Switch Capability Mode',
    description: 'Transition workspace to Code, Deep Research, Sheets, or Slides',
    category: 'Command',
    icon: <Sliders className="w-4 h-4 text-accent" />,
    inputs: ['mode_name'],
  },
  {
    id: 'cmd-clear',
    command: '/clear',
    name: 'Clear Chat Canvas',
    description: 'Reset active conversation and return to clean empty state',
    category: 'Command',
    icon: <Eraser className="w-4 h-4 text-danger" />,
  },
  {
    id: 'plug-web',
    command: '/web-search',
    name: 'Toggle Web Search Grounding',
    description: 'Enable live web retrieval and citation synthesis',
    category: 'Plugin',
    icon: <Globe className="w-4 h-4 text-accent" />,
  },
  {
    id: 'plug-memory',
    command: '/memory',
    name: 'Query Observational Memory',
    description: 'Search long-term semantic knowledge and preferences',
    category: 'Plugin',
    icon: <Brain className="w-4 h-4 text-success" />,
    inputs: ['query'],
  },
  {
    id: 'plug-sandbox',
    command: '/sandbox',
    name: 'Deterministic Python Sandbox',
    description: 'Run Python code in local AST-verified zero-token environment',
    category: 'Plugin',
    icon: <Terminal className="w-4 h-4 text-warning" />,
    inputs: ['code'],
  },
];

const getSkillIcon = (category: string) => {
  switch (category.toLowerCase()) {
    case 'engineering':
      return <Code2 className="w-4 h-4 text-accent" />;
    case 'database':
      return <Database className="w-4 h-4 text-warning" />;
    case 'productivity':
      return <FileCheck className="w-4 h-4 text-success" />;
    case 'education':
      return <GraduationCap className="w-4 h-4 text-accent" />;
    case 'communication':
      return <FileText className="w-4 h-4 text-text-secondary" />;
    default:
      return <Zap className="w-4 h-4 text-accent" />;
  }
};

export const SlashCommandPopup: React.FC<SlashCommandPopupProps> = ({
  query,
  skills,
  selectedIndex,
  onSelect,
  className = '',
}) => {
  const listRef = useRef<HTMLDivElement>(null);

  // Convert skills into SlashCommandItems
  const skillCommands: SlashCommandItem[] = skills.map((s) => ({
    id: `skill-${s.id}`,
    command: s.command.startsWith('/') ? s.command : `/${s.command}`,
    name: s.name,
    description: s.description,
    category: 'Skill',
    icon: getSkillIcon(s.category),
    inputs: s.inputs,
    skill: s,
  }));

  const allItems = [...skillCommands, ...BUILT_IN_COMMANDS];

  // Clean query text: remove leading '/' and trim
  const cleanQuery = query.replace(/^\//, '').toLowerCase().trim();

  // Fuzzy filter
  const filteredItems = allItems.filter((item) => {
    if (!cleanQuery) return true;
    const matchCmd = item.command.toLowerCase().includes(cleanQuery);
    const matchName = item.name.toLowerCase().includes(cleanQuery);
    const matchDesc = item.description.toLowerCase().includes(cleanQuery);
    const matchCat = item.category.toLowerCase().includes(cleanQuery);
    return matchCmd || matchName || matchDesc || matchCat;
  });

  // Ensure selected item scrolls into view
  useEffect(() => {
    if (!listRef.current) return;
    const selectedEl = listRef.current.children[selectedIndex] as HTMLElement;
    if (selectedEl) {
      selectedEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [selectedIndex]);

  if (filteredItems.length === 0) {
    return (
      <div
        className={`absolute bottom-full left-0 mb-2 w-full max-w-md bg-bg-elevated border border-border-strong rounded-xl shadow-2xl p-3 text-xs text-text-tertiary z-50 ${className}`}
      >
        <span className="font-mono">No matching skills or commands for &ldquo;/{cleanQuery}&rdquo;</span>
      </div>
    );
  }

  return (
    <div
      className={`absolute bottom-full left-0 mb-2 w-full max-w-lg bg-bg-elevated border border-border-strong rounded-xl shadow-2xl overflow-hidden z-50 select-none animate-in fade-in duration-100 ${className}`}
    >
      {/* Header bar */}
      <div className="px-3 py-2 bg-bg-base/80 border-b border-border-subtle flex items-center justify-between text-[10px] uppercase font-semibold text-text-tertiary tracking-wider">
        <span>Skills & Slash Commands ({filteredItems.length})</span>
        <div className="flex items-center gap-2">
          <span><kbd className="px-1 py-0.5 rounded bg-bg-elevated border border-border-subtle">↑</kbd> <kbd className="px-1 py-0.5 rounded bg-bg-elevated border border-border-subtle">↓</kbd> navigate</span>
          <span><kbd className="px-1 py-0.5 rounded bg-bg-elevated border border-border-subtle">Enter</kbd> select</span>
          <span><kbd className="px-1 py-0.5 rounded bg-bg-elevated border border-border-subtle">Esc</kbd> dismiss</span>
        </div>
      </div>

      {/* Item List */}
      <div
        ref={listRef}
        className="max-h-72 overflow-y-auto p-1.5 space-y-1 scrollbar-thin"
      >
        {filteredItems.map((item, idx) => {
          const isSelected = idx === selectedIndex;
          return (
            <div
              key={item.id}
              onClick={() => onSelect(item)}
              className={`px-3 py-2 rounded-lg cursor-pointer flex items-start justify-between gap-3 transition-colors ${
                isSelected
                  ? 'bg-accent/15 border border-accent/40 text-text-primary'
                  : 'hover:bg-bg-hover text-text-secondary border border-transparent'
              }`}
            >
              <div className="flex items-start gap-2.5 min-w-0">
                <div className="mt-0.5 p-1 rounded-md bg-bg-base border border-border-subtle flex-shrink-0">
                  {item.icon}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold text-accent">
                      {item.command}
                    </span>
                    <span className="text-xs font-medium text-text-primary truncate">
                      {item.name}
                    </span>
                    <span
                      className={`text-[9px] uppercase font-mono px-1.5 py-0.5 rounded ${
                        item.category === 'Skill'
                          ? 'bg-accent/10 text-accent border border-accent/20'
                          : item.category === 'Command'
                          ? 'bg-warning/10 text-warning border border-warning/20'
                          : 'bg-success/10 text-success border border-success/20'
                      }`}
                    >
                      {item.category}
                    </span>
                  </div>
                  <p className="text-[11px] text-text-tertiary mt-0.5 line-clamp-1">
                    {item.description}
                  </p>
                </div>
              </div>

              {/* Parameter preview chips */}
              {item.inputs && item.inputs.length > 0 && (
                <div className="hidden sm:flex items-center gap-1 flex-shrink-0 mt-0.5">
                  {item.inputs.slice(0, 2).map((inp) => (
                    <span
                      key={inp}
                      className="px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-[10px] font-mono text-text-tertiary"
                    >
                      [{inp}]
                    </span>
                  ))}
                  {item.inputs.length > 2 && (
                    <span className="text-[10px] font-mono text-text-tertiary">
                      +{item.inputs.length - 2}
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
