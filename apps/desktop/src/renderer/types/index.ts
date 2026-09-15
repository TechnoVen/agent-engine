export type Mode =
  | 'home'
  | 'agent'
  | 'tasks'
  | 'swarm'
  | 'workflows'
  | 'code'
  | 'deep-research'
  | 'docs'
  | 'sheets'
  | 'slides'
  | 'websites'
  | 'design'
  | 'diagrams'
  | 'channels'
  | 'skills'
  | 'marketplace'
  | 'cost'
  | 'policies'
  | 'benchmarks'
  | 'settings'
  | 'projects';

export type ModelTier = 'instant' | 'swarm' | 'reasoning';

export interface ModelTierOption {
  id: ModelTier;
  label: string;
  description: string;
  costPer1k: string;
}

export interface ProjectThread {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
  snippet?: string;
  status: 'active' | 'archived';
}

export interface ProjectFile {
  id: string;
  name: string;
  size: string;
  type: string;
  uploadedAt: string;
}

export interface Project {
  id: string;
  name: string;
  icon: string;
  threadCount: number;
  lastActivity: string;
  description?: string;
  instructions?: string;
  color?: string;
  files?: ProjectFile[];
  threads?: ProjectThread[];
  activeAgents?: string[];
  scopedPolicy?: string;
  monthlySpendUsd?: number;
  budgetCeilingUsd?: number;
}

export interface RecentChat {
  id: string;
  title: string;
  mode: Mode;
  updatedAt: string;
}

export interface SidecarHealth {
  status: 'healthy' | 'degraded' | 'offline';
  version?: string;
  engine?: string;
  uptime_seconds?: number;
  timestamp?: string;
  error?: string;
}

export interface ExecutionTierInfo {
  tier: string;
  model: string;
  costPer1k?: string;
}

export interface CredentialItem {
  service: string;
  key: string;
  masked_value: string;
  backend: string;
  updated_at?: number;
}

export interface CredentialDetail extends CredentialItem {
  value?: string;
  revealed: boolean;
}

export interface SetCredentialPayload {
  service?: string;
  key: string;
  value: string;
}

export interface CredentialTestResult {
  provider: string;
  valid: boolean;
  latency_ms: number;
  error?: string;
}

export type UpdateChannel = 'stable' | 'beta' | 'nightly';

export interface UpdateStatus {
  current_version: string;
  channel: UpdateChannel;
  auto_check: boolean;
  last_checked_at?: number | null;
  feed_url: string;
}

export interface UpdateCheckResult {
  update_available: boolean;
  current_version: string;
  latest_version: string;
  channel: UpdateChannel;
  release_notes: string;
  pub_date?: string | null;
  download_url?: string | null;
  signature?: string | null;
  sha256?: string | null;
}

export type MessageRole = 'user' | 'assistant' | 'system';

export interface AttachmentFile {
  id: string;
  name: string;
  size: number;
  type: string;
  url?: string;
  snippet?: string;
  uploadProgress?: number;
  status?: 'pending' | 'uploading' | 'indexed' | 'error';
}

export interface ObserveMemoryPayload {
  content: string;
  category?: string;
  importance?: number;
  session_id?: string;
  metadata?: Record<string, any>;
}

export interface ObservationRecord {
  id: string;
  content: string;
  category?: string;
  importance?: number;
  created_at?: string;
  session_id?: string;
}

export interface MessageMetadata {
  modelTier?: ModelTier;
  modelName?: string;
  tokenCount?: number;
  tokensPerSec?: number;
  latencyMs?: number;
  estCost?: string;
  cached?: boolean;
  skillId?: string;
  skillName?: string;
  enabledPlugins?: string[];
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: string;
  isStreaming?: boolean;
  metadata?: MessageMetadata;
  attachments?: AttachmentFile[];
  skill?: SelectedSkill;
  approvalRequest?: ApprovalRequest;
}

export interface SkillItem {
  id: string;
  name: string;
  category: string;
  description: string;
  command: string;
  inputs: string[];
  outputs: string[];
  icon?: string;
  sampleInputs?: Record<string, string>;
}

export interface PluginItem {
  id: string;
  name: string;
  description: string;
  iconName: string;
  enabled: boolean;
  tier: 'free' | 'pro' | 'enterprise';
  badge?: string;
}

export interface SelectedSkill {
  skill: SkillItem;
  parameters: Record<string, string>;
}

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'edited';

export interface SafetyPolicyRuleInfo {
  rule_id: string;
  name: string;
  description: string;
  action: string;
  severity: string;
  tool_pattern?: string;
  match_conditions?: Record<string, any>;
  suggestion?: string;
}

export interface PendingOperation {
  operation_id: string;
  tool_name: string;
  tool_args: Record<string, any>;
  args_hash: string;
  risk_level: RiskLevel;
  risk_score: number;
  status: 'pending' | 'approved' | 'rejected' | 'expired' | 'consumed';
  created_at: number;
  expires_at: number;
  session_id?: string;
  reason?: string;
  suggestion?: string;
  diff?: ToolCallDiff;
  approval_token?: string;
  actor?: string;
  decision_reason?: string;
}

export interface DiffLine {
  type: 'add' | 'remove' | 'context';
  text: string;
  lineNumber?: number;
}

export interface ToolCallDiff {
  type: 'file' | 'command' | 'sql' | 'api' | 'generic';
  target: string;
  original?: string;
  proposed?: string;
  diffLines?: DiffLine[];
  contextInfo?: Record<string, any>;
}

export interface ApprovalRequest {
  id: string;
  toolName: string;
  toolArgs: Record<string, any>;
  riskLevel: RiskLevel;
  riskScore: number;
  reason: string;
  suggestion?: string;
  diff?: ToolCallDiff;
  estCostDelta?: string;
  status: ApprovalStatus;
  createdAt: string;
  resolvedAt?: string;
  decisionBy?: string;
  decisionReason?: string;
  modifiedArgs?: Record<string, any>;
  auditId?: number;
}

export interface ApprovalDecision {
  approvalId: string;
  decision: 'approve' | 'reject' | 'edit';
  reason?: string;
  modifiedArgs?: Record<string, any>;
}

export interface AuditLogEntry {
  id: number;
  timestamp: string;
  tool_name: string;
  tool_args: Record<string, any>;
  decision: string;
  risk_level: string;
  risk_score: number;
  policy_id?: string;
  reason?: string;
  suggestion?: string;
  session_id?: string;
}

export interface PolicyYamlResponse {
  yaml_content: string;
  rules_count: number;
}

export interface DryRunRequest {
  tool_name: string;
  tool_args?: Record<string, any>;
  context?: Record<string, any>;
}

export interface DryRunResult {
  decision: 'allow' | 'block' | 'stage';
  risk_score: number;
  risk_level: RiskLevel;
  violating_rules: Array<{
    id: string;
    name: string;
    description: string;
    action: string;
    risk_level: string;
    pattern: string;
    reason?: string;
    suggestion?: string;
  }>;
  suggestion?: string;
  reason?: string;
  audit_id?: number;
}

export interface PaginatedAuditLogsResponse {
  total: number;
  limit: number;
  offset: number;
  items: AuditLogEntry[];
}

export interface AgentPersona {
  id: string;
  name: string;
  role: string;
  description: string;
  avatar: string;
  suggestedModel: ModelTier;
  pipelineName: string;
  systemPrompt?: string;
  badge?: string;
}

export interface SessionSearchResult {
  session_id: string;
  title: string;
  channel: string;
  matched_snippets: Array<{
    role?: string;
    content?: string;
    field?: string;
  }>;
  total_messages: number;
  updated_at: string;
}

export type TaskScheduleStatus = 'active' | 'paused' | 'running' | 'error';
export type NotificationChannel = 'whatsapp' | 'telegram' | 'slack' | 'webhook';

export interface ScheduledTask {
  id: string;
  name: string;
  description: string;
  cron: string;
  cron_human: string;
  agent_persona: string;
  model: ModelTier;
  status: TaskScheduleStatus;
  last_run?: string;
  next_run?: string;
  cost_per_run: number;
  monthly_estimate: number;
  is_off_peak: boolean;
  notification_channel: NotificationChannel;
  prompt: string;
  created_at: string;
}

export interface ScheduledTaskCreatePayload {
  name: string;
  description?: string;
  cron: string;
  cron_human?: string;
  agent_persona?: string;
  model?: ModelTier;
  is_off_peak?: boolean;
  notification_channel?: NotificationChannel;
  prompt: string;
}

export interface TierSplitInfo {
  deterministic_cache_local_pct: number;
  mid_tier_pct: number;
  frontier_pct: number;
  code_cache_calls: number;
  mid_tier_calls: number;
  frontier_calls: number;
}

export interface DistillationCandidate {
  candidate_id: string;
  task_name: string;
  teacher_model: string;
  student_model: string;
  monthly_calls: number;
  current_cost_usd: number;
  distilled_cost_usd: number;
  monthly_savings_usd: number;
  accuracy_score: number;
  status: 'ready' | 'distilling' | 'distilled';
}

export interface BudgetConfig {
  monthly_budget_usd: number;
  daily_budget_usd: number;
  warning_threshold_pct: number;
  critical_threshold_pct: number;
  project: string;
  alerts?: Array<{
    alert_id?: string;
    level: 'warning' | 'critical';
    message: string;
    percentage: number;
    period: string;
  }>;
}

export interface CostMetrics {
  total_cost_usd: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  month_spend_usd: number;
  day_spend_usd: number;
  cache_hit_rate: number;
  tier_split?: TierSplitInfo;
  cost_per_task?: Array<{
    task: string;
    calls: number;
    cost_usd: number;
    avg_cost: number;
  }>;
  breakdown: Array<{
    group: string;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cost_usd: number;
  }>;
  alerts: Array<{
    alert_id?: string;
    level: 'warning' | 'critical';
    message: string;
    percentage: number;
    period: string;
  }>;
}

export interface HardwareTelemetry {
  cpu_usage_percent: number;
  cpu_cores_logical: number;
  cpu_cores_physical: number;
  ram_used_percent: number;
  ram_used_gb: number;
  ram_total_gb: number;
  ram_available_gb: number;
  gpu_detected: boolean;
  gpu_model: string;
  gpu_vendor: string;
  vram_used_percent: number;
  vram_used_gb: number;
  vram_total_gb: number;
  vram_free_gb: number;
  vram_warning: boolean;
  vram_warning_threshold?: number;
  tokens_per_second: number;
  recent_inference_runtime?: string | null;
  recent_inference_model?: string | null;
  ollama_active: boolean;
  llamacpp_active: boolean;
  local_runtime_active: boolean;
  timestamp?: string;
}

export interface SpeedRecordPayload {
  tokens: number;
  elapsed_seconds: number;
  model?: string;
  runtime?: string;
}




