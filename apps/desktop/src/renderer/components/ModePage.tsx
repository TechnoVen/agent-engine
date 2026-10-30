import React, { useState, useMemo, useRef, useCallback } from 'react';
import { RotateCcw } from 'lucide-react';
import { Mode, ModelTier, ChatMessage } from '../types';
import { ChatInput } from './ChatInput';
import { Message } from './Message';
import { FeaturedGrid, FeaturedCardItem, renderCardIcon } from './FeaturedGrid';
import { sidecarClient } from '../api/client';

export interface ModePageProps {
  mode: Mode;
  onSelectMode: (mode: Mode) => void;
  activeModel: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
  customCases?: FeaturedCardItem[];
}

export interface ModeMetadata {
  title: string;
  tagline: string;
  badge: string;
  pipeline: string;
  categories: string[];
  cases: FeaturedCardItem[];
}

export const MODE_CONFIGS: Record<string, ModeMetadata> = {
  code: {
    title: 'Code Studio',
    tagline: 'Architect, refactor, and test software with AST precision and zero-trust safety',
    badge: 'Code Engine',
    pipeline: 'code_fix',
    categories: ['All', 'Refactoring', 'Architecture', 'Testing', 'Security'],
    cases: [
      {
        id: 'code-1',
        title: 'AST Refactor & Clean Architecture',
        category: 'Refactoring',
        description: 'Eliminate duplicate types, optimize imports, and enforce clean layered interfaces.',
        mode: 'code',
        iconName: 'code',
        estCost: '$0.0008 (CODE Tier)',
        tags: ['AST', 'TypeScript', 'Refactor'],
        prompt: 'Analyze current TypeScript modules, identify coupling antipatterns, and propose an AST-safe refactoring diff.',
      },
      {
        id: 'code-2',
        title: 'Generate Pytest Suite with Boundaries',
        category: 'Testing',
        description: 'Synthesize comprehensive unit and regression tests with 100% boundary assertion coverage.',
        mode: 'code',
        iconName: 'code',
        estCost: '$0.0012 (Small Model)',
        tags: ['Pytest', 'Coverage', 'Mocks'],
        prompt: 'Write a comprehensive test suite for the current module covering edge cases, empty payloads, and exception branches.',
      },
      {
        id: 'code-3',
        title: 'Zero-Trust Security & Vulnerability Audit',
        category: 'Security',
        description: 'Scan code for OWASP Top 10 vulnerabilities, credential leakage, and dangerous shell calls.',
        mode: 'code',
        iconName: 'code',
        estCost: '$0.0020 (Audit Model)',
        tags: ['OWASP', 'Zero-Trust', 'AST'],
        prompt: 'Perform an in-depth security scan of the codebase, flagging unescaped shell commands, raw SQL queries, and exposed secrets.',
      },
    ],
  },
  'deep-research': {
    title: 'Deep Research',
    tagline: 'Synthesize complex domains across literature, verified databases, and structured web evidence',
    badge: 'Research Lab',
    pipeline: 'finance_extract',
    categories: ['All', 'Market Analysis', 'Technical Review', 'Academic', 'Due Diligence'],
    cases: [
      {
        id: 'research-1',
        title: 'Local-First AI Engine Architecture Comparison',
        category: 'Technical Review',
        description: 'Multi-source synthesis comparing local edge agents against centralized frontier API platforms.',
        mode: 'deep-research',
        iconName: 'search',
        estCost: '$0.0035 (Deep Model)',
        tags: ['Local-First', 'Cost', 'Latency'],
        prompt: 'Investigate the trade-offs between local edge agent execution and centralized frontier APIs, focusing on cost routing and data sovereignty.',
      },
      {
        id: 'research-2',
        title: 'Open-Weight LLM Cost-Per-Success Index',
        category: 'Market Analysis',
        description: 'Quantify empirical benchmarks and cost curves across modern open-source foundation models.',
        mode: 'deep-research',
        iconName: 'search',
        estCost: '$0.0028 (Deep Model)',
        tags: ['Benchmarks', 'Open-Weight', 'Cost'],
        prompt: 'Compile a comparative cost-per-success index for top open-weight models across code generation, tool use, and mathematical reasoning.',
      },
      {
        id: 'research-3',
        title: 'Autonomous Multi-Agent Consensus Mechanisms',
        category: 'Academic',
        description: 'Examine communication protocols, peer review topologies, and voting trees in swarm agents.',
        mode: 'deep-research',
        iconName: 'search',
        estCost: '$0.0042 (Deep Model)',
        tags: ['Swarm', 'Consensus', 'Topology'],
        prompt: 'Review recent academic architectures for multi-agent peer review, consensus voting, and error arbitration in autonomous software swarms.',
      },
    ],
  },
  docs: {
    title: 'Docs Authoring',
    tagline: 'Draft polished specifications, RFCs, technical books, and structured executive briefs',
    badge: 'Authoring Studio',
    pipeline: 'chapter_write',
    categories: ['All', 'Specifications', 'RFCs', 'Technical Writing', 'Executive'],
    cases: [
      {
        id: 'docs-1',
        title: 'Draft Architectural RFC / ADR Specification',
        category: 'RFCs',
        description: 'Generate standard Architectural Decision Records with context, decision drivers, and consequences.',
        mode: 'docs',
        iconName: 'docs',
        estCost: '$0.0010 (Instant)',
        tags: ['ADR', 'RFC', 'Architecture'],
        prompt: 'Draft an Architecture Decision Record (ADR) detailing the 90/9/1 cost routing discipline and its hard circuit-breaker enforcement.',
      },
      {
        id: 'docs-2',
        title: 'Technical Book Chapter Outline & Pacing',
        category: 'Technical Writing',
        description: 'Structure comprehensive chapters with conceptual scaffolding, code walkthroughs, and summaries.',
        mode: 'docs',
        iconName: 'docs',
        estCost: '$0.0015 (Instant)',
        tags: ['Books', 'Scaffolding', 'Outlines'],
        prompt: 'Outline a technical chapter on building local-first autonomous agent supervisors using Tauri, Rust, and React.',
      },
      {
        id: 'docs-3',
        title: 'Executive Briefing & Strategy Summary',
        category: 'Executive',
        description: 'Condense complex technical milestones into crisp executive bullets with ROI metrics.',
        mode: 'docs',
        iconName: 'docs',
        estCost: '$0.0008 (Instant)',
        tags: ['Executive', 'ROI', 'Summary'],
        prompt: 'Draft a one-page executive memo summarizing the cost savings and latency improvements from local agent engine adoption.',
      },
    ],
  },
  sheets: {
    title: 'Sheets & Data',
    tagline: 'Analyze tabular datasets, reconcile financial records, and build spreadsheet transformations',
    badge: 'Tabular Analytics',
    pipeline: 'fast_text_generation',
    categories: ['All', 'Financials', 'Reconciliation', 'Modeling', 'Cleaning'],
    cases: [
      {
        id: 'sheets-1',
        title: 'Invoice & Expense Ledger Reconciliation',
        category: 'Reconciliation',
        description: 'Extract rows from CSV transactions, detect duplicate charges, and balance expense accounts.',
        mode: 'sheets',
        iconName: 'sheets',
        estCost: '$0.0012 (Instant)',
        tags: ['CSV', 'Ledger', 'Math'],
        prompt: 'Reconcile invoice line items against payment confirmations, identifying tax rate mismatches and unallocated line items.',
      },
      {
        id: 'sheets-2',
        title: 'Token Spend & Unit Economics Projections',
        category: 'Modeling',
        description: 'Build financial projections modeling inference costs at 100k, 1M, and 10M daily active queries.',
        mode: 'sheets',
        iconName: 'sheets',
        estCost: '$0.0015 (Instant)',
        tags: ['Unit Economics', 'Modeling', 'Forecast'],
        prompt: 'Construct a unit economics tabular model comparing frontier API costs against local-first 90/9/1 hybrid deployment.',
      },
      {
        id: 'sheets-3',
        title: 'Data Cleaning & Normalization Formulas',
        category: 'Cleaning',
        description: 'Generate Excel / Google Sheets formulas to clean dates, phone numbers, and currency formats.',
        mode: 'sheets',
        iconName: 'sheets',
        estCost: '$0.0006 (CODE Tier)',
        tags: ['Formulas', 'Regex', 'ETL'],
        prompt: 'Generate formulas to normalize heterogeneous ISO dates, clean international phone prefixes, and parse currency symbols.',
      },
    ],
  },
  slides: {
    title: 'Slides & Decks',
    tagline: 'Craft high-impact keynote slides, investor pitches, and technical architecture decks',
    badge: 'Presentation Engine',
    pipeline: 'fast_text_generation',
    categories: ['All', 'Pitch Decks', 'Technical', 'Product', 'Keynotes'],
    cases: [
      {
        id: 'slides-1',
        title: '10-Slide Investor Seed Pitch Deck',
        category: 'Pitch Decks',
        description: 'Structure problem, solution, TAM, architecture, unit economics, and team traction slides.',
        mode: 'slides',
        iconName: 'slides',
        estCost: '$0.0018 (Instant)',
        tags: ['Pitch', 'Seed', 'Investors'],
        prompt: 'Create a 10-slide pitch deck structure for an autonomous, local-first enterprise AI agent engine with verifiable cost routing.',
      },
      {
        id: 'slides-2',
        title: 'System Architecture Technical Deep-Dive',
        category: 'Technical',
        description: 'Visual slide narrative explaining sidecar supervision, memory graph, and sandbox isolation.',
        mode: 'slides',
        iconName: 'slides',
        estCost: '$0.0022 (Instant)',
        tags: ['Architecture', 'Deep-Dive', 'Diagrams'],
        prompt: 'Structure a technical presentation explaining how the Rust supervisor maintains zero-trust safety and AST sandboxing.',
      },
      {
        id: 'slides-3',
        title: 'Quarterly Product Roadmap & Delivery',
        category: 'Product',
        description: 'Highlight shipped milestones, user growth, latency improvements, and upcoming wave priorities.',
        mode: 'slides',
        iconName: 'slides',
        estCost: '$0.0014 (Instant)',
        tags: ['Roadmap', 'Milestones', 'KPIs'],
        prompt: 'Draft an executive slide deck presenting quarterly agent engine deliverables, benchmark scores, and cost optimizations.',
      },
    ],
  },
  websites: {
    title: 'Website Builder',
    tagline: 'Generate modern, responsive web apps, landing pages, and interactive UI showcases',
    badge: 'Web Studio',
    pipeline: 'code_fix',
    categories: ['All', 'Landing Pages', 'Components', 'Apps', 'Glassmorphic'],
    cases: [
      {
        id: 'web-1',
        title: 'Glassmorphic Dark-Mode Landing Page',
        category: 'Landing Pages',
        description: 'Build modern responsive hero section with subtle gradient glow and interactive CTA widgets.',
        mode: 'websites',
        iconName: 'websites',
        estCost: '$0.0015 (Instant)',
        tags: ['Tailwind', 'Glassmorphic', 'Hero'],
        prompt: 'Generate a sleek dark-theme landing page hero section in Tailwind CSS featuring glassmorphism and subtle accent glow.',
      },
      {
        id: 'web-2',
        title: 'Real-Time Telemetry & Monitoring Dashboard',
        category: 'Apps',
        description: 'Create responsive analytics layout with live latency gauges, cost meters, and token stream charts.',
        mode: 'websites',
        iconName: 'websites',
        estCost: '$0.0025 (Small Model)',
        tags: ['Charts', 'Dashboard', 'Telemetry'],
        prompt: 'Build a single-page monitoring dashboard UI showing real-time agent memory hits, token throughput, and circuit breaker status.',
      },
      {
        id: 'web-3',
        title: 'Interactive Pricing Calculator Component',
        category: 'Components',
        description: 'Implement dynamic slider calculator demonstrating 90/9/1 cost savings vs frontier models.',
        mode: 'websites',
        iconName: 'websites',
        estCost: '$0.0010 (Instant)',
        tags: ['Calculator', 'Interactive', 'Pricing'],
        prompt: 'Create a responsive React component with a slider allowing users to calculate monthly cost savings using local agent routing.',
      },
    ],
  },
  design: {
    title: 'Design Studio',
    tagline: 'Design cohesive UI systems, accessible design tokens, and interactive prototype components',
    badge: 'Design System',
    pipeline: 'fast_text_generation',
    categories: ['All', 'Design Tokens', 'Components', 'A11y', 'Visuals'],
    cases: [
      {
        id: 'design-1',
        title: 'Dark Theme Design Tokens & Contrast Audit',
        category: 'Design Tokens',
        description: 'Define WCAG AAA compliant color scales, border hierarchy, and typography tokens.',
        mode: 'design',
        iconName: 'design',
        estCost: '$0.0008 (CODE Tier)',
        tags: ['WCAG', 'Tokens', 'Contrast'],
        prompt: 'Audit the color palette against WCAG AAA standards and propose calibrated dark-mode tokens for high contrast readability.',
      },
      {
        id: 'design-2',
        title: 'Micro-Interactions & Keyboard Nav Specifications',
        category: 'A11y',
        description: 'Specify focus rings, ARIA roles, and smooth hover/active transitions for universal components.',
        mode: 'design',
        iconName: 'design',
        estCost: '$0.0012 (Instant)',
        tags: ['Keyboard', 'ARIA', 'Transitions'],
        prompt: 'Provide complete accessibility and interaction specs for universal dropdowns, modals, and multi-file attachment chips.',
      },
      {
        id: 'design-3',
        title: 'Component Library State Matrix',
        category: 'Components',
        description: 'Design exhaustive states (default, hover, active, disabled, loading, error) for primary controls.',
        mode: 'design',
        iconName: 'design',
        estCost: '$0.0010 (Instant)',
        tags: ['State Matrix', 'UI', 'Components'],
        prompt: 'Create a state specification matrix covering normal, hover, pressed, focused, disabled, and error states for button components.',
      },
    ],
  },
  diagrams: {
    title: 'Diagrams & Architecture',
    tagline: 'Generate clean Mermaid diagrams, cloud infrastructure topologies, and sequence flows',
    badge: 'Architecture Graph',
    pipeline: 'fast_text_generation',
    categories: ['All', 'System Architecture', 'Sequence', 'Entity Relationship', 'Pipelines'],
    cases: [
      {
        id: 'diagrams-1',
        title: 'Sidecar & Supervisor Architecture Topology',
        category: 'System Architecture',
        description: 'Mermaid flowchart mapping Tauri shell, Rust supervisor, FastAPI daemon, and SQLite/Chroma.',
        mode: 'diagrams',
        iconName: 'diagrams',
        estCost: '$0.0006 (CODE Tier)',
        tags: ['Mermaid', 'Architecture', 'Tauri'],
        prompt: 'Generate a comprehensive Mermaid diagram illustrating the Agent Engine desktop process supervisor and IPC boundaries.',
      },
      {
        id: 'diagrams-2',
        title: 'Multi-Agent Swarm Mission Protocol Sequence',
        category: 'Sequence',
        description: 'Sequence diagram tracing user dispatch, decomposition, parallel execution, and synthesis.',
        mode: 'diagrams',
        iconName: 'diagrams',
        estCost: '$0.0008 (CODE Tier)',
        tags: ['Sequence', 'Swarm', 'Protocol'],
        prompt: 'Create a Mermaid sequence diagram detailing the complete lifecycle of a multi-agent parallel mission from prompt to consensus.',
      },
      {
        id: 'diagrams-3',
        title: 'RAG Observational Memory Vector Pipeline',
        category: 'Pipelines',
        description: 'Dataflow diagram showing document ingestion, chunking, embedding, and hybrid semantic retrieval.',
        mode: 'diagrams',
        iconName: 'diagrams',
        estCost: '$0.0007 (CODE Tier)',
        tags: ['RAG', 'Vector', 'Dataflow'],
        prompt: 'Generate a Mermaid graph showing how documents are dragged into canvas, embedded into ChromaDB, and scored by temporal decay.',
      },
    ],
  },
};

export const ModePage: React.FC<ModePageProps> = ({
  mode,
  onSelectMode,
  activeModel,
  onSelectModel,
  inputRef,
  customCases,
}) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string>('All');
  const chatBottomRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const config = useMemo(() => {
    return (
      MODE_CONFIGS[mode] || {
        title: `${mode.replace('-', ' ')} Studio`,
        tagline: `Integrated workspace for ${mode} with automated cost routing`,
        badge: `${mode} Mode`,
        pipeline: 'fast_text_generation',
        categories: ['All', 'Featured', 'Custom'],
        cases: customCases || [],
      }
    );
  }, [mode, customCases]);

  const allCases = useMemo(() => {
    return customCases && customCases.length > 0 ? customCases : config.cases;
  }, [customCases, config.cases]);

  const filteredCases = useMemo(() => {
    if (activeCategory === 'All') return allCases;
    return allCases.filter(
      (c) => c.category.toLowerCase() === activeCategory.toLowerCase()
    );
  }, [allCases, activeCategory]);

  const [initialInputText, setInitialInputText] = useState('');

  const handleSelectCase = (card: FeaturedCardItem) => {
    setInitialInputText(card.prompt);
    if (inputRef?.current) {
      inputRef.current.value = card.prompt;
      inputRef.current.focus();
      const event = new Event('input', { bubbles: true });
      inputRef.current.dispatchEvent(event);
    }
  };

  const handleSendMessage = useCallback(
    (text: string) => {
      if (!text.trim()) return;

      const userMsg: ChatMessage = {
        id: `user-${Date.now()}`,
        role: 'user',
        content: text.trim(),
        timestamp: 'Just now',
      };

      const asstMsgId = `asst-${Date.now()}`;
      const assistantMsg: ChatMessage = {
        id: asstMsgId,
        role: 'assistant',
        content: '',
        isStreaming: true,
        timestamp: 'Just now',
        metadata: {
          modelTier: activeModel,
          estCost: '$0.0000',
          tokenCount: 0,
        },
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);

      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;

      let accumulated = '';
      const startTime = performance.now();

      sidecarClient.streamChatCompletion({
        prompt: `[${config.title} - ${config.pipeline}] ${text.trim()}`,
        model: activeModel,
        signal: controller.signal,
        onToken: (token: string) => {
          accumulated += token;
          const currentTokenCount = Math.ceil(accumulated.length / 4);
          const elapsed = Math.round(performance.now() - startTime);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === asstMsgId
                ? {
                    ...m,
                    content: accumulated,
                    metadata: {
                      ...m.metadata,
                      tokenCount: currentTokenCount,
                      latencyMs: elapsed,
                    },
                  }
                : m
            )
          );
        },
        onCostUpdate: (costData: any) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === asstMsgId
                ? {
                    ...m,
                    metadata: {
                      ...m.metadata,
                      estCost:
                        costData.cost_usd !== undefined
                          ? `$${costData.cost_usd.toFixed(4)}`
                          : m.metadata?.estCost,
                      tokenCount:
                        (costData.prompt_tokens || 0) + (costData.completion_tokens || 0),
                    },
                  }
                : m
            )
          );
        },
        onError: (errMsg: string) => {
          setIsStreaming(false);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === asstMsgId
                ? {
                    ...m,
                    content: accumulated
                      ? `${accumulated}\n\n❌ **Execution Error:** ${errMsg}`
                      : `❌ **Provider Error:** ${errMsg}`,
                    isStreaming: false,
                  }
                : m
            )
          );
        },
        onDone: () => {
          setIsStreaming(false);
          setMessages((prev) =>
            prev.map((m) => (m.id === asstMsgId ? { ...m, isStreaming: false } : m))
          );
        },
      });

      setTimeout(() => {
        chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' });
      }, 50);
    },
    [config.title, config.pipeline, activeModel]
  );

  const handleClearHistory = () => {
    setMessages([]);
  };

  return (
    <div className="h-full flex flex-col justify-between overflow-hidden bg-bg-base relative select-none">
      {/* Scrollable Content */}
      <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 scrollbar-thin">
        <div className="w-full max-w-[960px] mx-auto space-y-6">
          {/* Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border-subtle pb-5 text-left">
            <div>
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
                  {renderCardIcon(undefined, mode, 'w-4 h-4')}
                </div>
                <h1 className="text-xl font-bold text-text-primary tracking-tight capitalize">
                  {config.title}
                </h1>
                <span className="px-2 py-0.5 rounded-full bg-accent/10 border border-accent/20 text-[11px] font-medium text-accent">
                  {config.badge}
                </span>
              </div>
              <p className="text-xs text-text-secondary mt-1 max-w-xl leading-relaxed">
                {config.tagline}
              </p>
            </div>

            {messages.length > 0 && (
              <button
                type="button"
                onClick={handleClearHistory}
                className="px-3 py-1.5 rounded-lg bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary hover:text-text-primary flex items-center gap-1.5 transition-colors self-start sm:self-center"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                <span>New Session</span>
              </button>
            )}
          </div>

          {/* If there is active chat history, show conversation messages */}
          {messages.length > 0 ? (
            <div className="space-y-4 pt-2">
              {messages.map((msg) => (
                <Message
                  key={msg.id}
                  message={msg}
                />
              ))}
              <div ref={chatBottomRef} />
            </div>
          ) : (
            /* Empty state: Featured Cases with Category Filter */
            <div className="space-y-5 text-left">
              {/* Category Filter Tabs */}
              {config.categories.length > 1 && (
                <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
                  <div className="flex items-center gap-1 bg-bg-elevated p-1 rounded-xl border border-border-subtle">
                    {config.categories.map((cat) => (
                      <button
                        key={cat}
                        type="button"
                        onClick={() => setActiveCategory(cat)}
                        className={`px-3 py-1 text-xs font-medium rounded-lg transition-all ${
                          activeCategory === cat
                            ? 'bg-bg-hover text-text-primary shadow-sm'
                            : 'text-text-tertiary hover:text-text-secondary'
                        }`}
                      >
                        {cat}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Inspiration Section */}
              <div className="space-y-3">
                <div className="flex items-center justify-between px-1">
                  <span className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                    Curated {config.title} Templates
                  </span>
                  <span className="text-xs text-text-tertiary">
                    {filteredCases.length} runnable routines
                  </span>
                </div>

                <FeaturedGrid items={filteredCases} onSelectCard={handleSelectCase} />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Bottom Universal ChatInput */}
      <div className="border-t border-border-subtle bg-bg-base/95 backdrop-blur-md px-4 py-3">
        <div className="w-full max-w-[960px] mx-auto">
          <ChatInput
            mode={mode}
            model={activeModel}
            initialValue={initialInputText}
            onSend={(msg) => handleSendMessage(msg)}
            onStop={() => {
              if (abortControllerRef.current) {
                abortControllerRef.current.abort();
                abortControllerRef.current = null;
              }
              setIsStreaming(false);
              setMessages((prev) =>
                prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m))
              );
            }}
            isStreaming={isStreaming}
            onModeChange={onSelectMode}
            onModelChange={onSelectModel}
            inputRef={inputRef}
            placeholder={`Instruct ${config.title} agent or click a curated case above...`}
          />
        </div>
      </div>
    </div>
  );
};
