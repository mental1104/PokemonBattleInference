import type { PokemonSearchItem } from './calculator';
import type { StatSpread } from './statConfigurations';

export type ConfigurationGoalKind = 'attack' | 'defense';
export type DamageRollPolicy = 'min' | 'max';
export type ConfigurationSearchMode = 'preset' | 'spread';

export interface ConfigurationGoalRequest {
  goal_id: string;
  kind: ConfigurationGoalKind;
  target_pokemon_id: number;
  move_id: number;
  required_turns: number;
  target_ability_identifier: string;
  target_item_identifier: string | null;
  target_stat_preset: string;
  damage_roll_policy: DamageRollPolicy | null;
}

export interface SolveConfigurationRequest {
  ruleset_id: string;
  subject_pokemon_id: number;
  subject_ability_identifier: string;
  subject_item_identifier: string | null;
  level: number;
  goals: ConfigurationGoalRequest[];
  allowed_stat_presets: string[];
  max_candidates: number;
}

export interface SearchConfigurationSpreadsRequest {
  ruleset_id: string;
  subject_pokemon_id: number;
  subject_ability_identifier: string;
  subject_item_identifier: string | null;
  level: number;
  goals: ConfigurationGoalRequest[];
  max_candidates: number;
}

export interface SolverPokemonSummary extends PokemonSearchItem {}

export interface SolverMoveSummary {
  move_id: number;
  identifier: string;
  display_name: string;
  type: string;
  type_name: string;
  category: 'physical' | 'special';
  power: number;
}

export interface GoalVerification {
  goal_id: string;
  kind: ConfigurationGoalKind;
  satisfied: boolean;
  subject_role: 'attacker' | 'defender';
  target: SolverPokemonSummary;
  move: SolverMoveSummary;
  roll_policy: DamageRollPolicy;
  damage_min: number;
  damage_max: number;
  selected_damage: number;
  repetitions: number;
  total_damage: number;
  hp_threshold: number;
  remaining_hp: number;
  effective_attack: number | null;
  effective_defense: number | null;
}

export interface StatValueRange {
  minimum: number;
  maximum: number;
}

export interface StatSpreadRange {
  hp: StatValueRange;
  attack: StatValueRange;
  defense: StatValueRange;
  special_attack: StatValueRange;
  special_defense: StatValueRange;
  speed: StatValueRange;
}

export interface SolverNatureOption {
  identifier: string;
  label: string;
}

export interface SolvedConfiguration {
  stat_preset: string;
  stat_preset_label: string;
  stat_preset_assumption: string;
  stats: Record<string, number>;
  goals: GoalVerification[];
  solution_kind?: 'preset' | 'spread';
  nature_id?: string | null;
  nature_label?: string | null;
  nature_options?: SolverNatureOption[];
  evs?: StatSpread | null;
  ivs?: StatSpread | null;
  ev_ranges?: StatSpreadRange | null;
  iv_ranges?: StatSpreadRange | null;
}

export interface SolveConfigurationResponse {
  ruleset_id: string;
  ruleset_name: string;
  subject: SolverPokemonSummary;
  level: number;
  reachable: boolean;
  candidates: SolvedConfiguration[];
  rejected_goals: GoalVerification[];
  scope: string[];
  warnings: string[];
}

const API_BASE = '/api/v1';

/**
 * 读取失败响应中的 detail，供页面展示稳定错误文案。
 *
 * @param response 后端返回的非成功 HTTP 响应。
 * @returns 优先使用结构化 detail，否则回退为 HTTP 状态码。
 */
async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string') return payload.detail;
  } catch {
    return `HTTP ${response.status}`;
  }
  return `HTTP ${response.status}`;
}

/**
 * 提交已有配置模板的多目标可达性求解请求。
 *
 * @param request 固定待配置 Pokémon、机制、目标和允许模板的完整请求。
 * @returns 模板候选或不可达证据。
 */
export async function solveConfiguration(
  request: SolveConfigurationRequest,
): Promise<SolveConfigurationResponse> {
  const response = await fetch(`${API_BASE}/configuration_solver/solve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return (await response.json()) as SolveConfigurationResponse;
}

/**
 * 根据攻防目标反推待配置 Pokémon 的 EV、IV 与性格。
 *
 * @param request 固定 Pokémon、机制、等级和目标的属性搜索请求。
 * @returns 最多十条包含代表值、等价性格和单字段安全区间的候选。
 */
export async function searchConfigurationSpreads(
  request: SearchConfigurationSpreadsRequest,
): Promise<SolveConfigurationResponse> {
  const response = await fetch(`${API_BASE}/configuration_solver/search-spreads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return (await response.json()) as SolveConfigurationResponse;
}
