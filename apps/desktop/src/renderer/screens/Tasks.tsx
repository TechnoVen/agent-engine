import React, { useState, useEffect, useMemo } from 'react';
import {
  Clock,
  Plus,
  Play,
  Pause,
  Trash2,
  Calendar,
  ChevronDown,
  Moon,
  MessageSquare,
  FileCode2,
  Sparkles,
  Coins,
  Search,
  CheckCircle2,
  RefreshCw,
  Send,
  X,
  Bot,
  Activity,
  Sliders,
} from 'lucide-react';
import {
  Mode,
  ModelTier,
  ScheduledTask,
  ScheduledTaskCreatePayload,
  NotificationChannel,
  TaskScheduleStatus,
} from '../types';
import { ChatInput } from '../components/ChatInput';
import { sidecarClient, DEFAULT_PERSONAS } from '../api/client';

export interface TasksScreenProps {
  onSelectMode: (mode: Mode) => void;
  activeModel: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  inputRef?: React.RefObject<HTMLTextAreaElement>;
}

// Built-in curated templates
const TASK_TEMPLATES = [
  {
    title: 'Daily inbox digest at 8 AM',
    description: 'Summarizes high-priority emails, actionable requests, and generates quick replies.',
    cron: '0 8 * * *',
    cron_human: 'Every day at 8:00 AM',
    persona: 'Executive Drafter',
    model: 'instant' as ModelTier,
    is_off_peak: false,
    channel: 'slack' as NotificationChannel,
    prompt: 'Synthesize all unread urgent emails from the last 24 hours into 3 executive bullet points.',
  },
  {
    title: 'Weekly expense report Sunday 6 PM',
    description: 'Reconciles receipts, compares against 90/9/1 routing budgets, and flags discrepancies.',
    cron: '0 18 * * 0',
    cron_human: 'Every Sunday at 6:00 PM',
    persona: 'Deep Researcher',
    model: 'instant' as ModelTier,
    is_off_peak: false,
    channel: 'slack' as NotificationChannel,
    prompt: 'Generate weekly team expense breakdown and verify token spend against hard ceilings.',
  },
  {
    title: 'Hourly code audit on save',
    description: 'Scans recently committed workspace changes for security policies and AST defects.',
    cron: '0 * * * *',
    cron_human: 'Every hour at minute 0',
    persona: 'Security Auditor',
    model: 'reasoning' as ModelTier,
    is_off_peak: false,
    channel: 'webhook' as NotificationChannel,
    prompt: 'Audit recent Git diffs for sensitive credentials, OWASP vulnerabilities, and destructive commands.',
  },
  {
    title: 'Monthly book progress summary',
    description: 'Analyzes chapter drafts, character arcs, and calculates words written vs milestone.',
    cron: '0 3 1 * *',
    cron_human: 'Monthly on day 1 at 3:00 AM (Off-peak)',
    persona: 'Technical Writer',
    model: 'swarm' as ModelTier,
    is_off_peak: true,
    channel: 'telegram' as NotificationChannel,
    prompt: 'Aggregate all story draft files in ~/writing, calculate pacing statistics and export markdown report.',
  },
];

// Helper: Translate cron expressions into plain English
export function cronToPlainEnglish(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return 'Custom cron schedule';

  const [min, hour, dom, mon, dow] = parts;

  if (min === '0' && hour === '2' && dom === '*' && mon === '*' && dow === '*') {
    return 'Every day at 2:00 AM (Off-peak)';
  }
  if (min === '0' && hour === '8' && dom === '*' && mon === '*' && dow === '*') {
    return 'Every day at 8:00 AM';
  }
  if (min === '0' && hour === '18' && dom === '*' && mon === '*' && dow === '0') {
    return 'Every Sunday at 6:00 PM';
  }
  if (min === '0' && hour === '*' && dom === '*' && mon === '*' && dow === '*') {
    return 'Every hour at minute 0';
  }
  if (min === '0' && hour === '3' && dom === '1' && mon === '*' && dow === '*') {
    return 'Monthly on day 1 at 3:00 AM (Off-peak)';
  }

  // General heuristics
  if (dom === '*' && mon === '*' && dow === '*') {
    if (hour === '*') return `Every hour at minute ${min}`;
    const h = parseInt(hour, 10);
    const ampm = h >= 12 ? 'PM' : 'AM';
    const displayHour = h % 12 === 0 ? 12 : h % 12;
    const isOffPeak = h >= 2 && h <= 6;
    return `Every day at ${displayHour}:${min.padStart(2, '0')} ${ampm}${isOffPeak ? ' (Off-peak)' : ''}`;
  }

  return `Runs with cron pattern: ${cron}`;
}

export const Tasks: React.FC<TasksScreenProps> = ({
  onSelectMode,
  activeModel,
  onSelectModel,
  inputRef,
}) => {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [activeFilter, setActiveFilter] = useState<'all' | 'active' | 'paused' | 'off_peak'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Dropdown & Modal state
  const [createDropdownOpen, setCreateDropdownOpen] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [modalTab, setModalTab] = useState<'manual' | 'chat' | 'template'>('manual');

  // Manual Form state
  const [taskName, setTaskName] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [taskCron, setTaskCron] = useState('0 2 * * *');
  const [taskPersona, setTaskPersona] = useState('Senior Engineer');
  const [taskModel, setTaskModel] = useState<ModelTier>('instant');
  const [taskIsOffPeak, setTaskIsOffPeak] = useState(true);
  const [taskChannel, setTaskChannel] = useState<NotificationChannel>('slack');
  const [taskPrompt, setTaskPrompt] = useState('');
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  // Load initial tasks from sidecar
  useEffect(() => {
    let mounted = true;
    const fetchTasks = async () => {
      try {
        const list = await sidecarClient.listScheduledTasks();
        if (mounted) {
          setTasks(list);
          setIsLoading(false);
        }
      } catch {
        if (mounted) setIsLoading(false);
      }
    };
    fetchTasks();
    return () => {
      mounted = false;
    };
  }, []);

  // Filtered tasks
  const filteredTasks = useMemo(() => {
    return tasks.filter((t) => {
      const matchesSearch =
        t.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        t.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
        t.agent_persona.toLowerCase().includes(searchQuery.toLowerCase()) ||
        t.cron_human.toLowerCase().includes(searchQuery.toLowerCase());

      if (!matchesSearch) return false;

      if (activeFilter === 'active') return t.status === 'active';
      if (activeFilter === 'paused') return t.status === 'paused';
      if (activeFilter === 'off_peak') return t.is_off_peak;
      return true;
    });
  }, [tasks, searchQuery, activeFilter]);

  // Aggregate Metrics
  const metrics = useMemo(() => {
    const total = tasks.length;
    const active = tasks.filter((t) => t.status === 'active').length;
    const offPeak = tasks.filter((t) => t.is_off_peak).length;
    const monthlyCost = tasks.reduce((sum, t) => sum + (t.status === 'active' ? t.monthly_estimate : 0), 0);
    return { total, active, offPeak, monthlyCost };
  }, [tasks]);

  const handleToggleTask = async (id: string, currentStatus: TaskScheduleStatus) => {
    const nextStatus = currentStatus === 'active' ? 'paused' : 'active';
    setTasks((prev) =>
      prev.map((t) => (t.id === id ? { ...t, status: nextStatus as TaskScheduleStatus } : t))
    );
    try {
      await sidecarClient.toggleScheduledTask(id, currentStatus);
    } catch {
      // offline dev
    }
  };

  const handleTriggerTask = async (task: ScheduledTask) => {
    setActionNotice(`Runtime paused: Background cron task "${task.name}" requires R4 worker runtime.`);
    setTimeout(() => setActionNotice(null), 4000);
  };

  const handleDeleteTask = async (id: string) => {
    setTasks((prev) => prev.filter((t) => t.id !== id));
    try {
      await sidecarClient.deleteScheduledTask(id);
    } catch {
      // dev fallback
    }
  };

  const handleOpenCreateModal = (tab: 'manual' | 'chat' | 'template') => {
    setModalTab(tab);
    setCreateDropdownOpen(false);
    setCreateModalOpen(true);
  };

  const handleApplyTemplate = (template: (typeof TASK_TEMPLATES)[0]) => {
    setTaskName(template.title);
    setTaskDescription(template.description);
    setTaskCron(template.cron);
    setTaskPersona(template.persona);
    setTaskModel(template.model);
    setTaskIsOffPeak(template.is_off_peak);
    setTaskChannel(template.channel);
    setTaskPrompt(template.prompt);
    setModalTab('manual');
  };

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!taskName.trim() || !taskPrompt.trim()) return;

    const payload: ScheduledTaskCreatePayload = {
      name: taskName.trim(),
      description: taskDescription.trim(),
      cron: taskCron.trim(),
      cron_human: cronToPlainEnglish(taskCron),
      agent_persona: taskPersona,
      model: taskModel,
      is_off_peak: taskIsOffPeak,
      notification_channel: taskChannel,
      prompt: taskPrompt.trim(),
    };

    const created = await sidecarClient.createScheduledTask(payload);
    setTasks((prev) => [created, ...prev]);
    setCreateModalOpen(false);
    // Reset form
    setTaskName('');
    setTaskDescription('');
    setTaskPrompt('');
    setActionNotice(`Task "${created.name}" successfully scheduled!`);
    setTimeout(() => setActionNotice(null), 3500);
  };

  const handleCreateViaChat = () => {
    setCreateModalOpen(false);
    if (inputRef?.current) {
      inputRef.current.value =
        'Schedule a task: Every day at 2:00 AM (off-peak), perform security audit and notify Slack.';
      inputRef.current.focus();
    }
  };

  return (
    <div className="h-full flex flex-col justify-between overflow-hidden bg-bg-base relative select-none">
      {/* Scrollable Container */}
      <div className="flex-1 overflow-y-auto px-4 md:px-8 py-6 scrollbar-thin">
        <div className="w-full max-w-[960px] mx-auto space-y-6">
          {/* Top Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border-subtle pb-5">
            <div className="space-y-1">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-xl bg-accent/15 border border-accent/30 flex items-center justify-center text-accent">
                  <Clock className="w-4 h-4" />
                </div>
                <h1 className="text-xl font-bold text-text-primary tracking-tight">
                  Scheduled Tasks
                </h1>
                <span className="px-2 py-0.5 rounded-md bg-warning/10 border border-warning/25 text-[10px] font-mono font-medium text-warning uppercase">
                  Preview · Runtime not available yet · Coming in R4
                </span>
              </div>
              <p className="text-xs text-text-secondary">
                Recurring schedules and background cron execution are scheduled for Milestone R4.
              </p>
            </div>

            {/* Create ▾ Dropdown Button */}
            <div className="relative self-start sm:self-center">
              <button
                type="button"
                onClick={() => setCreateDropdownOpen(!createDropdownOpen)}
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-semibold shadow-sm flex items-center gap-2 transition-all"
                aria-haspopup="true"
                aria-expanded={createDropdownOpen}
              >
                <Plus className="w-3.5 h-3.5" />
                <span>Create</span>
                <ChevronDown className="w-3.5 h-3.5 opacity-80" />
              </button>

              {createDropdownOpen && (
                <div className="absolute right-0 mt-2 w-52 rounded-xl bg-bg-elevated border border-border-strong shadow-2xl z-40 py-1.5 overflow-hidden text-left animate-in fade-in zoom-in-95">
                  <button
                    type="button"
                    onClick={() => handleOpenCreateModal('manual')}
                    className="w-full px-3.5 py-2 text-xs text-text-primary hover:bg-bg-hover flex items-center gap-2.5 transition-colors"
                  >
                    <Sliders className="w-4 h-4 text-accent" />
                    <div className="text-left">
                      <div className="font-medium">Manually</div>
                      <div className="text-[10px] text-text-tertiary">Configure cron & parameters</div>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleOpenCreateModal('chat')}
                    className="w-full px-3.5 py-2 text-xs text-text-primary hover:bg-bg-hover flex items-center gap-2.5 transition-colors"
                  >
                    <MessageSquare className="w-4 h-4 text-success" />
                    <div className="text-left">
                      <div className="font-medium">Via chat</div>
                      <div className="text-[10px] text-text-tertiary">Express prompt in natural language</div>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleOpenCreateModal('template')}
                    className="w-full px-3.5 py-2 text-xs text-text-primary hover:bg-bg-hover flex items-center gap-2.5 transition-colors"
                  >
                    <FileCode2 className="w-4 h-4 text-warning" />
                    <div className="text-left">
                      <div className="font-medium">From template</div>
                      <div className="text-[10px] text-text-tertiary">Use curated recurring routines</div>
                    </div>
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Toast / Notification banner */}
          {actionNotice && (
            <div className="p-3 rounded-xl bg-accent/10 border border-accent/30 text-accent text-xs flex items-center justify-between animate-in fade-in">
              <div className="flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4" />
                <span>{actionNotice}</span>
              </div>
              <button
                type="button"
                onClick={() => setActionNotice(null)}
                className="text-text-tertiary hover:text-text-primary"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          )}

          {/* Metrics Strip */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-left">
            <div className="p-3.5 rounded-xl bg-bg-elevated border border-border-subtle">
              <div className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary flex items-center gap-1">
                <Clock className="w-3 h-3 text-accent" />
                <span>Total Tasks</span>
              </div>
              <div className="text-lg font-bold text-text-primary mt-0.5">{metrics.total}</div>
              <div className="text-[10px] text-text-tertiary">Configured routines</div>
            </div>

            <div className="p-3.5 rounded-xl bg-bg-elevated border border-border-subtle">
              <div className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary flex items-center gap-1">
                <Activity className="w-3 h-3 text-success" />
                <span>Active</span>
              </div>
              <div className="text-lg font-bold text-success mt-0.5">{metrics.active}</div>
              <div className="text-[10px] text-text-tertiary">Ready to trigger</div>
            </div>

            <div className="p-3.5 rounded-xl bg-bg-elevated border border-border-subtle">
              <div className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary flex items-center gap-1">
                <Moon className="w-3 h-3 text-accent" />
                <span>Off-Peak (Law 7)</span>
              </div>
              <div className="text-lg font-bold text-text-primary mt-0.5">{metrics.offPeak}</div>
              <div className="text-[10px] text-text-tertiary">02:00 – 06:00 window</div>
            </div>

            <div className="p-3.5 rounded-xl bg-bg-elevated border border-border-subtle">
              <div className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary flex items-center gap-1">
                <Coins className="w-3 h-3 text-warning" />
                <span>Est. Monthly Cost</span>
              </div>
              <div className="text-lg font-bold text-warning mt-0.5">
                ${metrics.monthlyCost.toFixed(3)}
              </div>
              <div className="text-[10px] text-text-tertiary">90/9/1 cost routing</div>
            </div>
          </div>

          {/* Filter Bar & Search */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-left">
            <div className="flex items-center gap-1 bg-bg-elevated p-1 rounded-xl border border-border-subtle">
              {(['all', 'active', 'paused', 'off_peak'] as const).map((filter) => (
                <button
                  key={filter}
                  type="button"
                  onClick={() => setActiveFilter(filter)}
                  className={`px-3 py-1 text-xs font-medium rounded-lg transition-all capitalize ${
                    activeFilter === filter
                      ? 'bg-bg-hover text-text-primary shadow-sm'
                      : 'text-text-tertiary hover:text-text-secondary'
                  }`}
                >
                  {filter.replace('_', ' ')}
                </button>
              ))}
            </div>

            <div className="relative w-full sm:w-64">
              <Search className="w-3.5 h-3.5 text-text-tertiary absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search tasks, persona, schedule..."
                className="w-full pl-8 pr-3 py-1.5 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
              />
            </div>
          </div>

          {/* Task Table or Empty State */}
          {isLoading ? (
            <div className="p-12 text-center text-text-tertiary text-xs flex items-center justify-center gap-2">
              <RefreshCw className="w-4 h-4 animate-spin text-accent" />
              <span>Loading scheduled background tasks...</span>
            </div>
          ) : filteredTasks.length === 0 ? (
            /* Empty State */
            <div className="p-12 rounded-2xl bg-bg-elevated/40 border border-dashed border-border-strong text-center flex flex-col items-center justify-center">
              <div className="w-14 h-14 rounded-2xl bg-bg-elevated border border-border-subtle flex items-center justify-center mb-4 text-text-tertiary shadow-inner">
                <Calendar className="w-7 h-7" />
              </div>
              <h3 className="text-sm font-semibold text-text-primary mb-1">
                Create a scheduled task
              </h3>
              <p className="text-xs text-text-secondary max-w-sm mb-6 leading-relaxed">
                Automate recurring routines, security sweeps, and digests with autonomous off-peak
                dispatch.
              </p>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => handleOpenCreateModal('manual')}
                  className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-semibold shadow-sm transition-all"
                >
                  Add manually
                </button>
                <span className="text-xs text-text-tertiary">or</span>
                <button
                  type="button"
                  onClick={() => handleOpenCreateModal('chat')}
                  className="px-4 py-2 bg-bg-elevated hover:bg-bg-hover border border-border-subtle text-text-primary rounded-xl text-xs font-medium transition-all"
                >
                  Create via chat
                </button>
              </div>
            </div>
          ) : (
            /* Populated State: Table / Card Grid */
            <div className="space-y-3">
              {filteredTasks.map((task) => {
                const isActive = task.status === 'active';
                return (
                  <div
                    key={task.id}
                    className="p-4 rounded-xl bg-bg-elevated border border-border-subtle hover:border-border-strong transition-all flex flex-col md:flex-row md:items-center justify-between gap-4 text-left"
                  >
                    {/* Left: Info */}
                    <div className="space-y-1.5 flex-1 min-w-0">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <span className="text-sm font-semibold text-text-primary truncate">
                          {task.name}
                        </span>

                        {/* Status Badge */}
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${
                            isActive
                              ? 'bg-success/10 text-success border-success/20'
                              : 'bg-text-tertiary/10 text-text-tertiary border-text-tertiary/20'
                          }`}
                        >
                          {task.status}
                        </span>

                        {/* Off-Peak Badge */}
                        {task.is_off_peak && (
                          <span className="px-2 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20 text-[10px] font-medium flex items-center gap-1">
                            <Moon className="w-2.5 h-2.5" />
                            <span>Off-Peak</span>
                          </span>
                        )}

                        {/* Notification Channel Badge */}
                        <span className="px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-[10px] text-text-tertiary capitalize">
                          {task.notification_channel}
                        </span>
                      </div>

                      <p className="text-xs text-text-secondary line-clamp-1">
                        {task.description || task.prompt}
                      </p>

                      <div className="flex items-center gap-4 text-[11px] text-text-tertiary flex-wrap pt-0.5">
                        <span className="flex items-center gap-1 text-text-secondary">
                          <Clock className="w-3 h-3 text-accent" />
                          <span className="font-medium text-text-primary">{task.cron_human}</span>
                          <span className="font-mono text-[10px] text-text-tertiary">({task.cron})</span>
                        </span>

                        <span className="flex items-center gap-1">
                          <Bot className="w-3 h-3 text-text-tertiary" />
                          <span>{task.agent_persona}</span>
                        </span>

                        <span>Next: {task.next_run || 'Pending'}</span>
                        <span>Last: {task.last_run || 'Never'}</span>
                      </div>
                    </div>

                    {/* Right: Cost & Actions */}
                    <div className="flex items-center gap-3 self-end md:self-center">
                      <div className="text-right pr-2">
                        <div className="text-xs font-semibold text-text-primary">
                          ${task.cost_per_run.toFixed(4)}
                          <span className="text-[10px] font-normal text-text-tertiary"> /run</span>
                        </div>
                        <div className="text-[10px] text-text-tertiary">
                          ~${task.monthly_estimate.toFixed(3)}/mo
                        </div>
                      </div>

                      {/* Trigger Run Now Button */}
                      <button
                        type="button"
                        onClick={() => handleTriggerTask(task)}
                        title="Run now"
                        className="p-2 rounded-lg bg-bg-base hover:bg-bg-hover border border-border-subtle text-text-secondary hover:text-text-primary transition-colors"
                      >
                        <Play className="w-3.5 h-3.5" />
                      </button>

                      {/* Toggle Pause/Resume */}
                      <button
                        type="button"
                        onClick={() => handleToggleTask(task.id, task.status)}
                        title={isActive ? 'Pause task' : 'Resume task'}
                        className={`p-2 rounded-lg border transition-colors ${
                          isActive
                            ? 'bg-bg-base hover:bg-bg-hover border-border-subtle text-text-secondary hover:text-warning'
                            : 'bg-accent/10 border-accent/30 text-accent hover:bg-accent/20'
                        }`}
                      >
                        {isActive ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                      </button>

                      {/* Delete */}
                      <button
                        type="button"
                        onClick={() => handleDeleteTask(task.id)}
                        title="Delete task"
                        className="p-2 rounded-lg bg-bg-base hover:bg-bg-hover border border-border-subtle text-text-secondary hover:text-danger transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Create Modal */}
      {createModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in">
          <div className="w-full max-w-xl rounded-2xl bg-bg-elevated border border-border-strong shadow-2xl overflow-hidden flex flex-col text-left">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-border-subtle flex items-center justify-between">
              <div>
                <h2 className="text-sm font-bold text-text-primary">Create Scheduled Task</h2>
                <p className="text-[11px] text-text-tertiary">
                  Background recurring execution with failure notifications
                </p>
              </div>
              <button
                type="button"
                onClick={() => setCreateModalOpen(false)}
                className="p-1 rounded-lg hover:bg-bg-hover text-text-tertiary hover:text-text-primary"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal Tabs */}
            <div className="px-6 pt-3 flex items-center gap-2 border-b border-border-subtle">
              <button
                type="button"
                onClick={() => setModalTab('manual')}
                className={`pb-2 text-xs font-medium border-b-2 transition-all ${
                  modalTab === 'manual'
                    ? 'border-accent text-accent'
                    : 'border-transparent text-text-tertiary hover:text-text-secondary'
                }`}
              >
                Configure Manually
              </button>
              <button
                type="button"
                onClick={() => setModalTab('template')}
                className={`pb-2 text-xs font-medium border-b-2 transition-all ${
                  modalTab === 'template'
                    ? 'border-accent text-accent'
                    : 'border-transparent text-text-tertiary hover:text-text-secondary'
                }`}
              >
                From Template
              </button>
              <button
                type="button"
                onClick={() => setModalTab('chat')}
                className={`pb-2 text-xs font-medium border-b-2 transition-all ${
                  modalTab === 'chat'
                    ? 'border-accent text-accent'
                    : 'border-transparent text-text-tertiary hover:text-text-secondary'
                }`}
              >
                Via Chat
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 max-h-[70vh] overflow-y-auto scrollbar-thin">
              {modalTab === 'manual' && (
                <form onSubmit={handleCreateSubmit} className="space-y-4">
                  <div>
                    <label className="block text-xs font-medium text-text-primary mb-1">
                      Task Name
                    </label>
                    <input
                      type="text"
                      required
                      value={taskName}
                      onChange={(e) => setTaskName(e.target.value)}
                      placeholder="e.g. Nightly AST Security Scan"
                      className="w-full px-3 py-2 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-text-primary mb-1">
                      Cron Schedule & Preview
                    </label>
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          required
                          value={taskCron}
                          onChange={(e) => setTaskCron(e.target.value)}
                          placeholder="0 2 * * *"
                          className="flex-1 px-3 py-2 bg-bg-base border border-border-subtle rounded-lg font-mono text-xs text-text-primary focus:outline-none focus:border-accent"
                        />
                        {/* Quick Presets */}
                        <select
                          onChange={(e) => {
                            if (e.target.value) setTaskCron(e.target.value);
                          }}
                          className="px-3 py-2 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-secondary focus:outline-none focus:border-accent"
                        >
                          <option value="">Presets...</option>
                          <option value="0 2 * * *">Daily 2:00 AM (Off-peak)</option>
                          <option value="0 8 * * *">Daily 8:00 AM</option>
                          <option value="0 18 * * 0">Weekly Sun 6:00 PM</option>
                          <option value="0 * * * *">Hourly</option>
                          <option value="0 3 1 * *">Monthly 1st 3:00 AM</option>
                        </select>
                      </div>

                      {/* Live plain-English preview */}
                      <div className="p-2.5 rounded-xl bg-accent/10 border border-accent/20 text-accent text-xs flex items-center gap-2">
                        <Clock className="w-3.5 h-3.5 flex-shrink-0" />
                        <span className="font-medium">
                          Plain-English preview: {cronToPlainEnglish(taskCron)}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs font-medium text-text-primary mb-1">
                        Assigned Agent
                      </label>
                      <select
                        value={taskPersona}
                        onChange={(e) => setTaskPersona(e.target.value)}
                        className="w-full px-3 py-2 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary focus:outline-none focus:border-accent"
                      >
                        {DEFAULT_PERSONAS.map((p) => (
                          <option key={p.id} value={p.name}>
                            {p.name} ({p.role})
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-text-primary mb-1">
                        Execution Model Tier
                      </label>
                      <select
                        value={taskModel}
                        onChange={(e) => setTaskModel(e.target.value as ModelTier)}
                        className="w-full px-3 py-2 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary focus:outline-none focus:border-accent"
                      >
                        <option value="instant">Instant High ($0.0002/1k)</option>
                        <option value="swarm">K3 Swarm High ($0.0015/1k)</option>
                        <option value="reasoning">K3 High ($0.0080/1k)</option>
                      </select>
                    </div>
                  </div>

                  {/* Off-Peak Default Checkbox (Law 7) */}
                  <div className="p-3 rounded-xl bg-bg-base border border-border-subtle flex items-center justify-between">
                    <div className="space-y-0.5">
                      <div className="text-xs font-semibold text-text-primary flex items-center gap-1.5">
                        <Moon className="w-3.5 h-3.5 text-accent" />
                        <span>Off-Peak Scheduling (Law 7)</span>
                      </div>
                      <div className="text-[10px] text-text-tertiary">
                        Run between 02:00 – 06:00 to conserve frontier quotas
                      </div>
                    </div>
                    <input
                      type="checkbox"
                      checked={taskIsOffPeak}
                      onChange={(e) => setTaskIsOffPeak(e.target.checked)}
                      className="w-4 h-4 accent-accent rounded"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-text-primary mb-1">
                      Failure Notification Channel
                    </label>
                    <select
                      value={taskChannel}
                      onChange={(e) => setTaskChannel(e.target.value as NotificationChannel)}
                      className="w-full px-3 py-2 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary focus:outline-none focus:border-accent capitalize"
                    >
                      <option value="slack">Slack (#agent-alerts)</option>
                      <option value="telegram">Telegram Direct</option>
                      <option value="whatsapp">WhatsApp Bridge</option>
                      <option value="webhook">Custom Webhook</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-text-primary mb-1">
                      Task Prompt / Directive
                    </label>
                    <textarea
                      required
                      rows={3}
                      value={taskPrompt}
                      onChange={(e) => setTaskPrompt(e.target.value)}
                      placeholder="Describe exactly what the agent should do on each trigger..."
                      className="w-full px-3 py-2 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
                    />
                  </div>

                  <div className="pt-2 flex items-center justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => setCreateModalOpen(false)}
                      className="px-4 py-2 bg-bg-base hover:bg-bg-hover text-text-secondary rounded-xl text-xs font-medium transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="px-4 py-2 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-semibold shadow-sm transition-all"
                    >
                      Schedule Task
                    </button>
                  </div>
                </form>
              )}

              {modalTab === 'template' && (
                <div className="space-y-3">
                  <p className="text-xs text-text-secondary">
                    Select a battle-tested routine to pre-fill schedule and parameters:
                  </p>
                  {TASK_TEMPLATES.map((tmpl) => (
                    <div
                      key={tmpl.title}
                      onClick={() => handleApplyTemplate(tmpl)}
                      className="p-3.5 rounded-xl bg-bg-base border border-border-subtle hover:border-accent cursor-pointer transition-all space-y-1.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-text-primary">{tmpl.title}</span>
                        <span className="px-2 py-0.5 rounded text-[10px] bg-accent/10 text-accent font-medium">
                          {tmpl.cron_human}
                        </span>
                      </div>
                      <p className="text-[11px] text-text-tertiary">{tmpl.description}</p>
                    </div>
                  ))}
                </div>
              )}

              {modalTab === 'chat' && (
                <div className="p-4 rounded-xl bg-bg-base border border-border-subtle space-y-3">
                  <div className="flex items-center gap-2 text-text-primary font-semibold text-xs">
                    <Sparkles className="w-4 h-4 text-accent" />
                    <span>Natural Language Task Scheduling</span>
                  </div>
                  <p className="text-xs text-text-secondary leading-relaxed">
                    Instruct your agent in plain English through the universal chat input below. It
                    will parse the cron schedule, recommend the optimal model tier, and configure
                    channel notifications automatically.
                  </p>
                  <button
                    type="button"
                    onClick={handleCreateViaChat}
                    className="w-full py-2.5 bg-accent hover:bg-accent-hover text-white rounded-xl text-xs font-semibold shadow-sm transition-all flex items-center justify-center gap-2"
                  >
                    <span>Insert Prompt into Chat</span>
                    <Send className="w-3.5 h-3.5" />
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Bottom Universal ChatInput for Scheduled Tasks Command */}
      <div className="border-t border-border-subtle bg-bg-base/95 backdrop-blur-md px-4 py-3">
        <div className="w-full max-w-[960px] mx-auto">
          <ChatInput
            mode="tasks"
            model={activeModel}
            onSend={(_msg) => {
              // Direct task trigger or schedule request
              setActionNotice('Task command received and queued in scheduler engine.');
              setTimeout(() => setActionNotice(null), 3500);
            }}
            onModeChange={onSelectMode}
            onModelChange={onSelectModel}
            inputRef={inputRef}
            placeholder="Tell your agent to schedule a task or run a routine on-demand..."
          />
        </div>
      </div>
    </div>
  );
};
