/** 配置空间后台任务的生命周期状态。 */
export type BattleInferenceJobStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'partial'
  | 'cancelled'
  | 'failed';

/** 单个配置对在批量任务中的执行状态。 */
export type ConfigurationRunStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'truncated'
  | 'cancelled';

/** Top-K 配置支持的稳定排序标识。 */
export type TopConfigurationSort =
  | 'overall-win-rate'
  | 'worst-matchup'
  | 'expected-winning-turns';

/** 失败与截断列表支持的状态过滤器。 */
export type ConfigurationIssueStatusFilter = 'all' | 'failed' | 'truncated';

/** 前端用于展示和识别招式的最小摘要。 */
export interface ConfigurationMoveSummary {
  move_id: number;
  identifier: string;
  name: string;
}

/** 配置对中一侧 Pokémon 与完整技能组的只读摘要。 */
export interface ConfigurationSideSummary {
  pokemon_id: number;
  pokemon_name: string;
  moves: ConfigurationMoveSummary[];
}

/** 后台任务按配置对数量统计的进度。 */
export interface ConfigurationJobCounts {
  total: number;
  completed: number;
  succeeded: number;
  failed: number;
  truncated: number;
  running: number;
  pending: number;
  cancelled: number;
}

/** 单项资源消耗及其任务预算。 */
export interface ConfigurationResourceBudget {
  used: number;
  limit: number;
}

/** 后台任务累计构建的状态图资源。 */
export interface ConfigurationJobResources {
  state_nodes: ConfigurationResourceBudget;
  edges: ConfigurationResourceBudget;
}

/** 已覆盖配置权重中的聚合胜负平概率。 */
export interface CoveredConfigurationProbability {
  win_percent: number;
  loss_percent: number;
  draw_percent: number;
}

/** 配置覆盖率、未完成权重及覆盖范围内概率摘要。 */
export interface ConfigurationAggregateSummary {
  configuration_coverage_percent: number;
  covered_weight_percent: number;
  unfinished_weight_percent: number;
  covered_probability: CoveredConfigurationProbability;
}

/** 某个 Top-K 排序是否可以使用，以及不可用时的稳定原因。 */
export interface TopSortCapability {
  sort: TopConfigurationSort;
  available: boolean;
  disabled_reason: string | null;
}

/** 任务规则、权重、行动策略与计算版本元数据。 */
export interface ConfigurationJobMetadata {
  ruleset_id: string;
  version_group_id: number;
  calculation_revision: string;
  configuration_weight_assumption: string;
  attacker_action_policy: string;
  defender_action_policy: string;
  included_mechanisms: string[];
  excluded_mechanisms: string[];
}

/** 配置空间任务的完整状态快照。 */
export interface ConfigurationSpaceJobSnapshot {
  job_id: string;
  status: BattleInferenceJobStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
  can_cancel: boolean;
  stop_reason_code: string | null;
  stop_reason_message: string | null;
  counts: ConfigurationJobCounts;
  resources: ConfigurationJobResources;
  aggregate: ConfigurationAggregateSummary;
  metadata: ConfigurationJobMetadata;
  top_sort_capabilities: TopSortCapability[];
  issue_error_codes: string[];
}

/** 单个配置对生成的状态图规模摘要；批量结果不包含完整图。 */
export interface ConfigurationGraphSummary {
  unique_state_count: number;
  edge_count: number;
  max_turn_number: number;
}

/** Top-K 中一个已求解或未完成配置对的结果。 */
export interface TopConfigurationResult {
  configuration_id: string;
  rank: number;
  status: ConfigurationRunStatus;
  attacker: ConfigurationSideSummary;
  defender: ConfigurationSideSummary;
  win_percent: number | null;
  loss_percent: number | null;
  draw_percent: number | null;
  expected_turns: number | null;
  worst_matchup_win_percent: number | null;
  graph: ConfigurationGraphSummary | null;
}

/** 一个失败或截断配置对的稳定诊断摘要。 */
export interface ConfigurationIssueResult {
  configuration_id: string;
  status: 'failed' | 'truncated';
  error_code: string;
  reason: string;
  diagnostic_summary: string;
  attacker: ConfigurationSideSummary;
  defender: ConfigurationSideSummary;
  unique_state_count: number;
  edge_count: number;
  max_turn_number: number;
}

/** 使用稳定 cursor 分页返回的结果窗口。 */
export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
  total: number;
}

/** 失败与截断分页查询参数。 */
export interface ConfigurationIssueQuery {
  status: ConfigurationIssueStatusFilter;
  error_code: string | null;
  cursor: string | null;
  limit: number;
}

/** 单个配置重试入口的占位操作结果。 */
export interface ConfigurationRetryResult {
  accepted: boolean;
  message: string;
}
