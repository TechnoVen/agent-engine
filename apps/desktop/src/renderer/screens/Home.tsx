import React, { useState, useRef, useEffect } from 'react';
import {
  ArrowUp,
  Paperclip,
  Folder,
  Sparkles,
  Zap,
  GitBranch,
  Search,
  FileText,
  Table2,
  Network,
  Code2,
  Layers,
  CheckCircle2,
} from 'lucide-react';
import { Mode, ModelTier } from '../types';

interface HomeProps {
  onSelectMode: (mode: Mode) => void;
  activeModel?: ModelTier;
}

export const Home: React.FC<HomeProps> = ({ onSelectMode, activeModel: _activeModel }) => {
  const [prompt, setPrompt] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // Focus textarea on mount
    textareaRef.current?.focus();
  }, []);

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning, Nadir';
    if (hour < 18) return 'Good afternoon, Nadir';
    return 'Good evening, Nadir';
  };

  const actionChips = [
    { mode: 'swarm' as Mode, label: 'Swarm', icon: <Zap className="w-3.5 h-3.5 text-warning" /> },
    { mode: 'workflows' as Mode, label: 'Workflows', icon: <GitBranch className="w-3.5 h-3.5 text-text-secondary" /> },
    { mode: 'deep-research' as Mode, label: 'Deep Research', icon: <Search className="w-3.5 h-3.5 text-accent" /> },
    { mode: 'docs' as Mode, label: 'Docs', icon: <FileText className="w-3.5 h-3.5 text-text-secondary" /> },
    { mode: 'sheets' as Mode, label: 'Sheets', icon: <Table2 className="w-3.5 h-3.5 text-success" /> },
    { mode: 'diagrams' as Mode, label: 'Diagrams', icon: <Network className="w-3.5 h-3.5 text-text-secondary" /> },
    { mode: 'code' as Mode, label: 'Code', icon: <Code2 className="w-3.5 h-3.5 text-text-secondary" /> },
  ];

  const featuredCases = [
    {
      title: 'Build an invoice agent',
      category: 'Business Pipeline',
      description: 'Extract line items from PDF invoices and validate calculations with 0-token deterministic code.',
      mode: 'workflows' as Mode,
      icon: <Layers className="w-5 h-5 text-accent" />,
      estCost: '$0.00 (CODE Tier)',
    },
    {
      title: 'Analyze codebase & architecture',
      category: 'Developer Case',
      description: 'Generate comprehensive AST component graphs and detect dead dependencies across projects.',
      mode: 'code' as Mode,
      icon: <Code2 className="w-5 h-5 text-warning" />,
      estCost: '$0.001 (Small Model)',
    },
    {
      title: 'Deep market research report',
      category: 'Investigative Case',
      description: 'Synthesize 40+ market source documents into an executive summary with verified source citations.',
      mode: 'deep-research' as Mode,
      icon: <Search className="w-5 h-5 text-success" />,
      estCost: '$0.004 (Mid Model)',
    },
  ];

  return (
    <div className="h-full overflow-y-auto px-6 py-8 flex flex-col items-center justify-between">
      <div className="w-full max-w-[760px] flex flex-col items-center text-center space-y-6 my-auto">
        {/* Logo and Greeting */}
        <div className="space-y-2">
          <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-bg-elevated border border-border-strong shadow-lg mb-2">
            <Sparkles className="w-6 h-6 text-accent" />
          </div>
          <h2 className="text-2xl font-bold tracking-tight text-text-primary">
            {getGreeting()}
          </h2>
          <p className="text-sm text-text-secondary">
            Collaborate with your local-first multi-agent engine. 90% code & cache, 9% small models, 1% frontier.
          </p>
        </div>

        {/* Universal ChatInput Box */}
        <div className="w-full bg-bg-elevated border border-border-strong rounded-xl p-3 shadow-2xl focus-within:border-accent transition-all text-left">
          <textarea
            ref={textareaRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Type '/' to invoke plugins and skills, or ask anything..."
            rows={3}
            className="w-full bg-transparent resize-none outline-none text-sm text-text-primary placeholder:text-text-tertiary"
          />

          {/* Input Actions Bar */}
          <div className="pt-2 border-t border-border-subtle flex items-center justify-between">
            <div className="flex items-center gap-2">
              <button
                type="button"
                title="Attach file"
                className="p-1.5 rounded-md hover:bg-bg-hover text-text-tertiary hover:text-text-primary transition-colors"
              >
                <Paperclip className="w-4 h-4" />
              </button>
              <button
                type="button"
                className="flex items-center gap-1 px-2 py-1 rounded-md bg-bg-base border border-border-subtle text-xs text-text-secondary hover:text-text-primary"
              >
                <Folder className="w-3.5 h-3.5 text-text-tertiary" />
                <span>Select project</span>
              </button>
              <div className="h-3 w-px bg-border-subtle" />
              <span className="text-[11px] font-mono text-text-tertiary flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3 text-success" />
                Est. Cost: $0.00 (Cache / Code)
              </span>
            </div>

            <button
              disabled={!prompt.trim()}
              className={`p-2 rounded-lg flex items-center justify-center transition-all ${
                prompt.trim()
                  ? 'bg-accent hover:bg-accent-hover text-white shadow-md'
                  : 'bg-bg-hover text-text-tertiary cursor-not-allowed'
              }`}
            >
              <ArrowUp className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Quick Action Chips */}
        <div className="flex flex-wrap items-center justify-center gap-2 pt-2">
          {actionChips.map((chip) => (
            <button
              key={chip.mode}
              onClick={() => onSelectMode(chip.mode)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-bg-elevated hover:bg-bg-hover border border-border-subtle hover:border-border-strong text-xs text-text-secondary hover:text-text-primary transition-all"
            >
              {chip.icon}
              <span>{chip.label}</span>
            </button>
          ))}
        </div>

        {/* Featured Inspiration Cards */}
        <div className="w-full pt-6 space-y-3 text-left">
          <div className="flex items-center justify-between px-1">
            <span className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">
              Explore Inspiration
            </span>
            <span className="text-xs text-accent hover:underline cursor-pointer">
              View all templates
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {featuredCases.map((item, idx) => (
              <div
                key={idx}
                onClick={() => onSelectMode(item.mode)}
                className="p-3.5 rounded-xl bg-bg-elevated hover:bg-bg-hover border border-border-subtle hover:border-border-strong cursor-pointer transition-all group flex flex-col justify-between"
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono text-text-tertiary uppercase">
                      {item.category}
                    </span>
                    {item.icon}
                  </div>
                  <h3 className="text-xs font-semibold text-text-primary group-hover:text-accent transition-colors">
                    {item.title}
                  </h3>
                  <p className="text-[11px] text-text-secondary leading-relaxed line-clamp-2">
                    {item.description}
                  </p>
                </div>
                <div className="pt-3 mt-2 border-t border-border-subtle/50 flex items-center justify-between text-[10px] font-mono text-text-tertiary">
                  <span>{item.estCost}</span>
                  <span className="group-hover:translate-x-0.5 transition-transform text-accent">→</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Footer hint */}
      <div className="text-[11px] text-text-tertiary">
        Press <kbd className="px-1 py-0.5 rounded bg-bg-elevated border border-border-strong text-text-secondary font-mono">Ctrl+K</kbd> to focus input anywhere
      </div>
    </div>
  );
};
