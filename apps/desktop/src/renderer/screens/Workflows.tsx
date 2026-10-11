import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  GitBranch,
  Wrench,
  Bot,
  ShieldAlert,
  HelpCircle,
  Layers,
  Combine,
  Play,
  Eye,
  Save,
  CheckCircle2,
  AlertCircle,
  RotateCw,
  ArrowLeft,
  Plus,
  Trash2,
  ZoomIn,
  ZoomOut,
  Maximize2,
  X,
  Search,
  Tag,
  Check,
  ChevronRight,
  FileCode,
  Sparkles,
} from 'lucide-react';
import {
  Mode,
  ModelTier,
  WorkflowDefinition,
  WorkflowNode,
  WorkflowEdge,
  WorkflowNodeType,
  WorkflowRun,
  WorkflowValidationResult,
  PendingGateInfo,
} from '../types';
import { sidecarClient } from '../api/client';

interface WorkflowsProps {
  onSelectMode?: (mode: Mode) => void;
  activeModel?: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
}

const NODE_WIDTH = 210;
const NODE_HEIGHT = 100;

interface NodeTypeMeta {
  type: WorkflowNodeType;
  label: string;
  defaultName: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  badgeBg: string;
  borderActive: string;
}

const PALETTE_NODES: NodeTypeMeta[] = [
  {
    type: 'pipeline',
    label: 'Pipeline',
    defaultName: 'DSPy Module',
    description: 'Compiled DSPy module with micro-steps',
    icon: GitBranch,
    color: 'text-purple-400',
    badgeBg: 'bg-purple-950/60 border-purple-500/40 text-purple-300',
    borderActive: 'border-purple-500',
  },
  {
    type: 'skill',
    label: 'Skill / Tool',
    defaultName: 'Skill Tool',
    description: 'Deterministic tool or executable script',
    icon: Wrench,
    color: 'text-blue-400',
    badgeBg: 'bg-blue-950/60 border-blue-500/40 text-blue-300',
    borderActive: 'border-blue-500',
  },
  {
    type: 'agent',
    label: 'Agent',
    defaultName: 'Autonomous Agent',
    description: 'LLM reasoning agent with prompt & model tier',
    icon: Bot,
    color: 'text-emerald-400',
    badgeBg: 'bg-emerald-950/60 border-emerald-500/40 text-emerald-300',
    borderActive: 'border-emerald-500',
  },
  {
    type: 'gate',
    label: 'Approval Gate',
    defaultName: 'Human Approval Gate',
    description: 'Interactive human review & pause node',
    icon: ShieldAlert,
    color: 'text-amber-400',
    badgeBg: 'bg-amber-950/60 border-amber-500/40 text-amber-300',
    borderActive: 'border-amber-500',
  },
  {
    type: 'condition',
    label: 'Condition',
    defaultName: 'Branch Condition',
    description: 'Branching logic based on upstream outputs',
    icon: HelpCircle,
    color: 'text-orange-400',
    badgeBg: 'bg-orange-950/60 border-orange-500/40 text-orange-300',
    borderActive: 'border-orange-500',
  },
  {
    type: 'parallel',
    label: 'Parallel',
    defaultName: 'Parallel Fan-Out',
    description: 'Concurrent branch execution',
    icon: Layers,
    color: 'text-indigo-400',
    badgeBg: 'bg-indigo-950/60 border-indigo-500/40 text-indigo-300',
    borderActive: 'border-indigo-500',
  },
  {
    type: 'merge',
    label: 'Merge',
    defaultName: 'State Merge',
    description: 'Aggregates outputs from parallel branches',
    icon: Combine,
    color: 'text-teal-400',
    badgeBg: 'bg-teal-950/60 border-teal-500/40 text-teal-300',
    borderActive: 'border-teal-500',
  },
];

const DEFAULT_NEW_WORKFLOW: WorkflowDefinition = {
  id: `wf_${Date.now().toString(36)}`,
  name: 'Custom DAG Workflow',
  description: 'Multi-step orchestrated agent workflow with approval gates',
  version: '1.0.0',
  status: 'active',
  nodes: [
    {
      id: 'step_analyze',
      type: 'agent',
      name: 'Query Analyzer',
      description: 'Parses input requirements and context',
      position: { x: 80, y: 160 },
      config: { model_tier: 'instant' },
      inputs: { query: '$workflow.input.query' },
      outputs: ['plan', 'entities'],
    },
    {
      id: 'step_gate',
      type: 'gate',
      name: 'Safety & Compliance Gate',
      description: 'Requires operator sign-off before high-risk execution',
      position: { x: 380, y: 160 },
      config: { timeout_seconds: 1800 },
      inputs: { plan: '{{step_analyze.plan}}' },
      outputs: ['approved', 'reviewer'],
    },
    {
      id: 'step_execute',
      type: 'skill',
      name: 'Apply Remediation',
      description: 'Applies changes upon operator approval',
      position: { x: 680, y: 90 },
      inputs: { plan: '{{step_analyze.plan}}' },
      outputs: ['result'],
    },
    {
      id: 'step_cancel',
      type: 'skill',
      name: 'Rollback Log',
      description: 'Rolls back and notifies upon rejection',
      position: { x: 680, y: 240 },
      inputs: { reason: 'Operator rejected changes' },
      outputs: ['logged'],
    },
  ],
  edges: [
    { id: 'e1', source: 'step_analyze', target: 'step_gate' },
    { id: 'e2', source: 'step_gate', target: 'step_execute', condition: 'approved' },
    { id: 'e3', source: 'step_gate', target: 'step_cancel', condition: 'false' },
  ],
  tags: ['orchestration', 'safety', 'human-gate'],
};

export const Workflows: React.FC<WorkflowsProps> = () => {
  // Navigation / View state
  const [viewMode, setViewMode] = useState<'list' | 'editor'>('list');
  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTag, setSelectedTag] = useState<string | null>(null);

  // Active workflow in editor
  const [activeWorkflow, setActiveWorkflow] = useState<WorkflowDefinition>(DEFAULT_NEW_WORKFLOW);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [connectingSourceId, setConnectingSourceId] = useState<string | null>(null);

  // Canvas Viewport (Pan & Zoom)
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<{ x: number; y: number }>({ x: 40, y: 40 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  // Node Dragging
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  // Execution & Validation state
  const [, setValidationResult] = useState<WorkflowValidationResult | null>(null);
  const [runResult, setRunResult] = useState<WorkflowRun | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isDryRunning, setIsDryRunning] = useState(false);
  const [pendingGates, setPendingGates] = useState<PendingGateInfo[]>([]);
  const [notification, setNotification] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  // Modals
  const [yamlModalOpen, setYamlModalOpen] = useState(false);
  const [yamlText, setYamlText] = useState('');
  const [runModalOpen, setRunModalOpen] = useState(false);
  const [runInputsJson, setRunInputsJson] = useState('{\n  "query": "Review and patch staging database schema"\n}');

  const canvasRef = useRef<HTMLDivElement>(null);

  // Fetch workflows and pending gates on mount
  useEffect(() => {
    loadWorkflows();
    loadPendingGates();
  }, []);

  const showNotification = (text: string, type: 'success' | 'error' = 'success') => {
    setNotification({ text, type });
    setTimeout(() => setNotification(null), 4000);
  };

  const loadWorkflows = async () => {
    setIsLoadingList(true);
    try {
      const list = await sidecarClient.listWorkflows();
      setWorkflows(list);
    } catch {
      showNotification('Failed to load workflows from sidecar', 'error');
    } finally {
      setIsLoadingList(false);
    }
  };

  const loadPendingGates = async () => {
    try {
      const gates = await sidecarClient.listPendingGates();
      setPendingGates(gates);
    } catch {
      // Non-blocking
    }
  };

  // Node lookup
  const selectedNode = useMemo(
    () => activeWorkflow.nodes.find((n) => n.id === selectedNodeId) || null,
    [activeWorkflow.nodes, selectedNodeId]
  );

  // Filtered workflows for list view
  const filteredWorkflows = useMemo(() => {
    return workflows.filter((wf) => {
      const matchesSearch =
        wf.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (wf.description && wf.description.toLowerCase().includes(searchQuery.toLowerCase())) ||
        wf.id.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesTag = !selectedTag || (wf.tags && wf.tags.includes(selectedTag));
      return matchesSearch && matchesTag;
    });
  }, [workflows, searchQuery, selectedTag]);

  // All unique tags across workflows
  const allTags = useMemo(() => {
    const set = new Set<string>();
    workflows.forEach((w) => w.tags?.forEach((t) => set.add(t)));
    return Array.from(set);
  }, [workflows]);

  // Node position updater
  const updateNodePosition = (nodeId: string, x: number, y: number) => {
    setActiveWorkflow((prev) => ({
      ...prev,
      nodes: prev.nodes.map((n) => (n.id === nodeId ? { ...n, position: { x, y } } : n)),
    }));
  };

  // Canvas pan handlers
  const handleCanvasMouseDown = (e: React.MouseEvent) => {
    if (e.target === canvasRef.current || (e.target as HTMLElement).tagName === 'svg') {
      setSelectedNodeId(null);
      setConnectingSourceId(null);
      setIsPanning(true);
      setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    }
  };

  const handleCanvasMouseMove = (e: React.MouseEvent) => {
    if (isPanning) {
      setPan({ x: e.clientX - panStart.x, y: e.clientY - panStart.y });
    } else if (draggingNodeId) {
      const newX = Math.round((e.clientX - pan.x) / zoom - dragOffset.x);
      const newY = Math.round((e.clientY - pan.y) / zoom - dragOffset.y);
      updateNodePosition(draggingNodeId, Math.max(20, newX), Math.max(20, newY));
    }
  };

  const handleCanvasMouseUp = () => {
    setIsPanning(false);
    setDraggingNodeId(null);
  };

  // Start dragging a node
  const handleNodeMouseDown = (e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation();
    setSelectedNodeId(nodeId);
    const node = activeWorkflow.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    const nx = node.position?.x ?? 50;
    const ny = node.position?.y ?? 50;
    const clickCanvasX = (e.clientX - pan.x) / zoom;
    const clickCanvasY = (e.clientY - pan.y) / zoom;
    setDragOffset({ x: clickCanvasX - nx, y: clickCanvasY - ny });
    setDraggingNodeId(nodeId);
  };

  // Node connection handle click
  const handleOutputHandleClick = (e: React.MouseEvent, nodeId: string) => {
    e.stopPropagation();
    if (connectingSourceId === nodeId) {
      setConnectingSourceId(null);
    } else {
      setConnectingSourceId(nodeId);
      showNotification(`Click another node's input port to connect edge from ${nodeId}`);
    }
  };

  const handleInputHandleClick = (e: React.MouseEvent, targetNodeId: string) => {
    e.stopPropagation();
    if (connectingSourceId && connectingSourceId !== targetNodeId) {
      // Create edge
      const edgeId = `e_${connectingSourceId}_${targetNodeId}_${Date.now().toString(36).slice(-4)}`;
      const newEdge: WorkflowEdge = {
        id: edgeId,
        source: connectingSourceId,
        target: targetNodeId,
      };
      // Check if already exists
      const exists = activeWorkflow.edges.some(
        (e) => e.source === connectingSourceId && e.target === targetNodeId
      );
      if (!exists) {
        setActiveWorkflow((prev) => ({
          ...prev,
          edges: [...prev.edges, newEdge],
        }));
        showNotification(`Connected ${connectingSourceId} → ${targetNodeId}`);
      }
      setConnectingSourceId(null);
    }
  };

  // Add node from palette
  const handleAddNodeFromPalette = (typeMeta: NodeTypeMeta) => {
    const existingCount = activeWorkflow.nodes.filter((n) => n.type === typeMeta.type).length;
    const id = `${typeMeta.type}_${Date.now().toString(36).slice(-4)}`;
    const name = `${typeMeta.label} ${existingCount + 1}`;
    // Position staggered near canvas center
    const x = Math.round((-pan.x + 300) / zoom + (existingCount % 3) * 60);
    const y = Math.round((-pan.y + 150) / zoom + (existingCount % 4) * 40);

    const newNode: WorkflowNode = {
      id,
      type: typeMeta.type,
      name,
      description: typeMeta.description,
      position: { x: Math.max(50, x), y: Math.max(50, y) },
      config: typeMeta.type === 'gate' ? { timeout_seconds: 1800 } : {},
      inputs: {},
      outputs: ['output'],
    };

    setActiveWorkflow((prev) => ({
      ...prev,
      nodes: [...prev.nodes, newNode],
    }));
    setSelectedNodeId(id);
    showNotification(`Added node: ${name}`);
  };

  // Delete selected node
  const handleDeleteNode = (nodeId: string) => {
    setActiveWorkflow((prev) => ({
      ...prev,
      nodes: prev.nodes.filter((n) => n.id !== nodeId),
      edges: prev.edges.filter((e) => e.source !== nodeId && e.target !== nodeId),
    }));
    if (selectedNodeId === nodeId) setSelectedNodeId(null);
    showNotification(`Deleted node: ${nodeId}`);
  };

  // Delete edge
  const handleDeleteEdge = (edgeId: string) => {
    setActiveWorkflow((prev) => ({
      ...prev,
      edges: prev.edges.filter((e) => e.id !== edgeId),
    }));
    showNotification('Edge deleted');
  };

  // Actions: Save, Validate, Dry Run, Run
  const handleSaveWorkflow = async () => {
    try {
      const saved = await sidecarClient.saveWorkflow(activeWorkflow);
      setActiveWorkflow(saved);
      showNotification(`Workflow '${saved.name}' saved successfully!`);
      loadWorkflows();
    } catch (err: any) {
      showNotification(err.message || 'Failed to save workflow', 'error');
    }
  };

  const handleValidateWorkflow = async () => {
    try {
      const res = await sidecarClient.validateWorkflow({ definition_json: activeWorkflow });
      setValidationResult(res);
      if (res.valid) {
        showNotification(`Validation passed! DAG is acyclic (${res.node_count} nodes, ${res.edge_count} edges).`);
      } else {
        showNotification(`Validation failed: ${res.errors.join('; ')}`, 'error');
      }
    } catch (err: any) {
      showNotification(err.message || 'Validation request failed', 'error');
    }
  };

  const handleDryRun = async () => {
    setIsDryRunning(true);
    setRunResult(null);
    try {
      let inputs: Record<string, any> = {};
      try {
        inputs = JSON.parse(runInputsJson);
      } catch {
        inputs = { query: 'Simulated dry run' };
      }
      // Save or ensure workflow exists on backend first
      await sidecarClient.saveWorkflow(activeWorkflow);
      const res = await sidecarClient.dryRunWorkflow(activeWorkflow.id, inputs);
      setRunResult(res);
      showNotification(`Dry run completed in ${res.execution_time_ms.toFixed(1)}ms with $0.00 cost!`);
    } catch (err: any) {
      showNotification(err.message || 'Dry run simulation failed', 'error');
    } finally {
      setIsDryRunning(false);
    }
  };

  const handleExecuteLive = async () => {
    setIsRunning(true);
    setRunResult(null);
    try {
      let inputs: Record<string, any> = {};
      try {
        inputs = JSON.parse(runInputsJson);
      } catch {
        inputs = {};
      }
      await sidecarClient.saveWorkflow(activeWorkflow);
      const res = await sidecarClient.runWorkflow(activeWorkflow.id, inputs);
      setRunResult(res);
      showNotification(`Workflow run started! Run ID: ${res.run_id || (res as any).id}`);
    } catch (err: any) {
      showNotification(err.message || 'Workflow operation failed', 'error');
    } finally {
      setIsRunning(false);
      setRunModalOpen(false);
    }
  };

  // Gate approval actions
  const handleApproveGate = async (workflowId: string, runId: string) => {
    try {
      const res = await sidecarClient.approveWorkflowGate(workflowId, runId, 'operator');
      setRunResult(res);
      showNotification(`Gate approved! Execution resumed to status: ${res.status}`);
      loadPendingGates();
    } catch (err: any) {
      showNotification(err.message || 'Failed to approve gate', 'error');
    }
  };

  const handleRejectGate = async (workflowId: string, runId: string) => {
    try {
      const res = await sidecarClient.rejectWorkflowGate(workflowId, runId, 'operator', 'Manual operator rejection');
      setRunResult(res);
      showNotification(`Gate rejected. Downstream rejection branch executed.`);
      loadPendingGates();
    } catch (err: any) {
      showNotification(err.message || 'Failed to reject gate', 'error');
    }
  };

  // YAML round-trip export / import
  const handleOpenYamlModal = () => {
    // Lossless JSON representation formatted as readable YAML-like JSON for editing
    setYamlText(JSON.stringify(activeWorkflow, null, 2));
    setYamlModalOpen(true);
  };

  const handleApplyYaml = () => {
    try {
      const parsed = JSON.parse(yamlText);
      if (!parsed.id || !parsed.nodes || !parsed.edges) {
        throw new Error('Definition must have id, nodes, and edges');
      }
      setActiveWorkflow(parsed);
      setYamlModalOpen(false);
      showNotification('Workflow definition updated successfully!');
    } catch (err: any) {
      showNotification(`Invalid format: ${err.message}`, 'error');
    }
  };

  // Zoom controls
  const handleZoomIn = () => setZoom((z) => Math.min(2, Math.round((z + 0.15) * 100) / 100));
  const handleZoomOut = () => setZoom((z) => Math.max(0.4, Math.round((z - 0.15) * 100) / 100));
  const handleResetZoom = () => {
    setZoom(1);
    setPan({ x: 40, y: 40 });
  };

  // Helper to determine node execution status from runResult
  const getNodeRunStatus = (nodeId: string) => {
    if (!runResult) return null;
    if (runResult.current_node_id === nodeId && runResult.status === 'waiting_approval') {
      return 'waiting_approval';
    }
    const step = runResult.step_results?.[nodeId];
    if (step) return step.status;
    return null;
  };

  // -------------------------------------------------------------
  // LIST VIEW
  // -------------------------------------------------------------
  if (viewMode === 'list') {
    return (
      <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden">
        {/* Header */}
        <div className="p-6 border-b border-border-subtle bg-bg-surface flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="sr-only">Preview · Runtime not available yet · Coming in R4</span>
              <span className="text-xs text-text-tertiary">ADR-012 Visual DAG Editor</span>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-text-primary flex items-center gap-2">
              <span>Automations & Workflows</span>
            </h1>
            <p className="text-xs text-text-secondary mt-1">
              Visual pipeline DAG designer. Author, validate, and execute durable multi-agent workflows.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                setActiveWorkflow({
                  ...DEFAULT_NEW_WORKFLOW,
                  id: `wf_${Date.now().toString(36)}`,
                  name: `New Workflow ${workflows.length + 1}`,
                });
                setRunResult(null);
                setValidationResult(null);
                setViewMode('editor');
              }}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium shadow-md transition-all flex items-center gap-1.5"
            >
              <Plus className="w-4 h-4" />
              <span>Create Workflow</span>
            </button>
          </div>
        </div>

        {/* Notifications */}
        {notification && (
          <div
            className={`px-6 py-2.5 text-xs flex items-center gap-2 font-medium border-b ${
              notification.type === 'error'
                ? 'bg-red-950/40 text-red-300 border-red-800/50'
                : 'bg-emerald-950/40 text-emerald-300 border-emerald-800/50'
            }`}
          >
            {notification.type === 'error' ? (
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
            ) : (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            )}
            <span>{notification.text}</span>
          </div>
        )}

        {/* Pending Approval Gates Banner */}
        {pendingGates.length > 0 && (
          <div className="mx-6 mt-4 p-4 rounded-xl bg-amber-950/30 border border-amber-500/40 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-400">
                <ShieldAlert className="w-5 h-5 animate-pulse" />
              </div>
              <div>
                <h4 className="text-xs font-semibold text-amber-300">
                  {pendingGates.length} Human Approval Gate{pendingGates.length > 1 ? 's' : ''} Pending Action
                </h4>
                <p className="text-[11px] text-amber-400/80">
                  Execution paused waiting for operator sign-off in pipeline: {pendingGates[0].workflow_name}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => handleApproveGate(pendingGates[0].workflow_id, pendingGates[0].run_id)}
                className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs font-medium flex items-center gap-1 transition-all"
              >
                <Check className="w-3.5 h-3.5" />
                <span>Approve Run</span>
              </button>
              <button
                onClick={() => handleRejectGate(pendingGates[0].workflow_id, pendingGates[0].run_id)}
                className="px-3 py-1 bg-red-600/80 hover:bg-red-600 text-white rounded text-xs font-medium flex items-center gap-1 transition-all"
              >
                <X className="w-3.5 h-3.5" />
                <span>Reject</span>
              </button>
            </div>
          </div>
        )}

        {/* Search and Filters */}
        <div className="px-6 py-4 flex items-center justify-between gap-4">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-text-tertiary absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search workflows by title, tag, or description..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-bg-base border border-border-subtle focus:border-accent rounded-lg pl-9 pr-3 py-1.5 text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none transition-all"
            />
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] text-text-tertiary flex items-center gap-1 mr-1">
              <Tag className="w-3 h-3" /> Tag:
            </span>
            <button
              onClick={() => setSelectedTag(null)}
              className={`px-2.5 py-1 rounded text-[11px] font-medium transition-all ${
                selectedTag === null
                  ? 'bg-accent text-white'
                  : 'bg-bg-elevated text-text-secondary hover:text-text-primary'
              }`}
            >
              All
            </button>
            {allTags.map((tag) => (
              <button
                key={tag}
                onClick={() => setSelectedTag(tag === selectedTag ? null : tag)}
                className={`px-2.5 py-1 rounded text-[11px] font-medium capitalize transition-all ${
                  selectedTag === tag
                    ? 'bg-accent text-white'
                    : 'bg-bg-elevated text-text-secondary hover:text-text-primary'
                }`}
              >
                {tag}
              </button>
            ))}
          </div>
        </div>

        {/* Workflow Cards Grid */}
        <div className="flex-1 overflow-y-auto px-6 pb-8">
          {isLoadingList ? (
            <div className="flex items-center justify-center h-48 text-text-tertiary text-xs gap-2">
              <RotateCw className="w-4 h-4 animate-spin text-accent" />
              <span>Loading workflows...</span>
            </div>
          ) : filteredWorkflows.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-center p-8 border border-dashed border-border-subtle rounded-2xl bg-bg-surface/50">
              <GitBranch className="w-10 h-10 text-text-tertiary mb-3 stroke-[1.5]" />
              <h3 className="text-sm font-semibold text-text-primary">No Workflows Found</h3>
              <p className="text-xs text-text-secondary max-w-sm mt-1 mb-4">
                {searchQuery || selectedTag
                  ? 'No workflows matched your search filters. Try clearing filters.'
                  : 'Create your first DAG workflow or explore built-in audit templates.'}
              </p>
              <button
                onClick={() => {
                  setActiveWorkflow(DEFAULT_NEW_WORKFLOW);
                  setViewMode('editor');
                }}
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-lg text-xs font-medium flex items-center gap-1.5"
              >
                <Plus className="w-4 h-4" />
                <span>Create Workflow</span>
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredWorkflows.map((wf) => (
                <div
                  key={wf.id}
                  className="p-5 rounded-xl bg-bg-surface hover:bg-bg-elevated border border-border-subtle hover:border-border-strong transition-all flex flex-col justify-between group shadow-sm"
                >
                  <div>
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-lg bg-purple-500/10 border border-purple-500/30 flex items-center justify-center text-purple-400">
                          <GitBranch className="w-4 h-4" />
                        </div>
                        <div>
                          <h3 className="text-sm font-bold text-text-primary leading-tight group-hover:text-accent transition-colors">
                            {wf.name}
                          </h3>
                          <span className="text-[10px] font-mono text-text-tertiary">
                            v{wf.version || '1.0.0'} · {wf.id}
                          </span>
                        </div>
                      </div>
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-emerald-950/60 text-emerald-300 border border-emerald-500/30">
                        {wf.status || 'active'}
                      </span>
                    </div>

                    <p className="text-xs text-text-secondary line-clamp-2 mt-2 leading-relaxed">
                      {wf.description || 'No description provided.'}
                    </p>

                    {wf.tags && wf.tags.length > 0 && (
                      <div className="flex items-center gap-1.5 mt-3 flex-wrap">
                        {wf.tags.map((t) => (
                          <span
                            key={t}
                            className="px-2 py-0.5 text-[10px] rounded bg-bg-base border border-border-subtle text-text-tertiary"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="mt-5 pt-3 border-t border-border-subtle flex items-center justify-between">
                    <div className="flex items-center gap-3 text-[11px] text-text-tertiary font-mono">
                      <span>{wf.nodes?.length || 0} nodes</span>
                      <span>·</span>
                      <span>{wf.edges?.length || 0} edges</span>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => {
                          setActiveWorkflow(wf);
                          setRunResult(null);
                          setValidationResult(null);
                          setViewMode('editor');
                        }}
                        className="px-3 py-1 bg-accent/15 hover:bg-accent/25 text-accent border border-accent/30 rounded text-xs font-medium transition-all flex items-center gap-1"
                      >
                        <span>Open Canvas</span>
                        <ChevronRight className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------
  // EDITOR / CANVAS VIEW
  // -------------------------------------------------------------
  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden">
      {/* Top Bar */}
      <div className="h-14 px-4 border-b border-border-subtle bg-bg-surface flex items-center justify-between gap-4 z-20 shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              loadWorkflows();
              setViewMode('list');
            }}
            className="p-1.5 rounded-lg text-text-secondary hover:text-text-primary hover:bg-bg-elevated transition-all flex items-center gap-1 text-xs"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Workflows</span>
          </button>
          <div className="h-4 w-[1px] bg-border-subtle" />

          <div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={activeWorkflow.name}
                onChange={(e) => setActiveWorkflow((prev) => ({ ...prev, name: e.target.value }))}
                className="text-sm font-bold bg-transparent border-b border-transparent hover:border-border-strong focus:border-accent text-text-primary focus:outline-none transition-all px-1 py-0.5"
                placeholder="Workflow Name"
              />
              <span className="px-1.5 py-0.2 rounded text-[10px] font-mono text-text-tertiary bg-bg-elevated border border-border-subtle">
                v{activeWorkflow.version || '1.0.0'}
              </span>
            </div>
          </div>
        </div>

        {/* Top Bar Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleValidateWorkflow}
            title="Validate topological DAG and check for cycles"
            className="px-2.5 py-1.5 rounded-lg text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-bg-elevated border border-border-subtle transition-all flex items-center gap-1.5"
          >
            <CheckCircle2 className="w-3.5 h-3.5 text-blue-400" />
            <span>Validate</span>
          </button>

          <button
            onClick={handleOpenYamlModal}
            title="Lossless YAML representation"
            className="px-2.5 py-1.5 rounded-lg text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-bg-elevated border border-border-subtle transition-all flex items-center gap-1.5"
          >
            <FileCode className="w-3.5 h-3.5 text-text-tertiary" />
            <span>YAML</span>
          </button>

          <div className="h-4 w-[1px] bg-border-subtle" />

          <button
            onClick={handleDryRun}
            disabled={isDryRunning || isRunning}
            title="Simulate DAG execution path without model token cost"
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-cyan-300 bg-cyan-950/40 hover:bg-cyan-950/70 border border-cyan-500/40 transition-all flex items-center gap-1.5"
          >
            {isDryRunning ? <RotateCw className="w-3.5 h-3.5 animate-spin" /> : <Eye className="w-3.5 h-3.5" />}
            <span>Dry Run</span>
          </button>

          <button
            onClick={() => setRunModalOpen(true)}
            disabled={isRunning || isDryRunning}
            title="Execute workflow live through sidecar engine"
            className="px-3.5 py-1.5 rounded-lg text-xs font-medium text-white bg-emerald-600 hover:bg-emerald-500 transition-all shadow-sm flex items-center gap-1.5"
          >
            {isRunning ? <RotateCw className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5 fill-current" />}
            <span>Run DAG</span>
          </button>

          <button
            onClick={handleSaveWorkflow}
            className="px-3.5 py-1.5 rounded-lg text-xs font-medium text-white bg-accent hover:bg-accent-hover transition-all shadow-sm flex items-center gap-1.5"
          >
            <Save className="w-3.5 h-3.5" />
            <span>Save</span>
          </button>
        </div>
      </div>

      {/* Notifications */}
      {notification && (
        <div
          className={`px-4 py-2 text-xs flex items-center gap-2 font-medium border-b shrink-0 z-20 ${
            notification.type === 'error'
              ? 'bg-red-950/50 text-red-300 border-red-800/50'
              : 'bg-emerald-950/50 text-emerald-300 border-emerald-800/50'
          }`}
        >
          {notification.type === 'error' ? (
            <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
          ) : (
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
          )}
          <span>{notification.text}</span>
        </div>
      )}

      {/* Main Workspace Area: Left Palette + Center Canvas + Right Inspector */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Left Palette */}
        <div className="w-56 border-r border-border-subtle bg-bg-surface flex flex-col shrink-0 z-10">
          <div className="p-3 border-b border-border-subtle">
            <h3 className="text-xs font-bold uppercase tracking-wider text-text-tertiary">Node Palette</h3>
            <p className="text-[10px] text-text-secondary mt-0.5">Click to add onto canvas</p>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
            {PALETTE_NODES.map((meta) => {
              const Icon = meta.icon;
              return (
                <button
                  key={meta.type}
                  onClick={() => handleAddNodeFromPalette(meta)}
                  className="w-full text-left p-2.5 rounded-lg bg-bg-elevated hover:bg-bg-hover border border-border-subtle hover:border-border-strong transition-all flex items-start gap-2.5 group shadow-sm"
                >
                  <div className={`p-1.5 rounded-md bg-bg-base border border-border-subtle ${meta.color} shrink-0`}>
                    <Icon className="w-4 h-4" />
                  </div>
                  <div className="overflow-hidden">
                    <div className="text-xs font-semibold text-text-primary group-hover:text-accent transition-colors">
                      {meta.label}
                    </div>
                    <div className="text-[10px] text-text-tertiary line-clamp-1">{meta.description}</div>
                  </div>
                </button>
              );
            })}
          </div>

          <div className="p-3 border-t border-border-subtle bg-bg-elevated/40 text-[10px] text-text-tertiary leading-relaxed">
            <div className="font-semibold text-text-secondary mb-1 flex items-center gap-1">
              <Sparkles className="w-3 h-3 text-accent" />
              <span>Canvas Tips</span>
            </div>
            <p>• Click output port (right) & input port (left) to connect edges.</p>
            <p className="mt-1">• Select nodes to edit inputs & expressions in Inspector.</p>
          </div>
        </div>

        {/* Center Canvas */}
        <div
          ref={canvasRef}
          onMouseDown={handleCanvasMouseDown}
          onMouseMove={handleCanvasMouseMove}
          onMouseUp={handleCanvasMouseUp}
          className="flex-1 bg-bg-base relative overflow-hidden cursor-crosshair select-none"
          style={{
            backgroundImage:
              'radial-gradient(circle, rgba(255,255,255,0.06) 1px, transparent 1px)',
            backgroundSize: `${20 * zoom}px ${20 * zoom}px`,
            backgroundPosition: `${pan.x}px ${pan.y}px`,
          }}
        >
          {/* Zoom / Viewport Controls Floating Bar */}
          <div className="absolute top-4 right-4 z-10 bg-bg-surface/90 backdrop-blur-md border border-border-strong rounded-xl p-1 flex items-center gap-1 shadow-xl">
            <button
              onClick={handleZoomIn}
              className="p-1.5 text-text-secondary hover:text-text-primary hover:bg-bg-elevated rounded-lg transition-all"
              title="Zoom In"
            >
              <ZoomIn className="w-4 h-4" />
            </button>
            <button
              onClick={handleZoomOut}
              className="p-1.5 text-text-secondary hover:text-text-primary hover:bg-bg-elevated rounded-lg transition-all"
              title="Zoom Out"
            >
              <ZoomOut className="w-4 h-4" />
            </button>
            <button
              onClick={handleResetZoom}
              className="px-2 py-1 text-[11px] font-mono text-text-secondary hover:text-text-primary hover:bg-bg-elevated rounded-lg transition-all"
              title="Reset View"
            >
              {Math.round(zoom * 100)}%
            </button>
            <div className="h-4 w-[1px] bg-border-subtle" />
            <button
              onClick={() => {
                // Auto-center nodes
                if (activeWorkflow.nodes.length > 0) {
                  const minX = Math.min(...activeWorkflow.nodes.map((n) => n.position?.x ?? 0));
                  const minY = Math.min(...activeWorkflow.nodes.map((n) => n.position?.y ?? 0));
                  setPan({ x: -minX + 60, y: -minY + 60 });
                  setZoom(1);
                }
              }}
              className="p-1.5 text-text-secondary hover:text-text-primary hover:bg-bg-elevated rounded-lg transition-all"
              title="Fit to Content"
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* SVG Canvas for Edges */}
          <svg
            className="absolute inset-0 w-full h-full pointer-events-none"
            style={{
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              transformOrigin: '0 0',
            }}
          >
            <defs>
              <marker
                id="arrowhead"
                markerWidth="8"
                markerHeight="6"
                refX="7"
                refY="3"
                orient="auto"
              >
                <polygon points="0 0, 8 3, 0 6" fill="rgba(156, 163, 175, 0.7)" />
              </marker>
              <marker
                id="arrowhead-active"
                markerWidth="8"
                markerHeight="6"
                refX="7"
                refY="3"
                orient="auto"
              >
                <polygon points="0 0, 8 3, 0 6" fill="#3b82f6" />
              </marker>
            </defs>

            {activeWorkflow.edges.map((edge) => {
              const src = activeWorkflow.nodes.find((n) => n.id === edge.source);
              const tgt = activeWorkflow.nodes.find((n) => n.id === edge.target);
              if (!src || !tgt) return null;

              const sx = (src.position?.x ?? 0) + NODE_WIDTH;
              const sy = (src.position?.y ?? 0) + NODE_HEIGHT / 2;
              const tx = tgt.position?.x ?? 0;
              const ty = tgt.position?.y ?? 0;
              const dx = Math.max(60, Math.abs(tx - sx) / 2);

              const path = `M ${sx} ${sy} C ${sx + dx} ${sy}, ${tx - dx} ${ty + NODE_HEIGHT / 2}, ${tx} ${ty + NODE_HEIGHT / 2}`;
              const midX = (sx + tx) / 2;
              const midY = (sy + ty + NODE_HEIGHT / 2) / 2;

              return (
                <g key={edge.id} className="pointer-events-auto group">
                  <path
                    d={path}
                    fill="none"
                    stroke="rgba(156, 163, 175, 0.4)"
                    strokeWidth="2"
                    markerEnd="url(#arrowhead)"
                    className="hover:stroke-blue-400 transition-colors"
                  />
                  {edge.condition && (
                    <g transform={`translate(${midX}, ${midY})`}>
                      <rect
                        x="-30"
                        y="-10"
                        width="60"
                        height="20"
                        rx="4"
                        fill="#18181b"
                        stroke="#3f3f46"
                        strokeWidth="1"
                      />
                      <text
                        x="0"
                        y="4"
                        textAnchor="middle"
                        fill="#e4e4e7"
                        fontSize="10"
                        fontFamily="monospace"
                      >
                        {edge.condition}
                      </text>
                    </g>
                  )}
                  {/* Delete Edge Button on Hover */}
                  <g
                    transform={`translate(${midX + (edge.condition ? 35 : 0)}, ${midY - 12})`}
                    className="opacity-0 group-hover:opacity-100 cursor-pointer transition-opacity"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteEdge(edge.id);
                    }}
                  >
                    <circle r="8" fill="#ef4444" />
                    <text x="0" y="3" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="bold">
                      ×
                    </text>
                  </g>
                </g>
              );
            })}
          </svg>

          {/* HTML Nodes Canvas Layer */}
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              transformOrigin: '0 0',
            }}
          >
            {activeWorkflow.nodes.map((node) => {
              const meta = PALETTE_NODES.find((m) => m.type === node.type) || PALETTE_NODES[0];
              const Icon = meta.icon;
              const isSelected = selectedNodeId === node.id;
              const isConnecting = connectingSourceId === node.id;
              const runStatus = getNodeRunStatus(node.id);

              return (
                <div
                  key={node.id}
                  onMouseDown={(e) => handleNodeMouseDown(e, node.id)}
                  style={{
                    transform: `translate(${node.position?.x ?? 0}px, ${node.position?.y ?? 0}px)`,
                    width: `${NODE_WIDTH}px`,
                    height: `${NODE_HEIGHT}px`,
                  }}
                  className={`absolute pointer-events-auto rounded-xl bg-bg-surface border-2 shadow-lg transition-shadow cursor-grab active:cursor-grabbing flex flex-col justify-between p-3 select-none ${
                    isSelected
                      ? 'border-accent ring-2 ring-accent/30 shadow-accent/20'
                      : isConnecting
                      ? 'border-amber-400 ring-2 ring-amber-400/30'
                      : runStatus === 'completed'
                      ? 'border-emerald-500 shadow-emerald-500/10'
                      : runStatus === 'waiting_approval'
                      ? 'border-amber-400 animate-pulse'
                      : runStatus === 'failed'
                      ? 'border-red-500 shadow-red-500/10'
                      : 'border-border-subtle hover:border-border-strong'
                  }`}
                >
                  {/* Left Input Port */}
                  <div
                    onClick={(e) => handleInputHandleClick(e, node.id)}
                    title="Input Port (Click here to connect)"
                    className="absolute -left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 rounded-full bg-bg-elevated border-2 border-border-strong hover:border-accent hover:bg-accent hover:scale-125 transition-all cursor-pointer flex items-center justify-center"
                  >
                    <div className="w-1.5 h-1.5 rounded-full bg-border-strong" />
                  </div>

                  {/* Right Output Port */}
                  <div
                    onClick={(e) => handleOutputHandleClick(e, node.id)}
                    title="Output Port (Click to start connection)"
                    className={`absolute -right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 rounded-full border-2 transition-all cursor-pointer flex items-center justify-center ${
                      connectingSourceId === node.id
                        ? 'bg-amber-400 border-amber-500 scale-125'
                        : 'bg-bg-elevated border-border-strong hover:border-accent hover:bg-accent hover:scale-125'
                    }`}
                  >
                    <div className="w-1.5 h-1.5 rounded-full bg-border-strong" />
                  </div>

                  {/* Node Header */}
                  <div className="flex items-center justify-between gap-1">
                    <div className="flex items-center gap-1.5 overflow-hidden">
                      <div className={`p-1 rounded bg-bg-base border border-border-subtle ${meta.color}`}>
                        <Icon className="w-3.5 h-3.5" />
                      </div>
                      <span className="text-xs font-bold text-text-primary truncate">{node.name}</span>
                    </div>

                    <span className={`px-1.5 py-0.5 rounded text-[9px] font-mono uppercase ${meta.badgeBg}`}>
                      {node.type}
                    </span>
                  </div>

                  {/* Node Description / Subtitle */}
                  <div className="text-[10px] text-text-secondary line-clamp-1 mt-1">
                    {node.description || 'No description'}
                  </div>

                  {/* Node Footer Badges */}
                  <div className="pt-2 border-t border-border-subtle flex items-center justify-between text-[10px] text-text-tertiary">
                    <span className="font-mono">{node.id}</span>
                    {runStatus && (
                      <span
                        className={`px-1.5 py-0.2 rounded font-mono font-medium ${
                          runStatus === 'completed'
                            ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-500/30'
                            : runStatus === 'waiting_approval'
                            ? 'bg-amber-950/60 text-amber-300 border border-amber-500/30'
                            : 'bg-red-950/60 text-red-300 border border-red-500/30'
                        }`}
                      >
                        {runStatus}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Inspector Panel */}
        <div className="w-72 border-l border-border-subtle bg-bg-surface flex flex-col shrink-0 z-10">
          <div className="p-3 border-b border-border-subtle flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wider text-text-tertiary">Inspector</h3>
            {selectedNode && (
              <button
                onClick={() => handleDeleteNode(selectedNode.id)}
                className="p-1 rounded text-red-400 hover:bg-red-950/40 transition-colors"
                title="Delete Node"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {selectedNode ? (
              <>
                {/* Node ID */}
                <div>
                  <label className="text-[11px] font-semibold text-text-tertiary uppercase">Node ID</label>
                  <input
                    type="text"
                    value={selectedNode.id}
                    readOnly
                    className="w-full mt-1 bg-bg-base border border-border-subtle rounded-lg px-2.5 py-1 text-xs font-mono text-text-secondary cursor-not-allowed"
                  />
                </div>

                {/* Node Name */}
                <div>
                  <label className="text-[11px] font-semibold text-text-secondary">Node Name</label>
                  <input
                    type="text"
                    value={selectedNode.name}
                    onChange={(e) => {
                      const val = e.target.value;
                      setActiveWorkflow((prev) => ({
                        ...prev,
                        nodes: prev.nodes.map((n) => (n.id === selectedNode.id ? { ...n, name: val } : n)),
                      }));
                    }}
                    className="w-full mt-1 bg-bg-base border border-border-subtle focus:border-accent rounded-lg px-2.5 py-1 text-xs text-text-primary focus:outline-none transition-all"
                  />
                </div>

                {/* Node Description */}
                <div>
                  <label className="text-[11px] font-semibold text-text-secondary">Description</label>
                  <textarea
                    rows={2}
                    value={selectedNode.description || ''}
                    onChange={(e) => {
                      const val = e.target.value;
                      setActiveWorkflow((prev) => ({
                        ...prev,
                        nodes: prev.nodes.map((n) => (n.id === selectedNode.id ? { ...n, description: val } : n)),
                      }));
                    }}
                    className="w-full mt-1 bg-bg-base border border-border-subtle focus:border-accent rounded-lg px-2.5 py-1 text-xs text-text-primary focus:outline-none transition-all"
                  />
                </div>

                {/* Node Type */}
                <div>
                  <label className="text-[11px] font-semibold text-text-secondary">Node Type</label>
                  <select
                    value={selectedNode.type}
                    onChange={(e) => {
                      const val = e.target.value as WorkflowNodeType;
                      setActiveWorkflow((prev) => ({
                        ...prev,
                        nodes: prev.nodes.map((n) => (n.id === selectedNode.id ? { ...n, type: val } : n)),
                      }));
                    }}
                    className="w-full mt-1 bg-bg-base border border-border-subtle focus:border-accent rounded-lg px-2.5 py-1 text-xs text-text-primary focus:outline-none transition-all capitalize"
                  >
                    {PALETTE_NODES.map((p) => (
                      <option key={p.type} value={p.type}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Node Inputs Mapping */}
                <div>
                  <label className="text-[11px] font-semibold text-text-secondary">Inputs Mapping (JSON)</label>
                  <textarea
                    rows={3}
                    value={JSON.stringify(selectedNode.inputs || {}, null, 2)}
                    onChange={(e) => {
                      try {
                        const parsed = JSON.parse(e.target.value);
                        setActiveWorkflow((prev) => ({
                          ...prev,
                          nodes: prev.nodes.map((n) => (n.id === selectedNode.id ? { ...n, inputs: parsed } : n)),
                        }));
                      } catch {
                        // ignore syntax error while typing
                      }
                    }}
                    className="w-full mt-1 bg-bg-base border border-border-subtle font-mono text-[11px] text-text-primary rounded-lg p-2 focus:outline-none focus:border-accent"
                  />
                  <span className="text-[10px] text-text-tertiary">
                    Use Mustache binding like <code className="text-accent">{`{{upstream_id.output}}`}</code>
                  </span>
                </div>

                {/* Node Config */}
                <div>
                  <label className="text-[11px] font-semibold text-text-secondary">Config / Options (JSON)</label>
                  <textarea
                    rows={3}
                    value={JSON.stringify(selectedNode.config || {}, null, 2)}
                    onChange={(e) => {
                      try {
                        const parsed = JSON.parse(e.target.value);
                        setActiveWorkflow((prev) => ({
                          ...prev,
                          nodes: prev.nodes.map((n) => (n.id === selectedNode.id ? { ...n, config: parsed } : n)),
                        }));
                      } catch {
                        // ignore syntax error while typing
                      }
                    }}
                    className="w-full mt-1 bg-bg-base border border-border-subtle font-mono text-[11px] text-text-primary rounded-lg p-2 focus:outline-none focus:border-accent"
                  />
                </div>

                {/* Output Keys */}
                <div>
                  <label className="text-[11px] font-semibold text-text-secondary">Output Declarations</label>
                  <div className="flex flex-wrap gap-1.5 mt-1.5">
                    {selectedNode.outputs?.map((out, i) => (
                      <span
                        key={i}
                        className="px-2 py-0.5 rounded bg-bg-base border border-border-subtle text-[10px] font-mono text-text-secondary"
                      >
                        {out}
                      </span>
                    )) || <span className="text-[10px] text-text-tertiary">None declared</span>}
                  </div>
                </div>
              </>
            ) : (
              <div className="flex flex-col items-center justify-center h-48 text-center text-text-tertiary text-xs">
                <Wrench className="w-8 h-8 stroke-[1.5] mb-2 opacity-50" />
                <p>Select a node on the canvas to inspect and configure parameters.</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Execution Results Drawer (Bottom) */}
      {runResult && (
        <div className="h-44 border-t border-border-subtle bg-bg-surface flex flex-col shrink-0 z-20">
          <div className="px-4 py-2 border-b border-border-subtle bg-bg-elevated/40 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-xs font-bold text-text-primary">Execution Output</span>
              <span
                className={`px-2 py-0.5 rounded text-[10px] font-mono uppercase ${
                  runResult.status === 'completed'
                    ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-500/30'
                    : runResult.status === 'waiting_approval'
                    ? 'bg-amber-950/60 text-amber-300 border border-amber-500/30 animate-pulse'
                    : 'bg-red-950/60 text-red-300 border border-red-500/30'
                }`}
              >
                {runResult.status}
              </span>
              <span className="text-[11px] text-text-tertiary font-mono">
                Run ID: {runResult.run_id} · Cost: ${runResult.total_cost_usd.toFixed(4)} · Time: {runResult.execution_time_ms.toFixed(1)}ms
              </span>
            </div>

            <button
              onClick={() => setRunResult(null)}
              className="p-1 rounded text-text-tertiary hover:text-text-primary"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          <div className="flex-1 overflow-x-auto p-3 flex gap-3">
            {Object.entries(runResult.step_results || {}).map(([nid, step]) => (
              <div
                key={nid}
                className="w-56 p-2.5 rounded-lg bg-bg-elevated border border-border-subtle shrink-0 flex flex-col justify-between text-xs"
              >
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-bold text-text-primary truncate">{nid}</span>
                    <span className="text-[10px] font-mono text-emerald-400">{step.status}</span>
                  </div>
                  <div className="text-[10px] font-mono text-text-tertiary truncate">
                    Type: {step.node_type} · ${(step.cost_usd || 0).toFixed(4)}
                  </div>
                </div>
                <div className="mt-2 pt-1 border-t border-border-subtle text-[10px] font-mono text-text-secondary truncate">
                  Output: {JSON.stringify(step.outputs || {})}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* YAML Import / Export Modal */}
      {yamlModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-bg-surface border border-border-strong rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
            <div className="px-5 py-4 border-b border-border-subtle flex items-center justify-between">
              <h3 className="text-sm font-bold text-text-primary flex items-center gap-2">
                <FileCode className="w-4 h-4 text-accent" />
                <span>Lossless Workflow Definition (Round-Trip)</span>
              </h3>
              <button
                onClick={() => setYamlModalOpen(false)}
                className="p-1 rounded text-text-tertiary hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 p-4 overflow-hidden">
              <textarea
                value={yamlText}
                onChange={(e) => setYamlText(e.target.value)}
                className="w-full h-96 bg-bg-base border border-border-subtle font-mono text-xs text-text-primary rounded-lg p-3 focus:outline-none focus:border-accent"
              />
            </div>

            <div className="px-5 py-3 border-t border-border-subtle bg-bg-elevated/50 flex items-center justify-between">
              <span className="text-[11px] text-text-tertiary">
                Preserves all node positions, edges, conditions, and gate metadata.
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(yamlText);
                    showNotification('Copied definition to clipboard!');
                  }}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary hover:text-text-primary bg-bg-elevated border border-border-subtle"
                >
                  Copy
                </button>
                <button
                  onClick={handleApplyYaml}
                  className="px-4 py-1.5 rounded-lg text-xs font-medium text-white bg-accent hover:bg-accent-hover"
                >
                  Apply to Canvas
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Run Inputs Modal */}
      {runModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md bg-bg-surface border border-border-strong rounded-2xl shadow-2xl overflow-hidden flex flex-col">
            <div className="px-5 py-4 border-b border-border-subtle flex items-center justify-between">
              <h3 className="text-sm font-bold text-text-primary flex items-center gap-2">
                <Play className="w-4 h-4 text-emerald-400 fill-current" />
                <span>Execute Live Workflow</span>
              </h3>
              <button
                onClick={() => setRunModalOpen(false)}
                className="p-1 rounded text-text-tertiary hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-5 space-y-3">
              <label className="text-xs font-semibold text-text-secondary">
                Workflow Inputs (JSON)
              </label>
              <textarea
                rows={5}
                value={runInputsJson}
                onChange={(e) => setRunInputsJson(e.target.value)}
                className="w-full bg-bg-base border border-border-subtle font-mono text-xs text-text-primary rounded-lg p-3 focus:outline-none focus:border-accent"
              />
              <p className="text-[11px] text-text-tertiary">
                These inputs will populate the root <code className="text-accent">$workflow.input</code> state.
              </p>
            </div>

            <div className="px-5 py-3 border-t border-border-subtle bg-bg-elevated/50 flex items-center justify-end gap-2">
              <button
                onClick={() => setRunModalOpen(false)}
                className="px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary hover:text-text-primary bg-bg-elevated border border-border-subtle"
              >
                Cancel
              </button>
              <button
                onClick={handleExecuteLive}
                disabled={isRunning}
                className="px-4 py-1.5 rounded-lg text-xs font-medium text-white bg-emerald-600 hover:bg-emerald-500 flex items-center gap-1.5"
              >
                {isRunning ? <RotateCw className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5 fill-current" />}
                <span>Start Run</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
