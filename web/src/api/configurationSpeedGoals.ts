import type {
  ConfigurationGoalRequest,
  ConfigurationSearchMode,
  SolveConfigurationResponse,
  SolvedConfiguration,
} from './configurationSolver';

export interface ConfigurationSpeedGoalRequest {
  goal_id: string;
  target_pokemon_id: number;
  target_stat_preset: string;
}

export interface SpeedGoalVerification {
  goal_id: string;
  satisfied: boolean;
  target: SolveConfigurationResponse['subject'];
  subject_speed: number;
  target_speed: number;
  speed_margin: number;
}

export interface SpeedAwareSolvedConfiguration extends SolvedConfiguration {
  speed_goals: SpeedGoalVerification[];
}

export interface SpeedAwareSolveConfigurationResponse
  extends Omit<SolveConfigurationResponse, 'candidates'> {
  candidates: SpeedAwareSolvedConfiguration[];
  rejected_speed_goals: SpeedGoalVerification[];
}

export interface SpeedAwareCommonRequest {
  ruleset_id: string;
  subject_pokemon_id: number;
  subject_ability_identifier: string;
  subject_item_identifier: string | null;
  level: number;
  goals: ConfigurationGoalRequest[];
  speed_goals: ConfigurationSpeedGoalRequest[];
}

export interface SpeedAwarePresetRequest extends SpeedAwareCommonRequest {
  allowed_stat_presets: string[];
  max_candidates: number;
}

export interface SpeedAwareSpreadRequest extends SpeedAwareCommonRequest {
  max_candidates: number;
}

const API_BASE = '/api/v1';

/**
 * 读取失败响应中的 detail，供速度目标页面展示稳定错误文案。
 *
 * @param response 非 2xx 的 Fetch Response。
 * @returns 服务端 detail 或 HTTP 状态文本。
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
 * 提交支持速度目标的已有配置验证请求。
 *
 * @param request 固定双方机制、伤害目标、速度目标和允许配置的请求。
 * @returns 包含两类目标证据的速度感知响应。
 */
export async function solveConfigurationWithSpeed(
  request: SpeedAwarePresetRequest,
): Promise<SpeedAwareSolveConfigurationResponse> {
  const response = await fetch(`${API_BASE}/configuration_solver/solve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()) as SpeedAwareSolveConfigurationResponse;
}

/**
 * 提交支持速度目标的 EV、IV 与性格反推请求。
 *
 * @param request 固定 Pokémon、机制、伤害目标、速度目标和候选上限的请求。
 * @returns 最多十条带速度证据与单字段安全区间的候选。
 */
export async function searchConfigurationSpreadsWithSpeed(
  request: SpeedAwareSpreadRequest,
): Promise<SpeedAwareSolveConfigurationResponse> {
  const response = await fetch(`${API_BASE}/configuration_solver/search-spreads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()) as SpeedAwareSolveConfigurationResponse;
}

export type { ConfigurationSearchMode };
