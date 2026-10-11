import React, { useState, useRef } from 'react';
import {
  FileText,
  Plus,
  Download,
  Upload,
  Sparkles,
  ListTree,
  PanelRightClose,
  PanelRightOpen,
  Send,
  Loader2,
  ChevronDown,
  CheckCircle2,
  AlertTriangle,
  FileCheck,
  ShieldCheck,
  Wand2,
  Play,
} from 'lucide-react';
import { sidecarClient } from '../api/client';
import {
  ArticleWorkflowState,
  ArticleWorkflowStage,
} from '../types';

export const Writing: React.FC = () => {
  const [docTitle, setDocTitle] = useState('Agent Engine Architecture: Production-Grade Multi-Model Systems');
  const [content, setContent] = useState('');
  const [selectedText, setSelectedText] = useState('');
  const [activeInspectorTab, setActiveInspectorTab] = useState<'workflow' | 'outline' | 'style' | 'claims' | 'notes' | 'assistant'>('workflow');
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [notes, setNotes] = useState(
    '### Core Facts & Source Notes\n' +
    '- Architecture: Deterministic router, zero-trust policy engine, execution coordinator kernel (ADR-016).\n' +
    '- Performance: Local models run with zero remote egress under LOCAL_ONLY boundary.\n' +
    '- Security: Strict HITL approval required for consequential operations (file deletion, network egress, shell commands).\n' +
    '- Verification: Multi-axis test suite, AST defense guards, cryptographic exact-operation digests.\n' +
    '- Deployment: Tauri desktop container with embedded Python sidecar communicated via Unix domain socket / localhost IPC token.'
  );
  const [newMenuOpen, setNewMenuOpen] = useState(false);

  // Workflow state
  const [workflowState, setWorkflowState] = useState<ArticleWorkflowState | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [workflowError, setWorkflowError] = useState<string | null>(null);

  // Assistant state
  const [assistantPrompt, setAssistantPrompt] = useState('');
  const [assistantResponse, setAssistantResponse] = useState('');
  const [isAssistantStreaming, setIsAssistantStreaming] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSelect = () => {
    if (textareaRef.current) {
      const start = textareaRef.current.selectionStart;
      const end = textareaRef.current.selectionEnd;
      if (start !== end) {
        setSelectedText(content.substring(start, end));
      } else {
        setSelectedText('');
      }
    }
  };

  const wordCount = content.trim() ? content.trim().split(/\s+/).length : 0;

  const ensureWorkflow = async (): Promise<ArticleWorkflowState> => {
    if (workflowState) return workflowState;
    const initial = await sidecarClient.createWritingWorkflow({
      project_id: 'default',
      title: docTitle,
      source_notes: notes,
      audience: 'Senior Software Engineers & AI Systems Architects',
      objective: 'Demonstrate deterministic local-first execution and safety boundaries in agentic systems.',
      style_guidance: 'Authoritative, precise, technically rigorous, devoid of marketing fluff.',
    });
    setWorkflowState(initial);
    return initial;
  };

  const handleGenerateOutline = async () => {
    setIsProcessing(true);
    setWorkflowError(null);
    try {
      const current = await ensureWorkflow();
      const updated = await sidecarClient.generateWritingOutline(current.workflow_run_id, {
        title: docTitle,
        source_notes: notes,
      });
      setWorkflowState(updated);
      setActiveInspectorTab('outline');
      if (!content.trim() && updated.outline) {
        setContent(updated.outline.thesis ? `# ${docTitle}\n\n**Thesis:** ${updated.outline.thesis}\n\n` : '');
      }
    } catch (err: any) {
      setWorkflowError(err?.message || 'Outline generation failed');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleGenerateDraft = async () => {
    setIsProcessing(true);
    setWorkflowError(null);
    try {
      const current = await ensureWorkflow();
      const updated = await sidecarClient.generateWritingDraft(current.workflow_run_id);
      setWorkflowState(updated);
      if (updated.draft?.content) {
        setContent(updated.draft.content);
      }
    } catch (err: any) {
      setWorkflowError(err?.message || 'Draft generation failed');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleReviewStyle = async () => {
    setIsProcessing(true);
    setWorkflowError(null);
    try {
      const current = await ensureWorkflow();
      const updated = await sidecarClient.reviewWritingStyle(current.workflow_run_id);
      setWorkflowState(updated);
      setActiveInspectorTab('style');
    } catch (err: any) {
      setWorkflowError(err?.message || 'Style review failed');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleReviseDraft = async () => {
    setIsProcessing(true);
    setWorkflowError(null);
    try {
      const current = await ensureWorkflow();
      const updated = await sidecarClient.reviseWritingDraft(current.workflow_run_id, {
        accepted_findings_only: true,
      });
      setWorkflowState(updated);
      if (updated.revised_draft?.content) {
        setContent(updated.revised_draft.content);
      }
    } catch (err: any) {
      setWorkflowError(err?.message || 'Revision failed');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleReviewClaims = async () => {
    setIsProcessing(true);
    setWorkflowError(null);
    try {
      const current = await ensureWorkflow();
      const updated = await sidecarClient.reviewWritingClaims(current.workflow_run_id);
      setWorkflowState(updated);
      setActiveInspectorTab('claims');
    } catch (err: any) {
      setWorkflowError(err?.message || 'Claim audit failed');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleFinalizeArticle = async () => {
    setIsProcessing(true);
    setWorkflowError(null);
    try {
      const current = await ensureWorkflow();
      const updated = await sidecarClient.finalizeWritingArticle(current.workflow_run_id, {
        final_content: content,
      });
      setWorkflowState(updated);
      setActiveInspectorTab('workflow');
    } catch (err: any) {
      setWorkflowError(err?.message || 'Finalization failed');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleRunFullPipeline = async () => {
    setIsProcessing(true);
    setWorkflowError(null);
    try {
      const completed = await sidecarClient.runFullWritingWorkflow({
        project_id: 'default',
        title: docTitle,
        source_notes: notes,
        audience: 'Senior Software Engineers & AI Systems Architects',
        objective: 'Comprehensive technical review of deterministic kernels and zero-trust safety.',
        style_guidance: 'Rigorous, clear, authoritative',
      });
      setWorkflowState(completed);
      if (completed.final_content) {
        setContent(completed.final_content);
      } else if (completed.revised_draft?.content) {
        setContent(completed.revised_draft.content);
      } else if (completed.draft?.content) {
        setContent(completed.draft.content);
      }
      setActiveInspectorTab('workflow');
    } catch (err: any) {
      setWorkflowError(err?.message || 'Full pipeline execution failed');
    } finally {
      setIsProcessing(false);
    }
  };

  const handleContentChange = (newText: string) => {
    setContent(newText);
    if (workflowState) {
      const stage = workflowState.current_stage;
      sidecarClient.editWritingStage(workflowState.workflow_run_id, {
        stage: stage === 'outline' ? 'outline' : stage === 'draft' ? 'draft' : 'final',
        content: newText,
      }).catch(() => {});
    }
  };

  const handleNewDocument = (template?: string) => {
    setNewMenuOpen(false);
    setWorkflowState(null);
    setWorkflowError(null);
    if (template === 'article') {
      setDocTitle('Agent Engine: High-Assurance AI Architecture');
      setContent('# Agent Engine: High-Assurance AI Architecture\n\n');
    } else {
      setDocTitle('Untitled Document');
      setContent('');
    }
    setAssistantResponse('');
    setSelectedText('');
  };

  const handleOpenFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      setContent(text || '');
      setDocTitle(file.name.replace(/\.[^/.]+$/, ''));
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const handleSaveFile = () => {
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = (docTitle.toLowerCase().replace(/\s+/g, '_') || 'article') + '.md';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleRunAssistant = async (customPrompt?: string) => {
    const promptToUse = customPrompt || assistantPrompt;
    if (!promptToUse.trim()) return;

    setActiveInspectorTab('assistant');
    setIsAssistantStreaming(true);
    setAssistantResponse('');

    const contextInstruction = selectedText
      ? `Selected snippet:\n"""\n${selectedText}\n"""\n\nRequest: ${promptToUse}`
      : `Document title: ${docTitle}\nContent:\n"""\n${content.slice(0, 4000)}\n"""\n\nRequest: ${promptToUse}`;

    try {
      await sidecarClient.streamChatCompletion({
        prompt: contextInstruction,
        onToken: (tok) => {
          setAssistantResponse((prev) => prev + tok);
        },
      });
    } catch (err: any) {
      setAssistantResponse(`[Error: ${err?.message || 'Failed to complete assistant request'}]`);
    } finally {
      setIsAssistantStreaming(false);
      setAssistantPrompt('');
    }
  };

  const handleInsertAssistantResponse = () => {
    if (!assistantResponse) return;
    if (selectedText && textareaRef.current) {
      const start = textareaRef.current.selectionStart;
      const end = textareaRef.current.selectionEnd;
      const nextContent = content.substring(0, start) + assistantResponse + content.substring(end);
      handleContentChange(nextContent);
      setSelectedText('');
    } else {
      handleContentChange(content ? `${content}\n\n${assistantResponse}` : assistantResponse);
    }
  };

  const currentStage: ArticleWorkflowStage = workflowState?.current_stage || 'notes';

  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden" data-testid="writing-screen">
      <input
        ref={fileInputRef}
        type="file"
        accept=".md,.txt,.json,.py,.ts"
        onChange={handleOpenFile}
        className="hidden"
      />

      {/* Top Action Bar */}
      <div className="h-12 border-b border-border-subtle bg-bg-elevated px-4 flex items-center justify-between">
        <div className="flex items-center gap-3 flex-1 max-w-lg">
          <FileText className="w-4 h-4 text-accent flex-shrink-0" />
          <input
            type="text"
            value={docTitle}
            onChange={(e) => setDocTitle(e.target.value)}
            className="bg-transparent text-sm font-semibold text-text-primary focus:outline-none focus:border-b focus:border-accent w-full"
            placeholder="Document title..."
          />
        </div>

        <div className="hidden lg:flex items-center gap-1.5 text-[11px] font-mono px-3 py-1 rounded bg-bg-base border border-border-subtle">
          <span className="text-text-tertiary">Stage:</span>
          <span className="px-1.5 py-0.5 rounded font-semibold text-[10px] uppercase bg-accent/20 text-accent border border-accent/30">
            {currentStage.replace('_', ' ')}
          </span>
          <span className="text-text-tertiary">•</span>
          <span className="text-text-secondary">{wordCount} words</span>
          {workflowState?.final_artifact_id && (
            <>
              <span className="text-text-tertiary">•</span>
              <span className="text-emerald-400 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" />
                <span>Artifact Persisted</span>
              </span>
            </>
          )}
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <button
              type="button"
              onClick={() => setNewMenuOpen(!newMenuOpen)}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>New</span>
              <ChevronDown className="w-3 h-3 text-text-tertiary" />
            </button>
            {newMenuOpen && (
              <div className="absolute right-0 mt-1 w-44 bg-bg-elevated border border-border-strong rounded-lg shadow-xl py-1 z-50 text-xs">
                <button
                  type="button"
                  onClick={() => handleNewDocument()}
                  className="w-full text-left px-3 py-1.5 hover:bg-bg-hover text-text-primary"
                >
                  Blank Document
                </button>
                <button
                  type="button"
                  onClick={() => handleNewDocument('article')}
                  className="w-full text-left px-3 py-1.5 hover:bg-bg-hover text-text-secondary hover:text-text-primary"
                >
                  Technical Article
                </button>
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary transition-colors"
          >
            <Upload className="w-3.5 h-3.5" />
            <span>Open</span>
          </button>

          <button
            type="button"
            onClick={handleSaveFile}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Save</span>
          </button>

          <button
            type="button"
            onClick={() => setInspectorOpen(!inspectorOpen)}
            className="p-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-text-secondary transition-colors"
          >
            {inspectorOpen ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Writing Pack Stage Toolbar */}
      <div className="h-10 border-b border-border-subtle bg-bg-base px-4 flex items-center justify-between text-xs overflow-x-auto">
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary mr-1">Writing Pack:</span>
          
          <button
            type="button"
            onClick={handleGenerateOutline}
            disabled={isProcessing}
            className="px-2.5 py-1 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-text-primary font-medium flex items-center gap-1.5 disabled:opacity-50 transition-colors"
          >
            <ListTree className="w-3.5 h-3.5 text-accent" />
            <span>1. Outline</span>
          </button>

          <button
            type="button"
            onClick={handleGenerateDraft}
            disabled={isProcessing}
            className="px-2.5 py-1 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-text-primary font-medium flex items-center gap-1.5 disabled:opacity-50 transition-colors"
          >
            <FileText className="w-3.5 h-3.5 text-blue-400" />
            <span>2. Draft</span>
          </button>

          <button
            type="button"
            onClick={handleReviewStyle}
            disabled={isProcessing}
            className="px-2.5 py-1 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-text-primary font-medium flex items-center gap-1.5 disabled:opacity-50 transition-colors"
          >
            <Sparkles className="w-3.5 h-3.5 text-amber-400" />
            <span>3. Style Review</span>
          </button>

          <button
            type="button"
            onClick={handleReviseDraft}
            disabled={isProcessing}
            className="px-2.5 py-1 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-text-primary font-medium flex items-center gap-1.5 disabled:opacity-50 transition-colors"
          >
            <Wand2 className="w-3.5 h-3.5 text-purple-400" />
            <span>4. Revise</span>
          </button>

          <button
            type="button"
            onClick={handleReviewClaims}
            disabled={isProcessing}
            className="px-2.5 py-1 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-text-primary font-medium flex items-center gap-1.5 disabled:opacity-50 transition-colors"
          >
            <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
            <span>5. Claim Audit</span>
          </button>

          <button
            type="button"
            onClick={handleFinalizeArticle}
            disabled={isProcessing}
            className="px-2.5 py-1 rounded bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/40 text-emerald-300 font-medium flex items-center gap-1.5 disabled:opacity-50 transition-colors"
          >
            <FileCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span>6. Finalize</span>
          </button>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            type="button"
            onClick={handleRunFullPipeline}
            disabled={isProcessing}
            className="px-3 py-1 rounded bg-accent hover:bg-accent-hover text-white font-medium flex items-center gap-1.5 disabled:opacity-50 transition-colors shadow-sm"
          >
            {isProcessing ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Executing Pipeline...</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5" />
                <span>Run Full Pipeline</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Main 2-Pane Split */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Document Editor */}
        <div className="flex-1 flex flex-col p-4 md:p-6 overflow-hidden">
          {workflowError && (
            <div className="mb-3 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              <span>{workflowError}</span>
            </div>
          )}

          {selectedText && (
            <div className="mb-2 p-2 rounded-lg bg-accent/10 border border-accent/30 flex items-center justify-between text-xs animate-in fade-in">
              <div className="flex items-center gap-2 truncate mr-3">
                <Sparkles className="w-3.5 h-3.5 text-accent flex-shrink-0" />
                <span className="text-text-secondary truncate">
                  Selected: <span className="font-mono text-text-primary">"{selectedText.slice(0, 40)}..."</span>
                </span>
              </div>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => handleRunAssistant('Improve clarity, conciseness, and precision')}
                  className="px-2 py-0.5 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-[11px] text-text-primary"
                >
                  Rewrite
                </button>
                <button
                  type="button"
                  onClick={() => handleRunAssistant('Critique flow and factual precision')}
                  className="px-2 py-0.5 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-[11px] text-text-primary"
                >
                  Critique
                </button>
              </div>
            </div>
          )}

          <textarea
            ref={textareaRef}
            value={content}
            onChange={(e) => handleContentChange(e.target.value)}
            onSelect={handleSelect}
            placeholder="Write markdown prose here, or click '1. Outline' or 'Run Full Pipeline' to generate from source notes..."
            className="flex-1 w-full p-4 bg-bg-base border border-border-subtle rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-border-strong font-mono resize-none leading-relaxed overflow-y-auto"
          />
        </div>

        {/* Right: Collapsible Inspector Pane */}
        {inspectorOpen && (
          <div className="w-96 border-l border-border-subtle bg-bg-elevated flex flex-col overflow-hidden">
            <div className="h-10 border-b border-border-subtle flex items-center px-2 gap-1 text-xs overflow-x-auto">
              <button
                type="button"
                onClick={() => setActiveInspectorTab('workflow')}
                className={`px-2 py-1 rounded transition-colors ${
                  activeInspectorTab === 'workflow'
                    ? 'bg-bg-base text-text-primary font-medium'
                    : 'text-text-tertiary hover:text-text-secondary'
                }`}
              >
                Pipeline
              </button>
              <button
                type="button"
                onClick={() => setActiveInspectorTab('outline')}
                className={`px-2 py-1 rounded transition-colors ${
                  activeInspectorTab === 'outline'
                    ? 'bg-bg-base text-text-primary font-medium'
                    : 'text-text-tertiary hover:text-text-secondary'
                }`}
              >
                Outline
              </button>
              <button
                type="button"
                onClick={() => setActiveInspectorTab('style')}
                className={`px-2 py-1 rounded transition-colors ${
                  activeInspectorTab === 'style'
                    ? 'bg-bg-base text-text-primary font-medium'
                    : 'text-text-tertiary hover:text-text-secondary'
                }`}
              >
                Style
              </button>
              <button
                type="button"
                onClick={() => setActiveInspectorTab('claims')}
                className={`px-2 py-1 rounded transition-colors ${
                  activeInspectorTab === 'claims'
                    ? 'bg-bg-base text-text-primary font-medium'
                    : 'text-text-tertiary hover:text-text-secondary'
                }`}
              >
                Claims
              </button>
              <button
                type="button"
                onClick={() => setActiveInspectorTab('notes')}
                className={`px-2 py-1 rounded transition-colors ${
                  activeInspectorTab === 'notes'
                    ? 'bg-bg-base text-text-primary font-medium'
                    : 'text-text-tertiary hover:text-text-secondary'
                }`}
              >
                Notes
              </button>
              <button
                type="button"
                onClick={() => setActiveInspectorTab('assistant')}
                className={`px-2 py-1 rounded transition-colors ${
                  activeInspectorTab === 'assistant'
                    ? 'bg-bg-base text-text-primary font-medium'
                    : 'text-text-tertiary hover:text-text-secondary'
                }`}
              >
                Assist
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-3 text-xs">
              {activeInspectorTab === 'workflow' && (
                <div className="space-y-3">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
                    Pipeline Status & Provenance
                  </div>

                  <div className="p-3 bg-bg-base border border-border-subtle rounded-lg space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-text-tertiary">Workflow Run ID:</span>
                      <span className="font-mono text-text-primary">{workflowState?.workflow_run_id || 'Not started'}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-text-tertiary">Active Stage:</span>
                      <span className="font-semibold text-accent uppercase">{currentStage}</span>
                    </div>
                    {workflowState?.final_artifact_id && (
                      <div className="pt-2 border-t border-border-subtle text-emerald-400">
                        <div className="font-semibold">Final Article Artifact:</div>
                        <div className="font-mono text-[11px]">{workflowState.final_artifact_id}</div>
                      </div>
                    )}
                  </div>

                  <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary pt-2">
                    Execution Steps ({workflowState?.execution_history.length || 0})
                  </div>
                  {(!workflowState || workflowState.execution_history.length === 0) ? (
                    <div className="py-4 text-center text-text-tertiary">
                      No executions recorded yet.
                    </div>
                  ) : (
                    <div className="space-y-1.5">
                      {workflowState.execution_history.map((step, idx) => (
                        <div key={idx} className="p-2 bg-bg-base border border-border-subtle rounded text-[11px] space-y-1">
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-text-primary uppercase">{step.stage}</span>
                            <span className="font-mono text-[10px] text-text-tertiary">{step.execution_id.slice(0, 10)}...</span>
                          </div>
                          {step.artifact_id && (
                            <div className="text-[10px] text-emerald-400 font-mono truncate">
                              Artifact: {step.artifact_id}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {activeInspectorTab === 'outline' && (
                <div className="space-y-3">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
                    Structured Thesis & Sections
                  </div>
                  {!workflowState?.outline ? (
                    <div className="py-8 text-center text-text-tertiary">
                      No outline generated yet. Click '1. Outline' above.
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="p-3 bg-bg-base border border-border-subtle rounded-lg">
                        <div className="text-[10px] uppercase font-semibold text-text-tertiary mb-1">Thesis</div>
                        <div className="text-text-primary leading-relaxed">{workflowState.outline.thesis}</div>
                      </div>
                      <div className="space-y-2">
                        {workflowState.outline.sections.map((sec, i) => (
                          <div key={i} className="p-2.5 bg-bg-base border border-border-subtle rounded-lg space-y-1.5">
                            <div className="font-semibold text-text-primary">{i + 1}. {sec.title}</div>
                            <div className="text-text-secondary text-[11px]"><span className="text-text-tertiary">Intent:</span> {sec.intent}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {activeInspectorTab === 'style' && (
                <div className="space-y-3">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
                    Style & Editorial Audit
                  </div>
                  {!workflowState?.style_review ? (
                    <div className="py-8 text-center text-text-tertiary">
                      No style review recorded yet. Click '3. Style Review'.
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="p-3 bg-bg-base border border-border-subtle rounded-lg">
                        <div className="text-[10px] uppercase font-semibold text-text-tertiary mb-1">Overall Feedback</div>
                        <div className="text-text-primary leading-relaxed">{workflowState.style_review.overall_feedback}</div>
                      </div>
                      <div className="space-y-2">
                        {workflowState.style_review.findings.map((finding, idx) => (
                          <div key={idx} className="p-2.5 bg-bg-base border border-border-subtle rounded-lg space-y-1.5">
                            <div className="flex items-center justify-between">
                              <span className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-accent/20 text-accent font-semibold uppercase">
                                {finding.category}
                              </span>
                              <span className="text-[10px] text-text-tertiary truncate max-w-[150px]">{finding.location}</span>
                            </div>
                            <div className="text-text-primary text-[11px]">{finding.issue}</div>
                            <div className="text-[11px] text-emerald-400/90 pl-2 border-l border-emerald-500/30">
                              Suggestion: {finding.suggestion}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {activeInspectorTab === 'claims' && (
                <div className="space-y-3">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
                    Claim & Factuality Verification
                  </div>
                  {!workflowState?.claim_review ? (
                    <div className="py-8 text-center text-text-tertiary">
                      No claim audit performed yet. Click '5. Claim Audit'.
                    </div>
                  ) : (
                    <div className="space-y-3">
                      <div className="p-3 bg-bg-base border border-border-subtle rounded-lg space-y-1">
                        <div className="text-text-primary font-medium">{workflowState.claim_review.summary}</div>
                        <div className="flex items-center gap-3 text-[11px] pt-1">
                          <span className="text-emerald-400 font-semibold">{workflowState.claim_review.supported_count} Supported</span>
                          <span className="text-amber-400 font-semibold">{workflowState.claim_review.unsupported_count} Unsupported</span>
                        </div>
                      </div>
                      <div className="space-y-2">
                        {workflowState.claim_review.claims.map((claim, idx) => (
                          <div key={idx} className="p-2.5 bg-bg-base border border-border-subtle rounded-lg space-y-1">
                            <span className="font-mono text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase bg-emerald-500/20 text-emerald-400">
                              {claim.classification}
                            </span>
                            <div className="text-text-primary text-[11px] italic font-serif">"{claim.claim_text}"</div>
                            <div className="text-[10px] text-text-tertiary">Rationale: {claim.rationale}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {activeInspectorTab === 'notes' && (
                <div className="space-y-2 h-full flex flex-col">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
                    Ground Truth Sources & Notes
                  </div>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Enter factual background notes, requirements, and reference passages..."
                    className="flex-1 w-full p-2.5 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary focus:outline-none focus:border-accent resize-none font-mono leading-relaxed min-h-[300px]"
                  />
                </div>
              )}

              {activeInspectorTab === 'assistant' && (
                <div className="space-y-3 flex flex-col h-full">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
                    Interactive Writing Assistant
                  </div>
                  <div className="space-y-1.5">
                    <textarea
                      value={assistantPrompt}
                      onChange={(e) => setAssistantPrompt(e.target.value)}
                      placeholder="Ask for feedback, rewrite, or expand..."
                      rows={3}
                      className="w-full p-2 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary focus:outline-none focus:border-accent resize-none"
                    />
                    <button
                      type="button"
                      onClick={() => handleRunAssistant()}
                      disabled={isAssistantStreaming || !assistantPrompt.trim()}
                      className="w-full py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50"
                    >
                      {isAssistantStreaming ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          <span>Generating...</span>
                        </>
                      ) : (
                        <>
                          <Send className="w-3.5 h-3.5" />
                          <span>Run Assistance</span>
                        </>
                      )}
                    </button>
                  </div>
                  {assistantResponse && (
                    <div className="flex-1 flex flex-col space-y-2 pt-2 border-t border-border-subtle">
                      <div className="flex items-center justify-between text-[11px] text-text-tertiary">
                        <span>Response</span>
                        <button
                          type="button"
                          onClick={handleInsertAssistantResponse}
                          className="text-accent hover:underline text-[11px]"
                        >
                          Insert into doc
                        </button>
                      </div>
                      <div className="flex-1 p-2 bg-bg-base border border-border-subtle rounded-lg text-xs font-mono text-text-secondary whitespace-pre-wrap overflow-y-auto max-h-64 leading-relaxed">
                        {assistantResponse}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
