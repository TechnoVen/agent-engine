import React, { useState } from 'react';
import {
  Sparkles,
  User,
  Copy,
  Check,
  Zap,
  Brain,
  FileCode,
  Clock,
  Coins,
  Gauge,
} from 'lucide-react';
import { ChatMessage } from '../types';

export interface MessageProps {
  message: ChatMessage;
}

export const Message: React.FC<MessageProps> = ({ message }) => {
  const [copied, setCopied] = useState(false);
  const [copiedCodeIdx, setCopiedCodeIdx] = useState<number | null>(null);

  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  const handleCopyMessage = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const handleCopyCode = async (codeText: string, idx: number) => {
    try {
      await navigator.clipboard.writeText(codeText);
      setCopiedCodeIdx(idx);
      setTimeout(() => setCopiedCodeIdx(null), 2000);
    } catch {
      // Fallback
    }
  };

  // Fast lightweight markdown parser for 60fps streaming token rendering
  const renderFormattedContent = (content: string) => {
    // Split by code blocks ```...```
    const parts = content.split(/(```[\s\S]*?```)/g);
    let codeBlockCount = 0;

    return parts.map((part, pIdx) => {
      if (part.startsWith('```') && part.endsWith('```')) {
        const codeIdx = codeBlockCount++;
        const firstLineBreak = part.indexOf('\n');
        const lang =
          firstLineBreak !== -1 ? part.substring(3, firstLineBreak).trim() : '';
        const code =
          firstLineBreak !== -1
            ? part.substring(firstLineBreak + 1, part.length - 3)
            : part.substring(3, part.length - 3);

        const isCodeCopied = copiedCodeIdx === codeIdx;

        return (
          <div
            key={pIdx}
            className="my-3 rounded-lg overflow-hidden border border-border-strong bg-code-bg text-left font-mono text-xs shadow-md"
          >
            <div className="flex items-center justify-between px-3 py-1.5 bg-bg-elevated/80 border-b border-border-subtle text-[11px] text-text-tertiary select-none">
              <span className="font-semibold text-text-secondary uppercase tracking-wider">
                {lang || 'code'}
              </span>
              <button
                type="button"
                onClick={() => handleCopyCode(code, codeIdx)}
                className="flex items-center gap-1 hover:text-text-primary transition-colors text-[10px]"
                title="Copy code"
              >
                {isCodeCopied ? (
                  <>
                    <Check className="w-3 h-3 text-success" />
                    <span className="text-success">Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3 h-3" />
                    <span>Copy</span>
                  </>
                )}
              </button>
            </div>
            <pre className="p-3 overflow-x-auto text-text-primary leading-relaxed scrollbar-thin">
              <code>{code}</code>
            </pre>
          </div>
        );
      }

      // Paragraph / line formatting
      const lines = part.split('\n');
      return (
        <span key={pIdx}>
          {lines.map((line, lIdx) => {
            // Render Headings
            if (line.startsWith('### ')) {
              return (
                <h4 key={lIdx} className="text-sm font-bold text-text-primary mt-3 mb-1">
                  {renderInlineStyles(line.replace('### ', ''))}
                </h4>
              );
            }
            if (line.startsWith('## ')) {
              return (
                <h3 key={lIdx} className="text-base font-bold text-text-primary mt-3 mb-1.5 border-b border-border-subtle pb-1">
                  {renderInlineStyles(line.replace('## ', ''))}
                </h3>
              );
            }
            if (line.startsWith('# ')) {
              return (
                <h2 key={lIdx} className="text-lg font-bold text-text-primary mt-3 mb-1.5">
                  {renderInlineStyles(line.replace('# ', ''))}
                </h2>
              );
            }

            // Bullet list
            if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
              return (
                <div key={lIdx} className="flex items-start gap-2 ml-2 my-0.5 leading-relaxed">
                  <span className="text-accent text-xs mt-1.5">•</span>
                  <span>{renderInlineStyles(line.trim().substring(2))}</span>
                </div>
              );
            }

            // Numbered list
            const numMatch = line.trim().match(/^(\d+)\.\s+(.*)/);
            if (numMatch) {
              return (
                <div key={lIdx} className="flex items-start gap-2 ml-2 my-0.5 leading-relaxed">
                  <span className="text-accent font-mono text-xs">{numMatch[1]}.</span>
                  <span>{renderInlineStyles(numMatch[2])}</span>
                </div>
              );
            }

            // Blockquote
            if (line.startsWith('> ')) {
              return (
                <blockquote
                  key={lIdx}
                  className="border-l-2 border-accent/60 pl-3 my-1.5 text-text-secondary italic text-xs leading-relaxed"
                >
                  {renderInlineStyles(line.replace('> ', ''))}
                </blockquote>
              );
            }

            // Standard line
            return (
              <React.Fragment key={lIdx}>
                {renderInlineStyles(line)}
                {lIdx < lines.length - 1 && <br />}
              </React.Fragment>
            );
          })}
        </span>
      );
    });
  };

  // Inline formatting: bold, italic, inline code
  const renderInlineStyles = (text: string) => {
    // Process inline code `...`
    const segments = text.split(/(`[^`]+`)/g);
    return segments.map((segment, sIdx) => {
      if (segment.startsWith('`') && segment.endsWith('`') && segment.length >= 2) {
        return (
          <code
            key={sIdx}
            className="px-1.5 py-0.5 mx-0.5 rounded bg-bg-base border border-border-strong font-mono text-[11px] text-accent font-medium"
          >
            {segment.slice(1, -1)}
          </code>
        );
      }

      // Process bold **...**
      const boldParts = segment.split(/(\*\*[^*]+\*\*)/g);
      return boldParts.map((bPart, bIdx) => {
        if (bPart.startsWith('**') && bPart.endsWith('**') && bPart.length >= 4) {
          return (
            <strong key={`${sIdx}-${bIdx}`} className="font-semibold text-text-primary">
              {bPart.slice(2, -2)}
            </strong>
          );
        }
        return bPart;
      });
    });
  };

  if (isSystem) {
    return (
      <div className="w-full max-w-[760px] mx-auto my-3 px-4 py-2 rounded-lg bg-bg-elevated/40 border border-border-subtle text-xs text-text-secondary text-center">
        {message.content}
      </div>
    );
  }

  return (
    <div
      className={`w-full max-w-[760px] mx-auto my-4 flex gap-3 text-left group ${
        isUser ? 'justify-end' : 'justify-start'
      }`}
    >
      {/* Assistant Avatar */}
      {!isUser && (
        <div className="w-8 h-8 rounded-lg bg-accent/15 border border-accent/30 flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm">
          <Sparkles className="w-4 h-4 text-accent" />
        </div>
      )}

      {/* Message Bubble Container */}
      <div
        className={`flex flex-col max-w-[85%] ${
          isUser ? 'items-end' : 'items-start'
        }`}
      >
        {/* Author / Timestamp header */}
        <div className="flex items-center gap-2 mb-1 px-1 text-[11px] text-text-tertiary select-none">
          <span className="font-medium text-text-secondary">
            {isUser ? 'You' : 'Agent Engine'}
          </span>
          <span>•</span>
          <span>{message.timestamp}</span>
        </div>

        {/* Bubble content */}
        <div
          className={`p-3.5 rounded-2xl text-sm leading-relaxed ${
            isUser
              ? 'bg-accent text-white rounded-tr-sm shadow-md'
              : 'bg-bg-elevated border border-border-subtle text-text-primary rounded-tl-sm shadow-sm hover:border-border-strong transition-colors'
          }`}
        >
          {/* User Attachments (if any) */}
          {message.attachments && message.attachments.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mb-2 pb-2 border-b border-white/20">
              {message.attachments.map((f) => (
                <div
                  key={f.id}
                  className="flex items-center gap-1 px-2 py-0.5 rounded bg-black/20 text-[11px] font-mono"
                >
                  <FileCode className="w-3 h-3" />
                  <span className="truncate max-w-[120px]">{f.name}</span>
                </div>
              ))}
            </div>
          )}

          {/* Text Content */}
          <div className="break-words">
            {isUser ? (
              <p className="whitespace-pre-wrap">{message.content}</p>
            ) : (
              <div>
                {renderFormattedContent(message.content)}
                {message.isStreaming && (
                  <span className="inline-block w-1.5 h-4 bg-accent ml-0.5 animate-pulse align-middle" />
                )}
              </div>
            )}
          </div>
        </div>

        {/* Assistant Metrics & Controls Strip */}
        {!isUser && !message.isStreaming && (
          <div className="flex items-center gap-3 mt-1.5 px-1 text-[10px] font-mono text-text-tertiary select-none">
            {/* Model Tier */}
            {message.metadata?.modelTier && (
              <span className="flex items-center gap-1 text-text-secondary">
                {message.metadata.modelTier === 'instant' && <Zap className="w-3 h-3 text-warning" />}
                {message.metadata.modelTier === 'swarm' && <Sparkles className="w-3 h-3 text-accent" />}
                {message.metadata.modelTier === 'reasoning' && <Brain className="w-3 h-3 text-success" />}
                <span className="capitalize">{message.metadata.modelTier}</span>
              </span>
            )}

            {/* Token Speed */}
            {message.metadata?.tokensPerSec && (
              <span className="flex items-center gap-0.5">
                <Gauge className="w-3 h-3" />
                {message.metadata.tokensPerSec} t/s
              </span>
            )}

            {/* Latency */}
            {message.metadata?.latencyMs && (
              <span className="flex items-center gap-0.5">
                <Clock className="w-3 h-3" />
                {message.metadata.latencyMs}ms
              </span>
            )}

            {/* Cost */}
            {message.metadata?.estCost && (
              <span className="flex items-center gap-0.5 text-success">
                <Coins className="w-3 h-3" />
                {message.metadata.estCost}
              </span>
            )}

            {/* Copy button */}
            <button
              type="button"
              onClick={handleCopyMessage}
              className="ml-auto hover:text-text-primary flex items-center gap-1 transition-colors"
              title="Copy message"
            >
              {copied ? (
                <>
                  <Check className="w-3 h-3 text-success" />
                  <span className="text-success">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="w-3 h-3" />
                  <span>Copy</span>
                </>
              )}
            </button>
          </div>
        )}
      </div>

      {/* User Avatar */}
      {isUser && (
        <div className="w-8 h-8 rounded-lg bg-bg-elevated border border-border-strong flex items-center justify-center flex-shrink-0 mt-0.5 shadow-sm">
          <User className="w-4 h-4 text-text-secondary" />
        </div>
      )}
    </div>
  );
};
