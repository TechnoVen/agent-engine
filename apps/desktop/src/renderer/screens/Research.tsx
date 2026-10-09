import React, { useState } from 'react';
import {
  Search,
  Globe,
  CheckCircle2,
  Copy,
  Send,
  Loader2,
  ShieldCheck,
} from 'lucide-react';
import { sidecarClient } from '../api/client';

export const Research: React.FC = () => {
  const [topic, setTopic] = useState('');
  const [reportContent, setReportContent] = useState('');
  const [isResearching, setIsResearching] = useState(false);
  const [notes, setNotes] = useState('');

  const sampleSources = [
    { title: 'Project Architecture & Local Kernel Spec', origin: 'Local Document', verified: true },
    { title: 'Deterministic Tool Execution Ledger (ADR-016)', origin: 'Observational Memory', verified: true },
  ];

  const handleStartResearch = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!topic.trim() || isResearching) return;

    setIsResearching(true);
    setReportContent('');

    const prompt = `Conduct a structured research synthesis on: "${topic}".\nProvide:\n1. Executive Summary\n2. Key Findings & Claims\n3. Methodological Evidence & Provenance\n4. Strategic Recommendations`;

    try {
      await sidecarClient.streamChatCompletion({
        prompt,
        onToken: (tok) => {
          setReportContent((prev) => prev + tok);
        },
      });
    } catch (err: any) {
      setReportContent(`[Research Execution Error: ${err?.message || 'Unable to complete research request'}]`);
    } finally {
      setIsResearching(false);
    }
  };

  const handleCopyReport = () => {
    if (reportContent) {
      navigator.clipboard.writeText(reportContent);
    }
  };

  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden" data-testid="research-screen">
      {/* Top Header & Query Bar */}
      <div className="border-b border-border-subtle bg-bg-elevated p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Search className="w-4 h-4 text-accent" />
            <h1 className="text-sm font-semibold tracking-tight text-text-primary">Research Workspace</h1>
          </div>
          <div className="flex items-center gap-2 text-[11px] font-mono text-text-tertiary">
            <span className="flex items-center gap-1 text-emerald-400">
              <ShieldCheck className="w-3.5 h-3.5" /> Local Synthesis Active
            </span>
            <span>•</span>
            <span className="text-warning">Web Deep Crawler: R4 Preview</span>
          </div>
        </div>

        {/* Universal Research Query Input */}
        <form onSubmit={handleStartResearch} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary" />
            <input
              type="text"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="Enter investigative research topic, hypothesis, or competitive query..."
              className="w-full pl-9 pr-3 py-2 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
            />
          </div>
          <button
            type="submit"
            disabled={isResearching || !topic.trim()}
            className="px-4 py-2 rounded-lg bg-accent hover:bg-accent-hover text-white text-xs font-medium flex items-center gap-1.5 transition-colors disabled:opacity-50 flex-shrink-0"
          >
            {isResearching ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Synthesizing...</span>
              </>
            ) : (
              <>
                <Send className="w-3.5 h-3.5" />
                <span>Synthesize Report</span>
              </>
            )}
          </button>
        </form>
      </div>

      {/* Main 2-Column Split: Sources & Notes (Left) / Synthesized Report (Right) */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Sources, Provenance & Notes */}
        <div className="w-80 border-r border-border-subtle bg-bg-elevated/40 p-4 space-y-4 overflow-y-auto">
          {/* Grounding Sources */}
          <div className="space-y-2">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
              Grounding Sources & Provenance
            </div>
            <div className="space-y-1.5">
              {sampleSources.map((s, idx) => (
                <div
                  key={idx}
                  className="p-2.5 rounded-md bg-bg-elevated border border-border-subtle text-xs space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-text-primary truncate mr-1">{s.title}</span>
                    <CheckCircle2 className="w-3 h-3 text-emerald-400 flex-shrink-0" />
                  </div>
                  <div className="text-[10px] font-mono text-text-tertiary">{s.origin}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Crawler Availability Notice */}
          <div className="p-3 rounded-lg bg-bg-elevated border border-border-subtle space-y-1.5 text-xs">
            <div className="flex items-center gap-1.5 font-medium text-text-primary text-[11px]">
              <Globe className="w-3.5 h-3.5 text-text-secondary" />
              <span>Multi-Source Crawler Status</span>
            </div>
            <p className="text-[11px] text-text-tertiary leading-relaxed">
              Real-time local synthesis is functional. Deep headless browser web-crawling is an R4 subsystem.
            </p>
            <span className="inline-block px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-[10px] font-mono text-warning">
              Preview · Coming in R4
            </span>
          </div>

          {/* Scratchpad Notes */}
          <div className="space-y-1.5 flex-1 flex flex-col">
            <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
              Investigator Notes
            </div>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Record hypotheses, claims to verify, or source URLs..."
              rows={6}
              className="w-full p-2.5 bg-bg-base border border-border-subtle rounded-md text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent font-mono resize-none leading-relaxed"
            />
          </div>
        </div>

        {/* Right: Synthesized Report Area */}
        <div className="flex-1 flex flex-col p-4 md:p-6 overflow-hidden">
          <div className="flex items-center justify-between pb-3 border-b border-border-subtle mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">
              Synthesized Findings & Report
            </span>
            {reportContent && (
              <button
                type="button"
                onClick={handleCopyReport}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary transition-colors"
              >
                <Copy className="w-3.5 h-3.5" />
                <span>Copy Markdown</span>
              </button>
            )}
          </div>

          {reportContent ? (
            <div className="flex-1 overflow-y-auto p-4 bg-bg-elevated/30 border border-border-subtle rounded-lg text-xs font-mono text-text-primary whitespace-pre-wrap leading-relaxed">
              {reportContent}
            </div>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center p-8 text-xs text-text-tertiary">
              <Search className="w-8 h-8 text-text-tertiary/40 mb-3" />
              <div className="font-medium text-text-secondary mb-1">No research synthesis active</div>
              <p className="max-w-sm text-[11px] leading-relaxed">
                Enter a topic or research query above and click "Synthesize Report" to generate an executive report with source attribution.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
