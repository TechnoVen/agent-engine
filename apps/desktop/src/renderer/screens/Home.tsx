import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Sparkles,
  Zap,
  GitBranch,
  Search,
  FileText,
  Table2,
  Network,
  Code2,
  Layers,
  RotateCcw,
  ArrowRight,
  FolderKanban,
} from 'lucide-react';
import { Mode, ModelTier, ChatMessage, AttachmentFile } from '../types';
import { ChatInput } from '../components/ChatInput';
import { Message } from '../components/Message';

export interface HomeProps {
  onSelectMode: (mode: Mode) => void;
  activeModel: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
  initialMessages?: ChatMessage[];
}

interface FeaturedCase {
  title: string;
  category: string;
  description: string;
  mode: Mode;
  icon: React.ReactNode;
  estCost: string;
  prompt: string;
}

export const Home: React.FC<HomeProps> = ({
  onSelectMode,
  activeModel,
  onSelectModel,
  inputRef: externalInputRef,
  initialMessages = [],
}) => {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeProjectId, setActiveProjectId] = useState<string>('');
  const [activeProjectName, setActiveProjectName] = useState<string>('');
  const [initialInputText, setInitialInputText] = useState('');

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const internalInputRef = useRef<HTMLTextAreaElement>(null);
  const activeInputRef = externalInputRef || internalInputRef;
  const streamAbortController = useRef<{ aborted: boolean }>({ aborted: false });

  // Auto-scroll when messages change or stream updates
  useEffect(() => {
    if (messages.length > 0) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isStreaming]);

  // Greeting based on time of day
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

  const featuredCases: FeaturedCase[] = [
    {
      title: 'Build an invoice agent',
      category: 'Business Pipeline',
      description: 'Extract line items from PDF invoices and validate calculations with 0-token deterministic code.',
      mode: 'workflows',
      icon: <Layers className="w-4 h-4 text-accent" />,
      estCost: '$0.00 (CODE Tier)',
      prompt: 'Build an invoice validation workflow that extracts line items from incoming PDFs, verifies tax arithmetic via Python, and flags discrepancies > 1% to Slack.',
    },
    {
      title: 'Analyze codebase & architecture',
      category: 'Developer Case',
      description: 'Generate comprehensive AST component graphs and detect dead dependencies across projects.',
      mode: 'code',
      icon: <Code2 className="w-4 h-4 text-warning" />,
      estCost: '$0.001 (Small Model)',
      prompt: 'Inspect the current codebase architecture, map inter-module dependencies across services, and suggest optimizations for deterministic execution.',
    },
    {
      title: 'Deep market research report',
      category: 'Investigative Case',
      description: 'Synthesize 40+ market source documents into an executive summary with verified source citations.',
      mode: 'deep-research',
      icon: <Search className="w-4 h-4 text-success" />,
      estCost: '$0.004 (Mid Model)',
      prompt: 'Draft an in-depth research report comparing local-first AI engine architectures against cloud-centric platforms, highlighting latency, cost, and data sovereignty.',
    },
  ];

  const recentProjects = [
    { id: '1', name: 'Organiser Workspace', threads: 8, updated: '2h ago' },
    { id: '2', name: 'Client Website Redesign', threads: 3, updated: '1d ago' },
  ];

  // 60fps streaming token dispatcher
  const startStreamingResponse = useCallback(
    (promptText: string, model: ModelTier) => {
      setIsStreaming(true);
      streamAbortController.current = { aborted: false };

      const assistantMsgId = `msg-${Date.now()}`;
      const startTime = performance.now();

      // Placeholder assistant message
      setMessages((prev) => [
        ...prev,
        {
          id: assistantMsgId,
          role: 'assistant',
          content: '',
          timestamp: 'Just now',
          isStreaming: true,
          metadata: {
            modelTier: model,
            latencyMs: 0,
            tokenCount: 0,
            tokensPerSec: 0,
            estCost: model === 'instant' ? '$0.0001' : model === 'swarm' ? '$0.0008' : '$0.0032',
          },
        },
      ]);

      // Sample generation tokens crafted for local-first agent engine
      const responseStreamText = `I have analyzed your request: "${promptText}".

### Execution Plan (90/9/1 Cost Optimized)
1. **Deterministic Rule Check (CODE Tier):**
   - Verified zero syntax conflicts and validated input structure.
   - Evaluated semantic cache; 0 frontier tokens expended.

2. **Core Pipeline Execution:**
   - Active Model Tier: **${model.toUpperCase()}**
   - Workspace Context: **${activeProjectName || 'Global Scratchpad'}**
   - Multi-agent coordinator dispatched sub-tasks to local runners.

\`\`\`python
# Agent Engine Execution Spec
def execute_agent_task(prompt: str, tier: str) -> dict:
    \"\"\"Local-first deterministic dispatcher\"\"\"
    return {
        "status": "completed",
        "tier": tier,
        "latency_overhead_ms": 14.2,
        "cache_hit": True
    }
\`\`\`

All constraints satisfied. Ready for your follow-up command!`;

      // 60fps token streaming loop via requestAnimationFrame
      const tokens = responseStreamText.split(/(\s+|\n+)/);
      let currentIdx = 0;
      let accumulated = '';
      let lastFrameTime = performance.now();
      const tokensPerFrame = 2; // Smooth 60fps chunk pacing (~60-90 tokens/sec)

      const streamStep = (now: number) => {
        if (streamAbortController.current.aborted) {
          setIsStreaming(false);
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantMsgId ? { ...m, isStreaming: false } : m))
          );
          return;
        }

        // Emit tokens at 60fps interval (~16.6ms per frame)
        if (now - lastFrameTime >= 16) {
          const nextIdx = Math.min(currentIdx + tokensPerFrame, tokens.length);
          for (let i = currentIdx; i < nextIdx; i++) {
            accumulated += tokens[i];
          }
          currentIdx = nextIdx;
          lastFrameTime = now;

          const elapsedSec = Math.max((now - startTime) / 1000, 0.05);
          const currentTokenCount = Math.ceil(accumulated.length / 4);
          const tps = Math.round(currentTokenCount / elapsedSec);

          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    content: accumulated,
                    metadata: {
                      ...m.metadata,
                      tokenCount: currentTokenCount,
                      tokensPerSec: tps,
                      latencyMs: Math.round(now - startTime),
                    },
                  }
                : m
            )
          );
        }

        if (currentIdx < tokens.length) {
          requestAnimationFrame(streamStep);
        } else {
          // Completed
          setIsStreaming(false);
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantMsgId ? { ...m, isStreaming: false } : m))
          );
        }
      };

      requestAnimationFrame(streamStep);
    },
    [activeProjectName]
  );

  const handleSend = (
    text: string,
    options?: { model: ModelTier; projectId?: string; attachments?: AttachmentFile[] }
  ) => {
    if (!text.trim() && (!options?.attachments || options.attachments.length === 0)) return;

    const userMsg: ChatMessage = {
      id: `usr-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: 'Just now',
      attachments: options?.attachments,
    };

    setMessages((prev) => [...prev, userMsg]);
    setInitialInputText('');

    const targetModel = options?.model || activeModel;
    startStreamingResponse(text, targetModel);
  };

  const handleStop = () => {
    streamAbortController.current.aborted = true;
    setIsStreaming(false);
  };

  const handleSelectFeaturedCase = (c: FeaturedCase) => {
    setInitialInputText(c.prompt);
    if (c.mode !== 'home') {
      onSelectMode(c.mode);
    }
    activeInputRef.current?.focus();
  };

  const handleProjectSelect = (id: string) => {
    setActiveProjectId(id);
    const found = recentProjects.find((p) => p.id === id);
    setActiveProjectName(found ? found.name : '');
  };

  const handleResetChat = () => {
    if (isStreaming) {
      handleStop();
    }
    setMessages([]);
    setInitialInputText('');
    activeInputRef.current?.focus();
  };

  const isChatActive = messages.length > 0;

  return (
    <div className="h-full flex flex-col justify-between overflow-hidden relative">
      {/* Top action bar when chat is active */}
      {isChatActive && (
        <div className="h-10 border-b border-border-subtle bg-bg-elevated/40 px-4 flex items-center justify-between text-xs text-text-tertiary select-none">
          <div className="flex items-center gap-2">
            <span className="font-medium text-text-secondary">Current Thread</span>
            <span>•</span>
            <span className="font-mono text-[11px]">{messages.length} messages</span>
          </div>
          <button
            type="button"
            onClick={handleResetChat}
            className="flex items-center gap-1.5 px-2 py-1 rounded hover:bg-bg-hover text-text-tertiary hover:text-text-primary transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            <span>New Chat</span>
          </button>
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-6 scrollbar-thin">
        {!isChatActive ? (
          /* Empty State Canvas */
          <div className="w-full max-w-[760px] mx-auto flex flex-col items-center text-center space-y-6 my-auto pt-4 md:pt-8">
            {/* Logo and Greeting */}
            <div className="space-y-2">
              <div className="inline-flex items-center justify-center w-12 h-12 rounded-xl bg-bg-elevated border border-border-strong shadow-lg mb-2">
                <Sparkles className="w-6 h-6 text-accent" />
              </div>
              <h2 className="text-2xl font-bold tracking-tight text-text-primary">
                {getGreeting()}
              </h2>
              <p className="text-sm text-text-secondary max-w-lg leading-relaxed">
                Collaborate with your local-first multi-agent engine. 90% code & cache, 9% small models, 1% frontier.
              </p>
            </div>

            {/* Universal ChatInput Box */}
            <div className="w-full">
              <ChatInput
                mode="home"
                model={activeModel}
                projectId={activeProjectId}
                projectName={activeProjectName}
                isStreaming={isStreaming}
                onSend={handleSend}
                onStop={handleStop}
                onModeChange={onSelectMode}
                onModelChange={onSelectModel}
                onProjectChange={handleProjectSelect}
                inputRef={activeInputRef}
                initialValue={initialInputText}
              />
            </div>

            {/* Quick Action Chips */}
            <div className="flex flex-wrap items-center justify-center gap-2 pt-1">
              {actionChips.map((chip) => (
                <button
                  key={chip.mode}
                  type="button"
                  onClick={() => onSelectMode(chip.mode)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-bg-elevated hover:bg-bg-hover border border-border-subtle hover:border-border-strong text-xs text-text-secondary hover:text-text-primary transition-all"
                >
                  {chip.icon}
                  <span>{chip.label}</span>
                </button>
              ))}
            </div>

            {/* Featured Inspiration Cards Grid */}
            <div className="w-full pt-4 space-y-3 text-left">
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
                    onClick={() => handleSelectFeaturedCase(item)}
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
                      <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition-transform text-accent" />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Recent Workspaces Row */}
            <div className="w-full pt-2 text-left space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-text-tertiary px-1 flex items-center gap-1.5">
                <FolderKanban className="w-3.5 h-3.5" />
                <span>Recent Workspaces</span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {recentProjects.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => handleProjectSelect(p.id)}
                    className={`p-2.5 rounded-lg border text-left flex items-center justify-between transition-all ${
                      activeProjectId === p.id
                        ? 'bg-accent/10 border-accent text-text-primary'
                        : 'bg-bg-elevated border-border-subtle hover:border-border-strong text-text-secondary hover:text-text-primary'
                    }`}
                  >
                    <div>
                      <div className="text-xs font-medium">{p.name}</div>
                      <div className="text-[10px] text-text-tertiary font-mono">
                        {p.threads} active threads • Updated {p.updated}
                      </div>
                    </div>
                    <span className="text-xs font-mono text-text-tertiary">
                      {activeProjectId === p.id ? 'Active' : 'Select'}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          /* Active Chat Thread */
          <div className="w-full max-w-[760px] mx-auto space-y-4 pb-2">
            {messages.map((msg) => (
              <Message key={msg.id} message={msg} />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Persistent Bottom ChatInput during active conversation */}
      {isChatActive && (
        <div className="border-t border-border-subtle bg-bg-base/95 backdrop-blur-md px-4 py-3">
          <div className="w-full max-w-[760px] mx-auto">
            <ChatInput
              mode="home"
              model={activeModel}
              projectId={activeProjectId}
              projectName={activeProjectName}
              isStreaming={isStreaming}
              onSend={handleSend}
              onStop={handleStop}
              onModeChange={onSelectMode}
              onModelChange={onSelectModel}
              onProjectChange={handleProjectSelect}
              inputRef={activeInputRef}
            />
          </div>
        </div>
      )}

      {/* Footer shortcut hint on empty state */}
      {!isChatActive && (
        <div className="pb-4 text-center text-[11px] text-text-tertiary select-none">
          Press{' '}
          <kbd className="px-1.5 py-0.5 rounded bg-bg-elevated border border-border-strong text-text-secondary font-mono">
            Ctrl+K
          </kbd>{' '}
          to focus input anywhere
        </div>
      )}
    </div>
  );
};
