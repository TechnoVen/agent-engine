import React, { useState, useRef } from 'react';
import {
  FileText,
  Plus,
  Download,
  Upload,
  Sparkles,
  ListTree,
  BookOpen,
  PanelRightClose,
  PanelRightOpen,
  Send,
  Loader2,
  ChevronDown,
} from 'lucide-react';
import { sidecarClient } from '../api/client';

export const Writing: React.FC = () => {
  const [docTitle, setDocTitle] = useState('Untitled Document');
  const [content, setContent] = useState('');
  const [selectedText, setSelectedText] = useState('');
  const [activeInspectorTab, setActiveInspectorTab] = useState<'outline' | 'assistant' | 'notes'>('outline');
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [notes, setNotes] = useState('');
  const [newMenuOpen, setNewMenuOpen] = useState(false);

  // Assistant state
  const [assistantPrompt, setAssistantPrompt] = useState('');
  const [assistantResponse, setAssistantResponse] = useState('');
  const [isAssistantStreaming, setIsAssistantStreaming] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Track selection for "Ask / Rewrite selected text"
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

  // Dynamic outline extraction from markdown headings
  const outlineHeadings = content
    .split('\n')
    .filter((line) => line.startsWith('#'))
    .map((line, idx) => {
      const level = (line.match(/^#+/) || ['#'])[0].length;
      const text = line.replace(/^#+\s*/, '').trim();
      return { id: idx, level, text };
    });

  const wordCount = content.trim() ? content.trim().split(/\s+/).length : 0;
  const charCount = content.length;

  const handleNewDocument = (template?: string) => {
    setNewMenuOpen(false);
    if (template === 'spec') {
      setDocTitle('Technical Specification');
      setContent('# Technical Specification\n\n## 1. Problem Statement\n\n## 2. Requirements\n\n## 3. Architecture & Data Flow\n\n## 4. Verification Plan\n');
    } else if (template === 'rfc') {
      setDocTitle('RFC Draft');
      setContent('# RFC: [Proposal Title]\n\n## Summary\n\n## Motivation\n\n## Detailed Design\n\n## Drawbacks & Alternatives\n');
    } else if (template === 'report') {
      setDocTitle('Executive Report');
      setContent('# Executive Summary\n\n## Key Findings\n\n## Methodology & Sources\n\n## Recommendations\n');
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
    link.download = `${docTitle.toLowerCase().replace(/\s+/g, '_') || 'document'}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  // Assistant run via sidecar
  const handleRunAssistant = async (customPrompt?: string) => {
    const promptToUse = customPrompt || assistantPrompt;
    if (!promptToUse.trim()) return;

    setActiveInspectorTab('assistant');
    setIsAssistantStreaming(true);
    setAssistantResponse('');

    const contextInstruction = selectedText
      ? `Selected document snippet:\n"""\n${selectedText}\n"""\n\nRequest: ${promptToUse}`
      : `Document title: ${docTitle}\nFull document:\n"""\n${content.slice(0, 4000)}\n"""\n\nRequest: ${promptToUse}`;

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
      setContent(nextContent);
      setSelectedText('');
    } else {
      setContent((prev) => (prev ? `${prev}\n\n${assistantResponse}` : assistantResponse));
    }
  };

  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden" data-testid="writing-screen">
      {/* Hidden File Input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".md,.txt,.json,.py,.ts"
        onChange={handleOpenFile}
        className="hidden"
      />

      {/* Top Action Bar */}
      <div className="h-12 border-b border-border-subtle bg-bg-elevated px-4 flex items-center justify-between">
        <div className="flex items-center gap-3 flex-1 max-w-md">
          <FileText className="w-4 h-4 text-accent flex-shrink-0" />
          <input
            type="text"
            value={docTitle}
            onChange={(e) => setDocTitle(e.target.value)}
            className="bg-transparent text-sm font-semibold text-text-primary focus:outline-none focus:border-b focus:border-accent w-full"
            placeholder="Document title..."
          />
        </div>

        {/* Middle Stats */}
        <div className="hidden md:flex items-center gap-3 text-[11px] font-mono text-text-tertiary">
          <span>{wordCount} words</span>
          <span>•</span>
          <span>{charCount} characters</span>
          <span>•</span>
          <span className="text-text-secondary">Local Workspace Session</span>
        </div>

        {/* Right Actions */}
        <div className="flex items-center gap-2">
          {/* New Document Dropdown */}
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
                <div className="px-3 py-1 text-[10px] uppercase font-semibold text-text-tertiary border-t border-border-subtle mt-1">
                  From Template
                </div>
                <button
                  type="button"
                  onClick={() => handleNewDocument('spec')}
                  className="w-full text-left px-3 py-1.5 hover:bg-bg-hover text-text-secondary hover:text-text-primary"
                >
                  Technical Spec
                </button>
                <button
                  type="button"
                  onClick={() => handleNewDocument('rfc')}
                  className="w-full text-left px-3 py-1.5 hover:bg-bg-hover text-text-secondary hover:text-text-primary"
                >
                  RFC Proposal
                </button>
                <button
                  type="button"
                  onClick={() => handleNewDocument('report')}
                  className="w-full text-left px-3 py-1.5 hover:bg-bg-hover text-text-secondary hover:text-text-primary"
                >
                  Executive Report
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
            title={inspectorOpen ? 'Collapse inspector' : 'Expand inspector'}
            className="p-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-text-secondary transition-colors"
          >
            {inspectorOpen ? <PanelRightClose className="w-4 h-4" /> : <PanelRightOpen className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Main 2-Pane Split: Document Editor (Left) & Context Inspector (Right) */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Document Editor */}
        <div className="flex-1 flex flex-col p-4 md:p-6 overflow-hidden">
          {/* Quick Selection Assist Bar */}
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
                  onClick={() => handleRunAssistant('Improve clarity and conciseness')}
                  className="px-2 py-0.5 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-[11px] text-text-primary"
                >
                  Rewrite
                </button>
                <button
                  type="button"
                  onClick={() => handleRunAssistant('Critique and highlight omissions')}
                  className="px-2 py-0.5 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-[11px] text-text-primary"
                >
                  Critique
                </button>
              </div>
            </div>
          )}

          {/* Actual Editable Content Area */}
          <textarea
            ref={textareaRef}
            value={content}
            onChange={(e) => setContent(e.target.value)}
            onSelect={handleSelect}
            placeholder="Write markdown or document text here..."
            className="flex-1 w-full p-4 bg-bg-elevated/40 border border-border-subtle rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-border-strong font-mono resize-none leading-relaxed overflow-y-auto"
          />
        </div>

        {/* Right: Collapsible Inspector Pane */}
        {inspectorOpen && (
          <div className="w-80 border-l border-border-subtle bg-bg-elevated flex flex-col overflow-hidden">
            {/* Inspector Tab Switcher */}
            <div className="h-10 border-b border-border-subtle flex items-center px-2 gap-1 text-xs">
              <button
                type="button"
                onClick={() => setActiveInspectorTab('outline')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-colors ${
                  activeInspectorTab === 'outline'
                    ? 'bg-bg-base text-text-primary font-medium'
                    : 'text-text-tertiary hover:text-text-secondary'
                }`}
              >
                <ListTree className="w-3.5 h-3.5" />
                <span>Outline</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveInspectorTab('assistant')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-colors ${
                  activeInspectorTab === 'assistant'
                    ? 'bg-bg-base text-text-primary font-medium'
                    : 'text-text-tertiary hover:text-text-secondary'
                }`}
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>Assistant</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveInspectorTab('notes')}
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-colors ${
                  activeInspectorTab === 'notes'
                    ? 'bg-bg-base text-text-primary font-medium'
                    : 'text-text-tertiary hover:text-text-secondary'
                }`}
              >
                <BookOpen className="w-3.5 h-3.5" />
                <span>Notes</span>
              </button>
            </div>

            {/* Inspector Tab Contents */}
            <div className="flex-1 overflow-y-auto p-3">
              {activeInspectorTab === 'outline' && (
                <div className="space-y-2">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary mb-2">
                    Document Headings
                  </div>
                  {outlineHeadings.length === 0 ? (
                    <div className="py-8 text-center text-xs text-text-tertiary">
                      No markdown headings (#) detected. Add headings to generate a structured outline.
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {outlineHeadings.map((h) => (
                        <div
                          key={h.id}
                          style={{ paddingLeft: `${(h.level - 1) * 12}px` }}
                          className="text-xs text-text-secondary hover:text-text-primary truncate py-1 cursor-default"
                        >
                          <span className="font-mono text-text-tertiary mr-1.5">{'#'.repeat(h.level)}</span>
                          <span>{h.text}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {activeInspectorTab === 'assistant' && (
                <div className="space-y-3 flex flex-col h-full">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
                    Contextual Assistant
                  </div>
                  <div className="space-y-1.5">
                    <textarea
                      value={assistantPrompt}
                      onChange={(e) => setAssistantPrompt(e.target.value)}
                      placeholder="Ask for feedback, rewrite, or expand..."
                      rows={3}
                      className="w-full p-2 bg-bg-base border border-border-subtle rounded text-xs text-text-primary focus:outline-none focus:border-accent resize-none"
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
                      <div className="flex-1 p-2 bg-bg-base border border-border-subtle rounded text-xs font-mono text-text-secondary whitespace-pre-wrap overflow-y-auto max-h-64 leading-relaxed">
                        {assistantResponse}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {activeInspectorTab === 'notes' && (
                <div className="space-y-2 h-full flex flex-col">
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
                    Sources & Reference Notes
                  </div>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Scratchpad for references, source links, and draft points..."
                    className="flex-1 w-full p-2.5 bg-bg-base border border-border-subtle rounded text-xs text-text-primary focus:outline-none focus:border-accent resize-none font-mono leading-relaxed"
                  />
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
