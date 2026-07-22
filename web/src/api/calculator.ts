export interface PokemonSearchItem {
  pokemon_id: number;
  identifier: string;
  display_name: string;
  form_identifier: string | null;
  types: string[];
  type_names: string[];
}

export interface PokemonDetail extends PokemonSearchItem {
  base_stats: Record<string, number>;
}

export interface MoveSearchItem {
  move_id: number;
  identifier: string;
  display_name: string;
  type: string;
  type_name: string;
  category: 'physical' | 'special';
  power: number;
}

export interface StatPreset {
  key: string;
  label: string;
  assumption: string;
}

export interface CalculatorPokemonInput {
  pokemon_id: number;
  level: number;
  stat_preset: string;
}

export interface CalculateDamageRequest {
  ruleset_id: string;
  attacker: CalculatorPokemonInput;
  defender: CalculatorPokemonInput;
  move_id: number;
}

export interface CalculateDamageResponse {
  ruleset_id: string;
  ruleset_name: string;
  attacker: ResultPokemon;
  defender: ResultPokemon;
  move: ResultMove;
  damage: DamageRange;
  ko: KOResult;
  modifiers: ModifierTraceItem[];
  scope: CalculationScope;
  warnings: string[];
}

export interface ResultPokemon {
  pokemon_id: number;
  identifier: string;
  display_name: string;
  level: number;
  preset_label: string;
  preset_assumption: string;
  stats: Record<string, number>;
  effective_attack: number | null;
  effective_hp: number | null;
  effective_defense: number | null;
}

export interface ResultMove {
  move_id: number;
  identifier: string;
  display_name: string;
  type: string;
  type_name: string;
  category: 'physical' | 'special';
  power: number;
}

export interface DamageRange {
  min: number;
  max: number;
  min_percent: number;
  max_percent: number;
  expected: number;
  expected_percent: number;
  rolls: number[];
}

export interface KOResult {
  ohko_probability: number;
  two_hit_ko_probability: number;
  guaranteed_ohko: boolean;
  guaranteed_2hko: boolean;
}

export interface ModifierTraceItem {
  key: string;
  multiplier: number | null;
  min_multiplier: number | null;
  max_multiplier: number | null;
  stage: string | null;
  source: string | null;
  reason: string;
}

export interface CalculationScope {
  mode: string;
  included: string[];
  excluded: string[];
}

const API_BASE = '/api/v1';

/** 把失败 HTTP 响应转换成面向界面的错误文本。 */
async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === 'string') {
      return payload.detail;
    }
  } catch {
    return `HTTP ${response.status}`;
  }
  return `HTTP ${response.status}`;
}

/** 发起 JSON 请求并在失败时抛出可展示错误。 */
async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return (await response.json()) as T;
}

/** 搜索当前规则集下可用于计算器的宝可梦。 */
export function searchPokemon(query: string, rulesetId: string): Promise<PokemonSearchItem[]> {
  const params = new URLSearchParams({ query, ruleset_id: rulesetId });
  return requestJson<PokemonSearchItem[]>(`${API_BASE}/calculator/pokemon?${params.toString()}`);
}

/** 读取一只宝可梦详情，当前用于选择后的摘要展示。 */
export function getPokemonDetail(pokemonId: number, rulesetId: string): Promise<PokemonDetail> {
  const params = new URLSearchParams({ ruleset_id: rulesetId });
  return requestJson<PokemonDetail>(`${API_BASE}/calculator/pokemon/${pokemonId}?${params.toString()}`);
}

/** 列出攻击方在当前规则集下可学且基础模式可计算的招式。 */
export function listPokemonMoves(
  pokemonId: number,
  rulesetId: string,
  query: string,
): Promise<MoveSearchItem[]> {
  const params = new URLSearchParams({ ruleset_id: rulesetId, query });
  return requestJson<MoveSearchItem[]>(
    `${API_BASE}/calculator/pokemon/${pokemonId}/moves?${params.toString()}`,
  );
}

/** 读取 application 同源配置模板，避免前端自行解释 EV/性格含义。 */
export function listStatPresets(): Promise<{ attacker: StatPreset[]; defender: StatPreset[] }> {
  return requestJson<{ attacker: StatPreset[]; defender: StatPreset[] }>(`${API_BASE}/calculator/presets`);
}

/** 提交基础伤害计算请求，派生战斗资料全部由服务端查询和校验。 */
export function calculateDamage(request: CalculateDamageRequest): Promise<CalculateDamageResponse> {
  return requestJson<CalculateDamageResponse>(`${API_BASE}/calculator/damage`, {
    method: 'POST',
    body: JSON.stringify(request),
  });
}
