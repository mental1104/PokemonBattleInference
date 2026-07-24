import type { ExplorationPathStepResult, ProbabilityResult } from './inference';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export type WinningPathWinner = 'attacker' | 'defender';

export interface WinningPathConfigurationSideResult {
  pokemon_id: number;
  name: string;
  level: number;
  ability_identifier: string;
  item_identifier: string;
  move_ids: number[];
}

export interface WinningPathConfigurationResult {
  configuration_key: string;
  attacker: WinningPathConfigurationSideResult;
  defender: WinningPathConfigurationSideResult;
}

export interface JointActionAlternativeResult {
  attacker_move_id: number | null;
  defender_move_id: number | null;
  attacker_source_identifier: string | null;
  defender_source_identifier: string | null;
}

export interface JointActionStepResult {
  turn_number: number;
  attacker_move_id: number | null;
  defender_move_id: number | null;
  attacker_source_identifier: string | null;
  defender_source_identifier: string | null;
  ambiguous: boolean;
  alternatives: JointActionAlternativeResult[];
}

export interface WinningPathKeyEventResult {
  kind: string;
  actor: string | null;
  target: string | null;
  move_id: number | null;
  source_identifier: string | null;
}

export interface WinningPathGroupResult {
  path_key: string;
  terminal_turn: number;
  probability: ProbabilityResult;
  raw_path_count: number;
  raw_history_count_estimate: number;
  terminal_reasons: string[];
  terminal_node_ids: number[];
  actions: JointActionStepResult[];
  representative_path: ExplorationPathStepResult[];
  damage_values: number[];
  attacker_remaining_hp_values: number[];
  defender_remaining_hp_values: number[];
  key_events: WinningPathKeyEventResult[];
}

export interface WinningPathPrefixNodeResult {
  prefix_key: string;
  depth: number;
  action: JointActionStepResult | null;
  probability: ProbabilityResult;
  raw_path_count: number;
  terminal_path_keys: string[];
  children: WinningPathPrefixNodeResult[];
}

export interface WinningPathCycleReferenceResult {
  source_node_id: number;
  edge_id: number;
  target_node_id: number;
  prefix_depth: number;
  component_id: number | null;
}

export interface WinningPathGroupsResult {
  graph_id: string;
  calculation_revision: string;
  winner: WinningPathWinner;
  sort: 'shortest-high-probability';
  configuration: WinningPathConfigurationResult;
  winner_probability: ProbabilityResult | null;
  returned_probability: ProbabilityResult;
  returned_coverage: ProbabilityResult | null;
  path_groups: WinningPathGroupResult[];
  prefix_tree: WinningPathPrefixNodeResult;
  cycle_references: WinningPathCycleReferenceResult[];
  next_cursor: string | null;
  has_more: boolean;
  query_complete: boolean;
  traversal_truncated: boolean;
}

interface WinningPathErrorPayload {
  detail?: string | { message?: string };
}

/**
 * 查询固定配置下一个获胜侧的分页行动路径组。
 *
 * @param graphId 首次推演返回的 graph ID。
 * @param calculationRevision 首次推演返回的计算语义版本。
 * @param winner 需要解释的绝对获胜侧。
 * @param limit 本页最多返回的路径组数量。
 * @param cursor 上一页返回的不透明游标；首页传 null。
 * @returns 当前页 Top-K、行动前缀树、精确概率覆盖与循环引用。
 * @throws Error 当后端返回非 2xx 状态时抛出用户可读错误。
 */
export async function listWinningPathGroups(
  graphId: string,
  calculationRevision: string,
  winner: WinningPathWinner,
  limit = 10,
  cursor: string | null = null,
): Promise<WinningPathGroupsResult> {
  const response = await fetch(
    `${API_BASE_URL}/winning_paths/graphs/${encodeURIComponent(graphId)}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        calculation_revision: calculationRevision,
        winner,
        limit,
        cursor,
        sort: 'shortest-high-probability',
      }),
    },
  );
  const payload = (await response.json()) as WinningPathGroupsResult & WinningPathErrorPayload;
  if (!response.ok) {
    const detail = payload.detail;
    const message =
      typeof detail === 'string'
        ? detail
        : detail?.message ?? `胜利路径查询失败：HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
}
