import type { BattleInferenceSummaryResult } from '../api/inference';

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
