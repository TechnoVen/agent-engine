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

export interface SkillDetailed {
  id: string;
  name: string;
  category: string;
  description: string;
  inputs: string[];
  outputs: string[];
  source_tool: string;
  version?: string;
  author?: string;
  tags?: string[];
  content?: string;
  path?: string | null;
  is_readonly?: boolean;
  format?: string;
}

export interface SkillRegistryPackage {
  id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  tags: string[];
  category: string;
  sha256: string;
  verified: boolean;
  installs: number;
  is_installed: boolean;
  installed_path?: string | null;
}

export interface SkillCollectionItem {
  id: string;
  name: string;
  description: string;
  skill_ids: string[];
  tags: string[];
  created_at?: string;
  updated_at?: string;
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

export interface ModelSettingsConfig {
  default_tier: ModelTier;
  fallback_tier: ModelTier;
  temperature: number;
  max_context_tokens: number;
  hard_ceiling_tokens: number;
  bypass_cache: boolean;
}

export interface LocalRuntimeSettingsConfig {
  ollama_base_url: string;
  llamacpp_base_url: string;
  gpu_layers: number;
  cpu_threads: number;
  context_length: number;
  auto_detect_gpu: boolean;
}

export interface AdapterSettingsConfig {
  mcp_enabled: boolean;
  claude_code_adapter: boolean;
  codex_adapter: boolean;
  openclaw_adapter: boolean;
  goose_adapter: boolean;
  cursor_adapter: boolean;
}

export interface ChannelSettingsConfig {
  slack_enabled: boolean;
  slack_webhook_url?: string | null;
  slack_bot_token?: string | null;
  slack_app_token?: string | null;
  teams_enabled: boolean;
  teams_app_id?: string | null;
  teams_app_password?: string | null;
  teams_tenant_id?: string | null;
  teams_webhook_url?: string | null;
  discord_enabled: boolean;
  discord_webhook_url?: string | null;
  discord_bot_token?: string | null;
  mattermost_enabled: boolean;
  mattermost_url?: string | null;
  mattermost_bot_token?: string | null;
  telegram_enabled: boolean;
  telegram_bot_token?: string | null;
  whatsapp_enabled: boolean;
}

export interface StorageSettingsConfig {
  database_backend: 'sqlite' | 'postgres';
  sqlite_path: string;
  postgres_url?: string | null;
  chroma_path: string;
  retention_days: number;
}

export interface SecuritySettingsConfig {
  zero_trust_eval: 'strict' | 'permissive';
  approval_timeout_seconds: number;
  ipc_token_enabled: boolean;
  sandbox_mode: 'standard' | 'isolated';
  keychain_backend: string;
}

export interface AppearanceSettingsConfig {
  theme: 'dark' | 'light' | 'system';
  font_size: 'sm' | 'base' | 'lg';
  ui_density: 'comfortable' | 'compact';
  code_font_family: string;
}

export interface AppSettings {
  models: ModelSettingsConfig;
  local_runtime: LocalRuntimeSettingsConfig;
  adapters: AdapterSettingsConfig;
  channels: ChannelSettingsConfig;
  storage: StorageSettingsConfig;
  security: SecuritySettingsConfig;
  appearance: AppearanceSettingsConfig;
  version: string;
  updated_at: string;
}

export interface DiagnosticsBundle {
  system_info: Record<string, any>;
  schema_versions: Record<string, any>;
  config: Record<string, any>;
  logs: string[];
}

export interface AdapterHealth {
  status: 'healthy' | 'degraded' | 'unavailable';
  message: string;
  latency_ms: number;
  version?: string | null;
  details?: Record<string, any>;
}

export interface AdapterMetadata {
  adapter_id: string;
  name: string;
  description: string;
  protocol: string;
  version: string;
  capabilities: string[];
  enabled: boolean;
  initialized: boolean;
  health?: AdapterHealth;
}

export interface AdapterExecutionRequest {
  prompt: string;
  session_id?: string;
  context?: Record<string, any>;
  tools?: Record<string, any>[];
  model?: string;
  temperature?: number;
  max_tokens?: number;
  timeout_seconds?: number;
  metadata?: Record<string, any>;
}

export interface AdapterExecutionResponse {
  adapter_id: string;
  content: string;
  tool_calls: Record<string, any>[];
  finish_reason: string;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
  latency_ms: number;
  metadata?: Record<string, any>;
}

// Collaborative Rooms (Phase 5B - Milestone M4)
export type RoomRole = 'admin' | 'member' | 'viewer' | 'agent';
export type RoomTaskStatus = 'pending' | 'in_progress' | 'completed' | 'blocked' | 'failed' | 'cancelled';
export type RoomTaskPriority = 'low' | 'medium' | 'high' | 'urgent';

export interface CollaborativeRoom {
  room_id: string;
  project_id: string;
  name: string;
  description: string;
  topic: string;
  status: string;
  policy_id?: string | null;
  active_adapters: string[];
  session_ids: string[];
  created_at: string;
  updated_at: string;
  metadata?: Record<string, any>;
}

export interface CreateRoomPayload {
  project_id: string;
  name: string;
  description?: string;
  topic?: string;
  policy_id?: string;
  active_adapters?: string[];
  metadata?: Record<string, any>;
}

export interface RoomParticipant {
  room_id: string;
  participant_id: string;
  name: string;
  role: RoomRole;
  participant_type: 'human' | 'agent';
  adapter_type?: string | null;
  permissions: string[];
  joined_at: string;
  metadata?: Record<string, any>;
}

export interface AddRoomParticipantPayload {
  participant_id: string;
  name?: string;
  role?: RoomRole;
  participant_type?: 'human' | 'agent';
  adapter_type?: string;
  permissions?: string[];
  metadata?: Record<string, any>;
}

export interface RoomTask {
  task_id: string;
  room_id: string;
  title: string;
  description: string;
  status: RoomTaskStatus;
  priority: RoomTaskPriority;
  assigned_to?: string | null;
  assigned_adapter?: string | null;
  parent_task_id?: string | null;
  dependencies: string[];
  created_by: string;
  created_at: string;
  updated_at: string;
  result?: Record<string, any> | null;
  metadata?: Record<string, any>;
}

export interface CreateRoomTaskPayload {
  title: string;
  description?: string;
  priority?: RoomTaskPriority;
  assigned_to?: string;
  assigned_adapter?: string;
  parent_task_id?: string;
  dependencies?: string[];
  created_by?: string;
  metadata?: Record<string, any>;
}

export interface SwarmAgentSpec {
  id: string;
  name: string;
  role: string;
  model_tier: string;
  system_prompt?: string;
  estimated_cost_usd: number;
}

export interface SwarmCase {
  id: string;
  title: string;
  tagline: string;
  description: string;
  agents: SwarmAgentSpec[];
  default_prompt: string;
}

export interface SwarmAgentProgress {
  agent_id: string;
  agent_name: string;
  role: string;
  model_tier: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress_percent: number;
  output: string;
  cost_usd: number;
  execution_time_ms: number;
  error?: string;
}

export interface SwarmRunResult {
  swarm_id: string;
  prompt: string;
  model_tier: string;
  status: 'completed' | 'partial_failure' | 'failed';
  agent_results: SwarmAgentProgress[];
  aggregated_output: string;
  total_cost_usd: number;
  total_time_ms: number;
  created_at: string;
}

export type WorkflowNodeType =
  | 'pipeline'
  | 'skill'
  | 'agent'
  | 'gate'
  | 'condition'
  | 'parallel'
  | 'merge';

export interface WorkflowPosition {
  x: number;
  y: number;
}

export interface WorkflowNode {
  id: string;
  type: WorkflowNodeType;
  name: string;
  description?: string;
  config?: Record<string, any>;
  inputs?: Record<string, any>;
  outputs?: string[];
  position?: WorkflowPosition;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  condition?: string;
}

export interface WorkflowDefinition {
  id: string;
  name: string;
  description?: string;
  version?: string;
  status?: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  inputs_schema?: Record<string, any>;
  tags?: string[];
  steps?: string[];
}

export interface WorkflowStepResult {
  node_id: string;
  node_type: WorkflowNodeType;
  status: string;
  inputs?: Record<string, any>;
  outputs?: Record<string, any>;
  error?: string;
  cost_usd?: number;
  execution_time_ms?: number;
}

export interface WorkflowRun {
  run_id: string;
  workflow_id: string;
  status: 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed';
  current_node_id?: string;
  pending_gate?: Record<string, any>;
  inputs: Record<string, any>;
  outputs?: Record<string, any>;
  step_results: Record<string, WorkflowStepResult>;
  total_cost_usd: number;
  execution_time_ms: number;
  created_at: string;
  completed_at?: string;
}

export interface WorkflowValidationResult {
  valid: boolean;
  errors: string[];
  node_count: number;
  edge_count: number;
}

export interface PendingGateInfo {
  run_id: string;
  workflow_id: string;
  workflow_name: string;
  node_id: string;
  gate_name: string;
  inputs: Record<string, any>;
  timeout_seconds: number;
  created_at: string;
}

// ============================================================================
// Local Model Catalog & Recommendation Types (Task R3.5)
// ============================================================================

export type HardwareFitState = 'fits' | 'fits_with_limits' | 'does_not_fit' | 'unknown';

export type RequirementsProvenance =
  | 'inspected_artifact'
  | 'trusted_catalog'
  | 'model_metadata'
  | 'estimate'
  | 'unknown';

export type NumericFactProvenance =
  | 'declared_fact'
  | 'inspected_fact'
  | 'measured_fact'
  | 'derived_estimate'
  | 'curated_heuristic'
  | 'curated_policy'
  | 'unknown';

export interface ModelKVArchitectureMetadata {
  num_layers: number;
  num_kv_heads: number;
  head_dim: number;
  cache_element_bytes: number;
  provenance: NumericFactProvenance;
  source: string;
}

export type RecommendationTier = 'fast' | 'balanced' | 'best_local';

export interface TaskRequirements {
  task_type?: string;
  coding?: boolean;
  reasoning?: boolean;
  vision?: boolean;
  tools?: boolean;
  structured_output?: boolean;
  min_context_tokens?: number;
  require_local_only?: boolean;
  required_accelerator?: string;
}

export interface CapabilityEligibility {
  eligible: boolean;
  missing_capabilities: string[];
  rejection_reasons: string[];
  evaluated_at: number;
}

export interface HardwareFitResult {
  state: HardwareFitState;
  safe_ram_available_bytes: number;
  usable_before_model_bytes: number;
  required_ram_bytes: number;
  ram_headroom_bytes: number;
  ram_headroom_ratio: number;
  memory_unit: string;
  kv_context_bytes: number;
  kv_context_provenance: NumericFactProvenance;
  vram_fit_state?: HardwareFitState;
  available_vram_bytes?: number | null;
  required_vram_bytes?: number | null;
  vram_headroom_bytes?: number | null;
  is_unified_memory: boolean;
  accelerator_compatible: boolean;
  backend_used: string;
  provenance: RequirementsProvenance;
  rejection_reasons: string[];
  explanation: string;
}

export interface CatalogModelEntry {
  model_identity: {
    provider_id: string;
    model_id: string;
    variant?: string;
  };
  family: string;
  architecture: string;
  parameter_size: string;
  parameter_count_billions: number;
  parameter_count_provenance: NumericFactProvenance;
  quantization: string;
  managed_runtime: string;
  memory_unit: string;
  artifact_size_bytes: number;
  artifact_size_provenance: NumericFactProvenance;
  artifact_size_source: string;
  min_ram_bytes: number;
  min_ram_provenance: NumericFactProvenance;
  min_ram_source: string;
  recommended_ram_bytes: number;
  recommended_ram_provenance: NumericFactProvenance;
  recommended_ram_source: string;
  accelerator_required: boolean;
  min_vram_bytes?: number | null;
  recommended_vram_bytes?: number | null;
  min_vram_bytes_if_gpu_required?: number | null;
  supported_backends: string[];
  supported_architectures: string[];
  context_window_limit: number;
  context_window_provenance: NumericFactProvenance;
  kv_metadata?: ModelKVArchitectureMetadata | null;
  capabilities: Record<string, string>;
  quality_rank: number;
  quality_rank_provenance: NumericFactProvenance;
  quality_rank_source: string;
  provenance: RequirementsProvenance;
  catalog_version: string;
  updated_at: string;
}

export interface LocalModelRecommendation {
  tier: RecommendationTier;
  model_identity: {
    provider_id: string;
    model_id: string;
    variant?: string;
  };
  fit_result: HardwareFitResult;
  reason: string;
  model_entry: CatalogModelEntry;
}

export interface RecommendationExplanation {
  selected_tier: RecommendationTier;
  model_identity: {
    provider_id: string;
    model_id: string;
    variant?: string;
  };
  hardware_fit: HardwareFitResult;
  snapshot_timestamp: number;
  stale_telemetry: boolean;
  factual_resources_used: Record<string, any>;
  requirements_used: Record<string, any>;
  reserves_used: Record<string, number>;
  provenance: RequirementsProvenance;
  rejection_reasons: Record<string, string[]>;
}

export interface LocalRecommendationResponse {
  fast?: LocalModelRecommendation | null;
  balanced?: LocalModelRecommendation | null;
  best_local?: LocalModelRecommendation | null;
  explanations: Record<string, RecommendationExplanation>;
  rejection_summary: Record<string, string[]>;
  evaluated_candidates_count: number;
  snapshot_timestamp: number;
  stale_telemetry: boolean;
  resource_captured_at: number;
  resource_stale: boolean;
  warning?: string | null;
}

export type DownloadState =
  | 'not_present'
  | 'downloading'
  | 'paused'
  | 'verifying'
  | 'verified'
  | 'failed';

export interface DownloadStatus {
  artifact_id: string;
  model_identity?: {
    provider_id: string;
    model_id: string;
    variant?: string;
  };
  state: DownloadState;
  bytes_downloaded: number;
  total_bytes_expected: number;
  progress_ratio: number;
  etag?: string | null;
  expected_sha256: string;
  observed_sha256?: string | null;
  error_message?: string | null;
  partial_present?: boolean;
  resumable: boolean;
  file_path?: string | null;
  started_at?: number | null;
  updated_at: number;
  completed_at?: number | null;
  verified_at?: number | null;
  catalog_version?: string;
}
export type TaskOutcome = 'SUCCESS' | 'FAILURE' | 'PARTIAL' | 'UNKNOWN';

export type EvidenceSource = 'GOLDEN_EVAL' | 'PRODUCTION_OBSERVATION' | 'BENCHMARK_RUN';

export type EvidenceSufficiencyStatus =
  | 'SUFFICIENT_EVIDENCE'
  | 'INSUFFICIENT_EVIDENCE'
  | 'NO_SUCCESS_EVIDENCE';

export interface Money {
  amount_micros: number;
  currency: string;
}

export interface EconomicsCohortKey {
  initial_model_identity?: {
    provider_id: string;
    model_id: string;
    variant?: string;
  };
  initial_model_identity_str: string;
  task_family: string;
  evaluator_id?: string | null;
  evaluator_version: string;
  routing_policy_version: string;
  fallback_policy_version: string;
  effective_privacy_class: string;
  evidence_source: EvidenceSource;
}

export interface ModelEconomicsSummary {
  cohort_key: EconomicsCohortKey;
  initial_model_identity: {
    provider_id: string;
    model_id: string;
    variant?: string;
  };
  initial_provider_id: string;
  task_family: string;
  logical_tasks_count: number;
  total_attempts_count: number;
  verified_successes: number;
  failures: number;
  partials: number;
  unknowns: number;
  evaluable_tasks_count?: number;
  known_correction_count?: number;
  total_cost: Money;
  mean_task_cost: Money;
  observed_cost_per_verified_success?: Money | null;
  expected_cost_per_success?: Money | null;
  expected_cost_per_success_provenance?: string | null;
  estimator_version?: string;
  sufficiency_policy_version?: string;
  status: EvidenceSufficiencyStatus;
  currency: string;
  evaluator_version: string;
  routing_policy_version: string;
  fallback_policy_version: string;
  effective_privacy_class: string;
  evidence_source: EvidenceSource;
  sample_freshness?: number | null;
}

export type ConnectionVerificationStatus =
  | 'NOT_CONFIGURED'
  | 'POLICY_BLOCKED'
  | 'AUTHENTICATION_FAILED'
  | 'ACCESS_DENIED'
  | 'NETWORK_ERROR'
  | 'TIMEOUT'
  | 'MODEL_NOT_FOUND'
  | 'RATE_LIMITED'
  | 'QUOTA_EXHAUSTED'
  | 'PROVIDER_ERROR'
  | 'INVALID_RESPONSE'
  | 'VERIFIED_CONNECTED'
  | 'UNKNOWN_FAILURE';

export interface ProviderConnectionVerification {
  provider_id: string;
  model_identity?: {
    provider_id: string;
    model_id: string;
    version?: string;
    revision?: string;
  } | null;
  status: ConnectionVerificationStatus;
  last_verified_at: number;
  latency_ms: number;
  failure_class?: string | null;
  sanitized_error?: string | null;
  verification_version: string;
  verification_method_version: string;
  probe_type: string;
  is_fresh: boolean;
  display_state: string;
  details: Record<string, unknown>;
}


