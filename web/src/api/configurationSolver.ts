import type { PokemonSearchItem } from './calculator';

export type ConfigurationGoalKind = 'attack' | 'defense';
export type DamageRollPolicy = 'min' | 'max';

export interface ConfigurationGoalRequest {
  goal_id: string;
  kind: ConfigurationGoalKind;
  target_pokemon_id: number;
  move_id: number;
  required_turns: number;
  target_stat_preset: string;
  damage_roll_policy: DamageRollPolicy | null;
}

export interface SolveConfigurationRequest {
  ruleset_id: string;
  subject_pokemon_id: number;
  level: number;
  goals: ConfigurationGoalRequest[];
  allowed_stat_presets: string[];
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

export interface SolvedConfiguration {
  stat_preset: string;
  stat_preset_label: string;
  stat_preset_assumption: string;
  stats: Record<string, number>;
  goals: GoalVerification[];
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

/** 读取失败响应中的 detail，供页面展示稳定错误文案。 */
async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string') return payload.detail;
  } catch {
    return `HTTP ${response.status}`;
  }
  return `HTTP ${response.status}`;
}

/** 提交多目标配置反向求解请求。 */
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
