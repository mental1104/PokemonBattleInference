import type { BattleInferenceSummaryResult } from '../api/inference';
import type { BattleJourneyResult } from '../api/inference';

/** 组合枚举与固定推演共享的一侧非招式配置。 */
export interface FixedBattleSideInput {
  pokemon_id: number;
  form_id: number | null;
  level: number;
  stat_profile_id: string;
  ability_identifier: string;
  item_identifier: string | null;
}

/** 一侧候选技能池输入；服务端会重新执行合法性与机制准入。 */
export interface MoveSetCombinationSideInput extends FixedBattleSideInput {
  candidate_move_ids: number[];
}

/** 只枚举技能组合、不创建后台任务的请求。 */
export interface MoveSetCombinationsRequest {
  ruleset_id: string;
  version_group_id: number;
  calculation_revision: string;
  attacker: MoveSetCombinationSideInput;
  defender: MoveSetCombinationSideInput;
}

/** 一个稳定、无序且规范化的一到四招技能组。 */
export interface MoveSetOptionResult {
  move_set_id: string;
  move_ids: number[];
  move_names: string[];
}

/** 一侧组合枚举结果。 */
export interface MoveSetSideResult {
  pokemon_id: number;
  pokemon_name: string;
  candidate_count: number;
  move_set_count: number;
  move_sets: MoveSetOptionResult[];
}

/** 双方独立技能组和理论配置对数量。 */
export interface MoveSetCombinationsResult {
  ruleset_id: string;
  version_group_id: number;
  calculation_revision: string;
  attacker: MoveSetSideResult;
  defender: MoveSetSideResult;
  configuration_pair_count: number;
}

/** 用户从组合列表选定的一侧固定技能组。 */
export interface FixedBattleChosenSideInput extends FixedBattleSideInput {
  move_ids: number[];
}

/** 单个固定配置允许使用的状态图运行保护。 */
export interface FixedBattleGraphLimitsInput {
  max_nodes: number;
  max_edges: number;
  max_turns: number;
}

/** 一次只求解一个固定配置快照的精确概率请求。 */
export interface FixedBattleSummaryRequest {
  ruleset_id: string;
  version_group_id: number;
  attacker: FixedBattleChosenSideInput;
  defender: FixedBattleChosenSideInput;
  attacker_policy: 'uniform-random' | 'first-legal';
  defender_policy: 'uniform-random' | 'first-legal';
  limits: FixedBattleGraphLimitsInput;
}

/** 固定配置摘要沿用现有精确胜负平响应。 */
export type FixedBattleSummaryResult = BattleInferenceSummaryResult;

/** 固定配置异步任务创建响应。 */
export interface FixedBattleJobCreationResult {
  job_id: string;
  job_type: 'fixed-one-on-one';
  status: string;
  phase: string;
  created_at: string;
  submitted_configuration_pairs: number;
  links: {
    self: string;
    cancel: string;
  };
}

/** 通用任务状态桶计数。 */
export interface InferenceJobCounts {
  total: number;
  pending: number;
  running: number;
  succeeded: number;
  failed: number;
  truncated: number;
  cancelled: number;
  completed: number;
}

/** 通用任务资源预算使用量。 */
export interface InferenceJobResource {
  used: number;
  limit: number;
}

/** 当前运行中 case 的观测进度。 */
export interface InferenceJobRunningCase {
  configuration_id: string;
  phase: string;
  percent: number;
  observed_nodes: number;
  observed_edges: number;
  node_limit: number;
  edge_limit: number;
  expanded_nodes: number;
  frontier_nodes: number;
  action_pairs_completed: number;
  action_pairs_total: number;
  updated_at: string;
}

/** 通用任务可靠进度；百分比只来自运行中 case 的观测资源使用量。 */
export interface InferenceJobProgress {
  phase: string;
  counts: InferenceJobCounts;
  state_nodes: InferenceJobResource;
  state_edges: InferenceJobResource;
  running_case: InferenceJobRunningCase | null;
  elapsed_seconds: number | null;
}

/** 固定任务列表项和详情共用快照。 */
export interface InferenceJobSummary {
  job_id: string;
  job_type: 'fixed-one-on-one' | 'configuration-space';
  status: string;
  phase: string;
  ruleset_id: string;
  version_group_id: number;
  calculation_revision: string;
  created_at: string;
  started_at: string | null;
  updated_at: string;
  finished_at: string | null;
  cancel_requested_at: string | null;
  can_cancel: boolean;
  progress: InferenceJobProgress;
  error_code: string | null;
  error_message: string | null;
  links: {
    self: string;
    cancel: string;
  };
}

/** 固定任务列表分页响应。 */
export interface InferenceJobListResult {
  items: InferenceJobSummary[];
  next_cursor: string | null;
}

/** 精确概率分数和前端展示小数。 */
export interface InferenceJobExactProbability {
  numerator: string;
  denominator: string;
  decimal: number;
}

/** 已完成配置的总结型归因概率片段。 */
export interface InferenceJobExplanationProbability {
  numerator: string;
  denominator: string;
  decimal: number;
}

/** 已完成配置中一个 root 行动对的胜率贡献桶。 */
export interface InferenceJobExplanationBucket {
  attacker_move_id: number | null;
  defender_move_id: number | null;
  probability: InferenceJobExplanationProbability;
  attacker_win_contribution: InferenceJobExplanationProbability;
  defender_win_contribution: InferenceJobExplanationProbability;
  draw_contribution: InferenceJobExplanationProbability;
  conditional_attacker_win: InferenceJobExplanationProbability;
  conditional_defender_win: InferenceJobExplanationProbability;
  conditional_draw: InferenceJobExplanationProbability;
  representative_target_node_id: number | null;
  path_count: number;
}

/** 已完成配置的首版总结型归因报告。 */
export interface InferenceJobExplanation {
  version: string;
  basis: string;
  coverage: InferenceJobExplanationProbability;
  root: {
    node_id: number;
    attacker_win: InferenceJobExplanationProbability;
    defender_win: InferenceJobExplanationProbability;
    draw: InferenceJobExplanationProbability;
  };
  buckets: InferenceJobExplanationBucket[];
  omitted_bucket_count: number;
  graph: {
    nodes: number;
    edges: number;
  };
}

/** 后台任务中一个固定配置 case 的轻量执行摘要。 */
export interface InferenceJobCaseSummary {
  configuration_id: string;
  sequence_no: number;
  status: string;
  attacker_pokemon_id: number;
  defender_pokemon_id: number;
  attacker_move_ids: number[];
  defender_move_ids: number[];
  attacker_win_probability: InferenceJobExactProbability | null;
  defender_win_probability: InferenceJobExactProbability | null;
  draw_probability: InferenceJobExactProbability | null;
  expected_turns_kind: string | null;
  expected_turns: string | null;
  node_count: number;
  edge_count: number;
  explanation: InferenceJobExplanation | null;
  failure_code: string | null;
  diagnostic: string | null;
}

/** 后台任务 case 分页响应。 */
export interface InferenceJobCasePageResult {
  job_id: string;
  offset: number;
  limit: number;
  total: number;
  next_cursor: string | null;
  items: InferenceJobCaseSummary[];
}

/** 已完成固定配置按需生成完整图后的响应。 */
export type FixedBattleJobGraphResult = BattleJourneyResult;
