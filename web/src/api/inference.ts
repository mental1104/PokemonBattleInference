const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export type DragoniteAbility = 'multiscale' | 'inner-focus';
export type WeavilePlan = 'ice-punch' | 'fake-out-pressure';

export interface BattleJourneyRequest {
  dragonite_ability: DragoniteAbility;
  weavile_plan: WeavilePlan;
  dragonite_stat_preset: string;
  weavile_stat_preset: string;
}

export interface ProbabilityResult {
  numerator: number;
  denominator: number;
  decimal: number;
  percent: number;
}

export interface ExpectedTurnsResult {
  available: boolean;
  numerator: number | null;
  denominator: number | null;
  decimal: number | null;
}

export interface PokemonConfigurationResult {
  pokemon_id: number;
  name: string;
  level: number;
  ability_identifier: string;
  item_identifier: string;
  move_ids: number[];
  move_names: string[];
  stats: Record<string, number>;
  dimension_labels: Record<string, string>;
}

export interface GraphSummaryResult {
  unique_state_count: number;
  edge_count: number;
  max_turn_number: number;
  closed_cycle_count: number;
  terminal_reachable_cycle_count: number;
  is_complete: boolean;
  truncation_reasons: string[];
}

export interface RepresentativePathStepResult {
  node_id: number;
  turn_number: number;
  phase: string;
  attacker_hp: number;
  defender_hp: number;
  outcome: string;
  events: string[];
}

export interface RepresentativePathResult {
  reference: string;
  outcome: string;
  steps: RepresentativePathStepResult[];
}

export interface BattleJourneyResult {
  ruleset_id: string;
  version_group_id: number;
  observer: string;
  attacker: PokemonConfigurationResult;
  defender: PokemonConfigurationResult;
  win_probability: ProbabilityResult;
  loss_probability: ProbabilityResult;
  draw_probability: ProbabilityResult;
  expected_turns: ExpectedTurnsResult;
  attacker_policy: string;
  defender_policy: string;
  graph: GraphSummaryResult;
  representative_paths: RepresentativePathResult[];
  included_mechanisms: string[];
  excluded_mechanisms: string[];
  configuration_coverage_percent: number;
  solver_status: string;
  warnings: string[];
}

/**
 * 读取 FastAPI JSON 响应，并把 detail 错误转换为用户可读异常。
 *
 * @param path 相对于 `/api/v1` 的接口路径。
 * @param init fetch 请求参数。
 * @returns 通过泛型声明的 JSON 响应。
 */
async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  const payload = (await response.json()) as T & { detail?: string };
  if (!response.ok) {
    throw new Error(payload.detail ?? `请求失败：HTTP ${response.status}`);
  }
  return payload;
}

/**
 * 执行快龙 vs 玛纽拉的受控多回合推演。
 *
 * @param request 页面选择的快龙特性、玛纽拉方案和能力预设。
 * @returns 后端 application 用例生成的概率、状态图和代表路径结果。
 */
export async function inferDragoniteVsWeavile(
  request: BattleJourneyRequest,
): Promise<BattleJourneyResult> {
  return requestJson<BattleJourneyResult>('/inference/dragonite-vs-weavile', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(request),
  });
}
