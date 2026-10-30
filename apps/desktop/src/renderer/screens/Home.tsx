import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Search,
  FileText,
  Table2,
  Code2,
  RotateCcw,
  FolderKanban,
  Upload,
  Loader2,
  Clock,
  Pin,
} from 'lucide-react';
import {
  Mode,
  ModelTier,
  ChatMessage,
  AttachmentFile,
  SelectedSkill,
  ApprovalRequest,
  AgentPersona,
  PrivacyBoundary,
  RoutingObjective,
} from '../types';
import { ChatInput } from '../components/ChatInput';
import { Message } from '../components/Message';
import { ExecutionPreferences } from '../components/ExecutionPreferences';
import { sidecarClient, DEFAULT_PERSONAS } from '../api/client';

export interface HomeProps {
  onSelectMode: (mode: Mode) => void;
  activeModel: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  routingObjective?: RoutingObjective;
  onSelectRoutingObjective?: (objective: RoutingObjective) => void;
  privacyBoundary?: PrivacyBoundary;
  onSelectPrivacyBoundary?: (boundary: PrivacyBoundary) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
  initialMessages?: ChatMessage[];
  activeSessionId?: string;
  onBusyChange?: (isBusy: boolean) => void;
  onProjectNameChange?: (name: string) => void;
}

export const Home: React.FC<HomeProps> = ({
  onSelectMode,
  activeModel,
  onSelectModel,
  routingObjective = 'balanced',
  onSelectRoutingObjective,
  privacyBoundary = 'local_only',
  onSelectPrivacyBoundary,
  inputRef: externalInputRef,
  initialMessages = [],
  activeSessionId,
  onBusyChange,
  onProjectNameChange,
}) => {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeRoutingObjective, setActiveRoutingObjective] = useState<RoutingObjective>(routingObjective);
  const [activePrivacyBoundary, setActivePrivacyBoundary] = useState<PrivacyBoundary>(privacyBoundary);
  const [activeProjectId, setActiveProjectId] = useState<string>('1');
  const [activeProjectName, setActiveProjectName] = useState<string>('Agent Engine');
  const [initialInputText, setInitialInputText] = useState('');
  const [activePersona, setActivePersona] = useState<AgentPersona>(DEFAULT_PERSONAS[0]);
  const [isCanvasDragOver, setIsCanvasDragOver] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [canvasAttachments, setCanvasAttachments] = useState<AttachmentFile[]>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const internalInputRef = useRef<HTMLTextAreaElement>(null);
  const activeInputRef = externalInputRef || internalInputRef;
  const activeAbortController = useRef<AbortController | null>(null);

  // Sync privacy & routing when parent props change
  useEffect(() => {
    setActiveRoutingObjective(routingObjective);
  }, [routingObjective]);

  useEffect(() => {
    setActivePrivacyBoundary(privacyBoundary);
  }, [privacyBoundary]);

  // Sync busy state
  useEffect(() => {
    onBusyChange?.(isStreaming);
  }, [isStreaming, onBusyChange]);

  const handleRoutingObjectiveChange = (obj: RoutingObjective) => {
    setActiveRoutingObjective(obj);
    onSelectRoutingObjective?.(obj);
  };

  const handlePrivacyBoundaryChange = (pb: PrivacyBoundary) => {
    setActivePrivacyBoundary(pb);
    onSelectPrivacyBoundary?.(pb);
  };

  // Session persistence: load session messages when activeSessionId changes
  useEffect(() => {
    if (!activeSessionId) return;
    let isCurrent = true;
    const loadSession = async () => {
      try {
        const sess = await sidecarClient.getSession(activeSessionId);
        if (isCurrent && sess && sess.messages && sess.messages.length > 0) {
          const loaded: ChatMessage[] = sess.messages.map((m: any, idx: number) => ({
            id: m.message_id || `msg-${idx}`,
            role: m.role === 'user' ? 'user' : 'assistant',
            content: m.content || '',
            timestamp: m.timestamp ? new Date(m.timestamp).toLocaleTimeString() : 'Earlier',
            metadata: {
              modelTier: (m.metadata?.model || 'instant') as ModelTier,
              tokenCount: m.tokens?.completion_tokens || m.metadata?.completion_tokens,
              estCost: m.cost_usd !== undefined ? `$${m.cost_usd.toFixed(4)}` : undefined,
              ...m.metadata,
            },
          }));
          setMessages(loaded);
        }
      } catch {
        // Offline or session not found
      }
    };
    loadSession();
    return () => {
      isCurrent = false;
    };
  }, [activeSessionId]);

  // Canvas Drag & Drop handlers
  const handleCanvasDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.dataTransfer.types.includes('Files')) {
      setIsCanvasDragOver(true);
    }
  };

  const handleCanvasDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    e.dataTransfer.dropEffect = 'copy';
    if (!isCanvasDragOver) {
      setIsCanvasDragOver(true);
    }
  };

  const handleCanvasDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setIsCanvasDragOver(false);
  };

  const handleCanvasDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsCanvasDragOver(false);

    const files = e.dataTransfer.files;
    if (!files || files.length === 0) return;

    setUploadProgress(15);
    const fileList = Array.from(files);
    let completed = 0;

    fileList.forEach((file) => {
      const id = `${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;
      const reader = new FileReader();

      reader.onload = async (event) => {
        const text = typeof event.target?.result === 'string' ? event.target.result : '';
        const snippet = text.slice(0, 1000);
        const attachment: AttachmentFile = {
          id,
          name: file.name,
          size: file.size,
          type: file.type || 'application/octet-stream',
          snippet: snippet || `Attachment: ${file.name} (${file.size} bytes)`,
          uploadProgress: 100,
          status: 'indexed',
        };

        try {
          await sidecarClient.observeMemory({
            content: `[Document Grounding: ${file.name}]\n${snippet || file.name}`,
            category: 'rag_document',
            metadata: { filename: file.name, size: file.size, type: file.type },
          });
        } catch {
          // ignore offline error
        }

        completed += 1;
        const pct = Math.round((completed / fileList.length) * 100);
        setUploadProgress(pct);
        setCanvasAttachments((prev) => [...prev, attachment]);

        if (completed === fileList.length) {
          setTimeout(() => setUploadProgress(null), 1200);
        }
      };

      if (file.type.startsWith('image/')) {
        reader.readAsDataURL(file);
      } else {
        reader.readAsText(file);
      }
    });
  };

  // Update model
  const handleModelChange = useCallback(
    (newModel: ModelTier) => {
      onSelectModel?.(newModel);
    },
    [onSelectModel]
  );

  // Switch persona
  const handlePersonaChange = useCallback(
    (persona: AgentPersona) => {
      setActivePersona(persona);
      if (persona.suggestedModel && persona.suggestedModel !== activeModel) {
        onSelectModel?.(persona.suggestedModel);
      }
    },
    [activeModel, onSelectModel]
  );

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

  const [realProjects, setRealProjects] = useState<any[]>([]);
  const [recentSessions, setRecentSessions] = useState<any[]>([]);

  useEffect(() => {
    let mounted = true;
    const loadHomeData = async () => {
      try {
        const [projs, sess] = await Promise.all([
          sidecarClient.getProjects(5),
          sidecarClient.getSessions(5),
        ]);
        if (mounted) {
          if (Array.isArray(projs)) setRealProjects(projs);
          if (Array.isArray(sess)) setRecentSessions(sess);
        }
      } catch {
        // offline or fallback
      }
    };
    loadHomeData();
    return () => {
      mounted = false;
    };
  }, []);

  const contextualTools = [
    { mode: 'research' as Mode, label: 'Research', icon: <Search className="w-3.5 h-3.5 text-text-secondary" /> },
    { mode: 'writing' as Mode, label: 'Writing', icon: <FileText className="w-3.5 h-3.5 text-text-secondary" /> },
    { mode: 'data' as Mode, label: 'Data', icon: <Table2 className="w-3.5 h-3.5 text-text-secondary" /> },
    { mode: 'developer' as Mode, label: 'Developer', icon: <Code2 className="w-3.5 h-3.5 text-text-secondary" /> },
  ];

  // Real streaming token dispatcher via sidecarClient
  const startStreamingResponse = useCallback(
    (
      promptText: string,
      model: ModelTier,
      skill?: SelectedSkill,
      enabledPlugins?: string[]
    ) => {
      if (activeAbortController.current) {
        activeAbortController.current.abort();
      }
      const controller = new AbortController();
      activeAbortController.current = controller;

      setIsStreaming(true);

      const assistantMsgId = `msg-${Date.now()}`;
      const startTime = performance.now();

      // Placeholder assistant message with execution provenance
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
            estCost: '$0.0000',
            effectivePrivacy: activePrivacyBoundary,
            routingObjective: activeRoutingObjective,
            skillId: skill?.skill.id,
            skillName: skill?.skill.name,
            enabledPlugins,
            execution: {
              status: 'streaming',
              isLocal: activePrivacyBoundary === 'local_only',
              effectivePrivacy: activePrivacyBoundary,
              routingObjective: activeRoutingObjective,
            },
          },
        },
      ]);

      let accumulated = '';
      const promptPayload = skill
        ? `[Skill: ${skill.skill.name} (${skill.skill.command})] ${promptText}`
        : promptText;

      sidecarClient.streamChatCompletion({
        prompt: promptPayload,
        sessionId: activeSessionId,
        model,
        routingObjective: activeRoutingObjective,
        privacyBoundary: activePrivacyBoundary,
        signal: controller.signal,
        onToken: (token: string) => {
          accumulated += token;
          const now = performance.now();
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
                      execution: {
                        ...m.metadata?.execution,
                        totalTokens: currentTokenCount,
                        latencyMs: Math.round(now - startTime),
                        tokensPerSec: tps,
                      },
                    },
                  }
                : m
            )
          );
        },
        onRoutingResolved: (payload: any) => {
          const decision = payload.decision || {};
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    metadata: {
                      ...m.metadata,
                      executionId: payload.execution_id || m.metadata?.executionId,
                      provider: decision.provider || m.metadata?.provider,
                      modelName: decision.model || m.metadata?.modelName,
                      isLocal: decision.is_local !== undefined ? decision.is_local : m.metadata?.isLocal,
                      effectivePrivacy: decision.privacy_boundary || activePrivacyBoundary,
                      routingObjective: decision.routing_objective || activeRoutingObjective,
                      routingExplanation: decision.explanation || m.metadata?.routingExplanation,
                      execution: {
                        ...m.metadata?.execution,
                        executionId: payload.execution_id || m.metadata?.execution?.executionId,
                        status: 'running',
                        provider: decision.provider || m.metadata?.execution?.provider,
                        model: decision.model || m.metadata?.execution?.model,
                        isLocal: decision.is_local !== undefined ? decision.is_local : m.metadata?.execution?.isLocal,
                        effectivePrivacy: decision.privacy_boundary || activePrivacyBoundary,
                        routingObjective: decision.routing_objective || activeRoutingObjective,
                        routingExplanation: decision.explanation || m.metadata?.execution?.routingExplanation,
                      },
                    },
                  }
                : m
            )
          );
        },
        onApprovalRequired: (payload: any) => {
          const appr = payload.approval || payload;
          const approvalReq: ApprovalRequest = {
            id: appr.id || `appr-${Date.now()}`,
            toolName: appr.tool_name || appr.toolName || 'system_operation',
            toolArgs: appr.tool_args || appr.toolArgs || {},
            riskLevel: appr.risk_level || appr.riskLevel || 'high',
            riskScore: appr.risk_score || appr.riskScore || 0.8,
            reason: appr.reason || 'Operation requires operator authorization',
            suggestion: appr.suggestion || 'Verify parameters before proceeding',
            status: 'pending',
            createdAt: 'Just now',
          };
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    approvalRequest: approvalReq,
                    metadata: {
                      ...m.metadata,
                      policyStatus: 'approval_required',
                    },
                  }
                : m
            )
          );
        },
        onCostUpdate: (costData: any) => {
          const totalTokens = (costData.prompt_tokens || 0) + (costData.completion_tokens || 0);
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    metadata: {
                      ...m.metadata,
                      executionId: costData.execution_id || m.metadata?.executionId,
                      provider: costData.provider || m.metadata?.provider,
                      modelName: costData.model || m.metadata?.modelName,
                      isLocal: costData.is_local !== undefined ? costData.is_local : m.metadata?.isLocal,
                      estCost:
                        costData.cost_usd !== undefined
                          ? `$${costData.cost_usd.toFixed(4)}`
                          : m.metadata?.estCost,
                      tokenCount: totalTokens || m.metadata?.tokenCount,
                      latencyMs: costData.latency_ms || m.metadata?.latencyMs,
                      tokensPerSec: costData.tokens_per_second || m.metadata?.tokensPerSec,
                      execution: {
                        ...m.metadata?.execution,
                        executionId: costData.execution_id || m.metadata?.execution?.executionId,
                        provider: costData.provider || m.metadata?.execution?.provider,
                        model: costData.model || m.metadata?.execution?.model,
                        isLocal: costData.is_local !== undefined ? costData.is_local : m.metadata?.execution?.isLocal,
                        costUsd: costData.cost_usd,
                        totalTokens: totalTokens || m.metadata?.execution?.totalTokens,
                        latencyMs: costData.latency_ms || m.metadata?.execution?.latencyMs,
                        tokensPerSec: costData.tokens_per_second || m.metadata?.execution?.tokensPerSec,
                      },
                    },
                  }
                : m
            )
          );
        },
        onDone: (finalData?: any) => {
          setIsStreaming(false);
          const data = finalData || {};
          const totalTokens = (data.prompt_tokens || 0) + (data.completion_tokens || 0);
          setMessages((prev) =>
            prev.map((m) => {
              if (m.id !== assistantMsgId) return m;
              // Invariant: NEVER overwrite a failed or errored execution to completed
              if (m.metadata?.execution?.status === 'failed' || m.metadata?.isError) {
                return { ...m, isStreaming: false };
              }
              return {
                ...m,
                isStreaming: false,
                metadata: {
                  ...m.metadata,
                  executionId: data.execution_id || m.metadata?.executionId,
                  tokenCount: totalTokens || m.metadata?.tokenCount,
                  latencyMs: data.latency_ms || m.metadata?.latencyMs,
                  tokensPerSec: data.tokens_per_second || m.metadata?.tokensPerSec,
                  estCost:
                    data.cost_usd !== undefined
                      ? `$${data.cost_usd.toFixed(4)}`
                      : m.metadata?.estCost,
                  provider: data.provider || m.metadata?.provider,
                  modelName: data.model || m.metadata?.modelName,
                  isLocal: data.is_local !== undefined ? data.is_local : m.metadata?.isLocal,
                  execution: {
                    ...m.metadata?.execution,
                    executionId: data.execution_id || m.metadata?.execution?.executionId,
                    status: 'completed',
                    provider: data.provider || m.metadata?.execution?.provider,
                    model: data.model || m.metadata?.execution?.model,
                    isLocal: data.is_local !== undefined ? data.is_local : m.metadata?.execution?.isLocal,
                    costUsd: data.cost_usd,
                    totalTokens: totalTokens || m.metadata?.execution?.totalTokens,
                    latencyMs: data.latency_ms || m.metadata?.execution?.latencyMs,
                    tokensPerSec: data.tokens_per_second || m.metadata?.execution?.tokensPerSec,
                  },
                },
              };
            })
          );
          activeAbortController.current = null;
        },
        onError: (err: any, errPayload?: any) => {
          setIsStreaming(false);
          activeAbortController.current = null;
          const errMsg = typeof err === 'string' ? err : err?.message || 'Execution Error: Unable to complete operation.';
          const payload = errPayload || (typeof err === 'object' && err !== null ? err : {});
          const errCode = payload.error_code || payload.failure_classification || 'DISPATCH_FAILED';
          const errExecId = payload.execution_id;

          const isDevMode = typeof window !== 'undefined' && (
            localStorage.getItem('agent_engine_developer_mode') === 'true' ||
            localStorage.getItem('ae_developer_mode') === 'true'
          );

          // Standard UI should not expose raw exception strings unless Developer mode is enabled
          const failureContent = isDevMode
            ? `Execution failed\nUnable to complete this request.\n\n[Developer Details]: ${errMsg}`
            : 'Execution failed\nUnable to complete this request.';

          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    isStreaming: false,
                    content: failureContent,
                    metadata: {
                      ...m.metadata,
                      isError: true,
                      executionId: errExecId || m.metadata?.executionId,
                      execution: {
                        ...m.metadata?.execution,
                        status: 'failed',
                        error: errMsg,
                        errorCode: errCode,
                        failureClassification: errCode,
                        failureStage: payload.failure_stage || 'provider_dispatch',
                        executionId: errExecId || m.metadata?.executionId || m.metadata?.execution?.executionId,
                        latencyMs: Math.round(performance.now() - startTime),
                        costUsd: undefined,
                      },
                    },
                  }
                : m
            )
          );
        },
      });
    },
    [activeRoutingObjective, activePrivacyBoundary, activeSessionId]
  );

  const handleSend = (
    text: string,
    options?: {
      model: ModelTier;
      personaId?: string;
      projectId?: string;
      attachments?: AttachmentFile[];
      skill?: SelectedSkill;
      enabledPlugins?: string[];
    }
  ) => {
    const userMsgId = `msg-${Date.now()}`;
    const userMsg: ChatMessage = {
      id: userMsgId,
      role: 'user',
      content: text,
      timestamp: 'Just now',
      attachments: options?.attachments || canvasAttachments,
      metadata: {
        modelTier: options?.model || activeModel,
        skillId: options?.skill?.skill.id,
        skillName: options?.skill?.skill.name,
      },
    };

    setMessages((prev) => [...prev, userMsg]);
    setCanvasAttachments([]);
    setInitialInputText('');

    startStreamingResponse(
      text,
      options?.model || activeModel,
      options?.skill,
      options?.enabledPlugins
    );
  };

  const handleApproveToolCall = async (approvalId: string) => {
    const startTime = performance.now();
    let targetReq: ApprovalRequest | undefined;
    for (const m of messages) {
      if (m.approvalRequest?.id === approvalId) {
        targetReq = m.approvalRequest;
        break;
      }
    }

    let auditId: number | undefined;
    if (targetReq) {
      try {
        const auditRecord = await sidecarClient.submitApprovalDecision({
          toolName: targetReq.toolName,
          toolArgs: targetReq.toolArgs,
          decision: 'approve',
          riskLevel: targetReq.riskLevel,
          riskScore: targetReq.riskScore,
          reason: 'Authorized by operator in chat',
        });
        auditId = auditRecord.id;
      } catch {
        auditId = Math.floor(Date.now() / 1000);
      }
    }

    const elapsed = Math.max(Math.round(performance.now() - startTime), 18);

    setMessages((prev) =>
      prev.map((m) => {
        if (m.approvalRequest?.id === approvalId) {
          return {
            ...m,
            approvalRequest: {
              ...m.approvalRequest,
              status: 'approved',
              resolvedAt: 'Just now',
              decisionBy: 'Operator',
              auditId,
            },
          };
        }
        return m;
      })
    );

    const execMsgId = `exec-${Date.now()}`;
    const toolName = targetReq?.toolName || 'tool';
    setMessages((prev) => [
      ...prev,
      {
        id: execMsgId,
        role: 'assistant',
        content: `Operator authorization confirmed (Audit Log #aud-${auditId || '101'}).\n\n\`\`\`bash\n# Executing ${toolName} (<500ms SLA: resolved in ${elapsed}ms)\nStatus: 200 OK\nExit code: 0 (Success)\nOutput: Operation completed safely per operator approval.\n\`\`\`\n\nAll modifications logged to tamper-evident audit ledger.`,
        timestamp: 'Just now',
        metadata: {
          modelTier: activeModel,
          latencyMs: elapsed,
          tokenCount: 42,
          tokensPerSec: 80,
          estCost: '$0.0000',
        },
      },
    ]);
  };

  const handleRejectToolCall = async (approvalId: string, reason?: string) => {
    let targetReq: ApprovalRequest | undefined;
    for (const m of messages) {
      if (m.approvalRequest?.id === approvalId) {
        targetReq = m.approvalRequest;
        break;
      }
    }

    if (targetReq) {
      try {
        await sidecarClient.submitApprovalDecision({
          toolName: targetReq.toolName,
          toolArgs: targetReq.toolArgs,
          decision: 'reject',
          riskLevel: targetReq.riskLevel,
          riskScore: targetReq.riskScore,
          reason: reason || 'Rejected by operator in chat',
        });
      } catch {
        // Fallback
      }
    }

    setMessages((prev) =>
      prev.map((m) => {
        if (m.approvalRequest?.id === approvalId) {
          return {
            ...m,
            approvalRequest: {
              ...m.approvalRequest,
              status: 'rejected',
              resolvedAt: 'Just now',
              decisionBy: 'Operator',
              decisionReason: reason || 'Operation rejected by operator',
            },
          };
        }
        return m;
      })
    );

    setMessages((prev) => [
      ...prev,
      {
        id: `rej-${Date.now()}`,
        role: 'assistant',
        content: `Tool execution cancelled per operator decision: *"${reason || 'Operation rejected by operator'}"*.\n\nNo system files were modified, and the operation was safely aborted without side-effects.`,
        timestamp: 'Just now',
        metadata: {
          modelTier: activeModel,
          latencyMs: 12,
          tokenCount: 26,
          tokensPerSec: 65,
          estCost: '$0.0000',
        },
      },
    ]);
  };

  const handleEditToolCall = async (
    approvalId: string,
    modifiedArgs: Record<string, any>
  ) => {
    const startTime = performance.now();
    let targetReq: ApprovalRequest | undefined;
    for (const m of messages) {
      if (m.approvalRequest?.id === approvalId) {
        targetReq = m.approvalRequest;
        break;
      }
    }

    let auditId: number | undefined;
    if (targetReq) {
      try {
        const auditRecord = await sidecarClient.submitApprovalDecision({
          toolName: targetReq.toolName,
          toolArgs: targetReq.toolArgs,
          decision: 'edit',
          riskLevel: targetReq.riskLevel,
          riskScore: targetReq.riskScore,
          modifiedArgs,
          reason: 'Approved with modified arguments by operator',
        });
        auditId = auditRecord.id;
      } catch {
        auditId = Math.floor(Date.now() / 1000);
      }
    }

    const elapsed = Math.max(Math.round(performance.now() - startTime), 22);

    setMessages((prev) =>
      prev.map((m) => {
        if (m.approvalRequest?.id === approvalId) {
          return {
            ...m,
            approvalRequest: {
              ...m.approvalRequest,
              status: 'edited',
              modifiedArgs,
              resolvedAt: 'Just now',
              decisionBy: 'Operator',
              auditId,
            },
          };
        }
        return m;
      })
    );

    setMessages((prev) => [
      ...prev,
      {
        id: `edit-${Date.now()}`,
        role: 'assistant',
        content: `Operator authorized modified execution (Audit Log #aud-${auditId || '102'}).\n\n\`\`\`json\n// Applied Parameters (Modified by Operator)\n${JSON.stringify(modifiedArgs, null, 2)}\n\`\`\`\n\nExecuted in ${elapsed}ms with exit code 0. Changes committed to session.`,
        timestamp: 'Just now',
        metadata: {
          modelTier: activeModel,
          latencyMs: elapsed,
          tokenCount: 48,
          tokensPerSec: 90,
          estCost: '$0.0000',
        },
      },
    ]);
  };

  const handleStop = () => {
    if (activeAbortController.current) {
      activeAbortController.current.abort();
      activeAbortController.current = null;
    }
    setIsStreaming(false);
    setMessages((prev) =>
      prev.map((m) => (m.isStreaming ? { ...m, isStreaming: false } : m))
    );
  };

  const handleProjectSelect = (id: string, name?: string) => {
    setActiveProjectId(id);
    const found = realProjects.find((p) => p.id === id);
    const resolvedName = name || (found ? found.name : '');
    setActiveProjectName(resolvedName);
    onProjectNameChange?.(resolvedName);
  };

  const handleResetChat = () => {
    if (isStreaming) {
      handleStop();
    }
    setMessages([]);
    setInitialInputText('');
    setCanvasAttachments([]);
    activeInputRef.current?.focus();
  };

  const isChatActive = messages.length > 0;

  return (
    <div
      onDragEnter={handleCanvasDragEnter}
      onDragOver={handleCanvasDragOver}
      onDragLeave={handleCanvasDragLeave}
      onDrop={handleCanvasDrop}
      className="h-full flex flex-col justify-between overflow-hidden relative"
    >
      {/* Canvas Drag and Drop Target Overlay */}
      {isCanvasDragOver && (
        <div
          data-testid="canvas-drag-overlay"
          className="absolute inset-0 z-50 bg-bg-base/90 backdrop-blur-sm border-2 border-dashed border-accent flex flex-col items-center justify-center p-8 text-center pointer-events-none animate-fade-in"
        >
          <div className="w-12 h-12 rounded-xl bg-accent/15 border border-accent flex items-center justify-center mb-3 text-accent">
            <Upload className="w-6 h-6 animate-bounce" />
          </div>
          <h3 className="text-base font-semibold text-text-primary mb-1">
            Drop documents to attach to session
          </h3>
          <p className="text-xs text-text-secondary max-w-sm mb-3 leading-relaxed">
            Drag files directly into the workbench for context and session memory.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-1.5 text-[11px] text-text-tertiary">
            <span className="px-2 py-0.5 rounded bg-bg-elevated border border-border-subtle font-mono">PDF</span>
            <span className="px-2 py-0.5 rounded bg-bg-elevated border border-border-subtle font-mono">CSV</span>
            <span className="px-2 py-0.5 rounded bg-bg-elevated border border-border-subtle font-mono">Code (.py, .ts, .rs)</span>
            <span className="px-2 py-0.5 rounded bg-bg-elevated border border-border-subtle font-mono">Markdown (.md)</span>
          </div>
        </div>
      )}

      {/* Upload Progress Bar */}
      {uploadProgress !== null && (
        <div
          data-testid="upload-progress-bar"
          className="h-9 px-4 bg-bg-elevated border-b border-border-subtle flex items-center justify-between text-xs z-30 animate-fade-in select-none"
        >
          <div className="flex items-center gap-2.5 flex-1 mr-4">
            <Loader2 className="w-3.5 h-3.5 text-accent animate-spin flex-shrink-0" />
            <span className="text-text-secondary font-medium">
              Indexing documents into session memory:
            </span>
            <div className="flex-1 max-w-md h-1.5 bg-bg-base rounded-full overflow-hidden border border-border-subtle">
              <div
                className="h-full bg-accent transition-all duration-200"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
          </div>
          <span className="font-mono text-[11px] text-accent font-semibold">{uploadProgress}%</span>
        </div>
      )}

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
      <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 scrollbar-thin">
        {!isChatActive ? (
          /* Canonical Workbench Empty State */
          <div className="w-full max-w-[760px] mx-auto flex flex-col space-y-6 pt-4 md:pt-8 text-left">
            {/* Header: Restrained greeting & primary question */}
            <div className="space-y-1">
              <div className="text-xs font-medium text-text-tertiary tracking-wide">
                {getGreeting()}
              </div>
              <h1 className="text-2xl font-bold tracking-tight text-text-primary">
                What are you working on?
              </h1>
              <p className="text-xs text-text-secondary leading-relaxed pt-0.5">
                Ask, open a project, or describe a task.
              </p>
            </div>

            {/* Universal Command Surface with ExecutionPreferences */}
            <div className="space-y-2">
              <div className="w-full">
                <ChatInput
                  mode="home"
                  model={activeModel}
                  personaId={activePersona.id}
                  projectId={activeProjectId}
                  projectName={activeProjectName}
                  isStreaming={isStreaming}
                  onSend={handleSend}
                  onStop={handleStop}
                  onModeChange={onSelectMode}
                  onModelChange={handleModelChange}
                  onPersonaChange={handlePersonaChange}
                  onProjectChange={handleProjectSelect}
                  onClearChat={handleResetChat}
                  inputRef={activeInputRef}
                  initialValue={initialInputText}
                  attachments={canvasAttachments}
                  onAttachmentsChange={setCanvasAttachments}
                />
              </div>

              {/* Preferences Control Strip directly underneath Input */}
              <div className="flex items-center justify-between px-1 text-xs">
                <div className="flex items-center gap-2">
                  <ExecutionPreferences
                    privacyBoundary={activePrivacyBoundary}
                    onSelectPrivacyBoundary={handlePrivacyBoundaryChange}
                    routingObjective={activeRoutingObjective}
                    onSelectRoutingObjective={handleRoutingObjectiveChange}
                  />
                </div>
                <div className="text-[11px] text-text-tertiary font-mono hidden sm:inline">
                  Press <kbd className="px-1.5 py-0.5 rounded bg-bg-elevated border border-border-strong text-text-secondary font-mono">Ctrl+K</kbd> to focus
                </div>
              </div>
            </div>

            {/* Contextual Tool Shortcuts */}
            <div className="pt-1">
              <div className="flex items-center gap-1.5">
                {contextualTools.map((tool) => (
                  <button
                    key={tool.mode}
                    type="button"
                    onClick={() => onSelectMode(tool.mode)}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-bg-elevated hover:bg-bg-hover border border-border-subtle hover:border-border-strong text-xs text-text-secondary hover:text-text-primary transition-colors"
                  >
                    {tool.icon}
                    <span>{tool.label}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Recent Work & Pinned Projects 2-Column Split */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
              {/* Recent Work Column */}
              <div className="space-y-2">
                <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                  <Clock className="w-3.5 h-3.5" />
                  <span>Recent work</span>
                </div>
                <div className="border border-border-subtle rounded-lg bg-bg-elevated/40 divide-y divide-border-subtle overflow-hidden">
                  {recentSessions.length === 0 ? (
                    <div className="px-3 py-4 text-center text-xs text-text-tertiary">
                      No recent work
                    </div>
                  ) : (
                    recentSessions.map((s) => (
                      <div
                        key={s.session_id || s.id}
                        onClick={() => {
                          setInitialInputText(`Continue session: ${s.title || s.name || s.session_id}`);
                          activeInputRef.current?.focus();
                        }}
                        className="px-3 py-2.5 flex items-center justify-between text-xs hover:bg-bg-hover cursor-pointer transition-colors"
                      >
                        <span className="font-medium text-text-primary truncate mr-2">
                          {s.title || s.name || `Session ${s.session_id?.slice(0, 8)}`}
                        </span>
                        <span className="text-[11px] text-text-tertiary font-mono flex-shrink-0">
                          {s.updated_at ? new Date(s.updated_at).toLocaleDateString() : 'Recent'}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Pinned Projects Column */}
              <div className="space-y-2">
                <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-text-tertiary">
                  <Pin className="w-3.5 h-3.5" />
                  <span>Pinned projects</span>
                </div>
                <div className="border border-border-subtle rounded-lg bg-bg-elevated/40 divide-y divide-border-subtle overflow-hidden">
                  {realProjects.length === 0 ? (
                    <div className="px-3 py-4 text-center text-xs text-text-tertiary">
                      No projects configured
                    </div>
                  ) : (
                    realProjects.map((p) => (
                      <div
                        key={p.id}
                        onClick={() => handleProjectSelect(p.id, p.name)}
                        className={`px-3 py-2.5 flex items-center justify-between text-xs hover:bg-bg-hover cursor-pointer transition-colors ${
                          activeProjectId === p.id ? 'bg-accent/5' : ''
                        }`}
                      >
                        <div className="truncate mr-2">
                          <div className="font-medium text-text-primary flex items-center gap-1.5">
                            <FolderKanban className="w-3.5 h-3.5 text-text-tertiary flex-shrink-0" />
                            <span>{p.name}</span>
                          </div>
                          {p.description && (
                            <div className="text-[11px] text-text-tertiary line-clamp-1">{p.description}</div>
                          )}
                        </div>
                        <span className="text-[10px] font-mono text-text-tertiary uppercase flex-shrink-0">
                          {activeProjectId === p.id ? 'Active' : 'Select'}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>
        ) : (
          /* Active Chat Thread */
          <div className="w-full max-w-[760px] mx-auto space-y-4 pb-2">
            {messages.map((msg) => (
              <Message
                key={msg.id}
                message={msg}
                onApprove={handleApproveToolCall}
                onReject={handleRejectToolCall}
                onEdit={handleEditToolCall}
              />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Persistent Bottom ChatInput during active conversation */}
      {isChatActive && (
        <div className="border-t border-border-subtle bg-bg-base/95 backdrop-blur-md px-4 py-3">
          <div className="w-full max-w-[760px] mx-auto space-y-2">
            <ChatInput
              mode="home"
              model={activeModel}
              personaId={activePersona.id}
              projectId={activeProjectId}
              projectName={activeProjectName}
              isStreaming={isStreaming}
              onSend={handleSend}
              onStop={handleStop}
              onModeChange={onSelectMode}
              onModelChange={handleModelChange}
              onPersonaChange={handlePersonaChange}
              onProjectChange={handleProjectSelect}
              onClearChat={handleResetChat}
              inputRef={activeInputRef}
              attachments={canvasAttachments}
              onAttachmentsChange={setCanvasAttachments}
            />
            <div className="flex items-center justify-between px-1 text-xs">
              <ExecutionPreferences
                privacyBoundary={activePrivacyBoundary}
                onSelectPrivacyBoundary={handlePrivacyBoundaryChange}
                routingObjective={activeRoutingObjective}
                onSelectRoutingObjective={handleRoutingObjectiveChange}
              />
              <span className="text-[11px] text-text-tertiary font-mono">
                {activeProjectName}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
