const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export type StatConfigurationRole = 'attacker' | 'defender' | 'both';
export type StatConfigurationSource = 'builtin' | 'custom';
export type PokemonBindingKind = 'global' | 'pokemon';

export interface StatSpread {
  hp: number;
  attack: number;
  defense: number;
  special_attack: number;
  special_defense: number;
  speed: number;
}

export interface NatureOption {
  identifier: string;
  label: string;
  increased_stat: string | null;
  decreased_stat: string | null;
}

export interface StatConfiguration {
  id: string;
  source: StatConfigurationSource;
  key: string;
  name: string;
  nature_id: string;
  evs: StatSpread;
  ivs: StatSpread;
  role: StatConfigurationRole;
  binding_kind: PokemonBindingKind;
  pokemon_id: number | null;
  description: string;
  hidden: boolean;
  visible: boolean;
  sort_order: number;
  editable: boolean;
  renamable: boolean;
  deletable: boolean;
  hideable: boolean;
  snapshot_profile_id: string;
  updated_at: string | null;
}

export interface StatConfigurationList {
  items: StatConfiguration[];
  visible_items: StatConfiguration[];
  default_visible_limit: number;
  fallback_id: string | null;
}

export interface SaveStatConfigurationRequest {
  name: string;
  nature_id: string;
  evs: StatSpread;
  ivs: StatSpread;
  role: StatConfigurationRole;
  binding_kind: PokemonBindingKind;
  pokemon_id: number | null;
}

interface ApiErrorPayload {
  detail?: unknown;
}

/** 将 API 错误转换成界面可直接展示的文本。 */
async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as ApiErrorPayload;
    if (typeof payload.detail === 'string') return payload.detail;
    if (Array.isArray(payload.detail)) return payload.detail.map(String).join('；');
  } catch {
    return `HTTP ${response.status}`;
  }
  return `HTTP ${response.status}`;
}

/** 发起 JSON 请求并在失败时抛出 Error。 */
async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
    ...init,
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** 按当前 Pokémon 和攻防位置读取可用配置。 */
export function listStatConfigurations(params: {
  role: 'attacker' | 'defender';
  pokemonId: number;
  includeHidden?: boolean;
}): Promise<StatConfigurationList> {
  const query = new URLSearchParams({
    role: params.role,
    pokemon_id: String(params.pokemonId),
    include_hidden: String(params.includeHidden === true),
  });
  return requestJson<StatConfigurationList>(`/stat-configurations?${query}`);
}

/** 读取合法性格列表。 */
export function listNatures(): Promise<NatureOption[]> {
  return requestJson<NatureOption[]>('/stat-configurations/natures');
}

/** 创建租户共享自定义配置。 */
export function createStatConfiguration(
  request: SaveStatConfigurationRequest,
): Promise<StatConfiguration> {
  return requestJson<StatConfiguration>('/stat-configurations', {
    method: 'POST',
    body: JSON.stringify(request),
  });
}

/** 完整更新租户共享自定义配置。 */
export function updateStatConfiguration(
  configId: string,
  request: SaveStatConfigurationRequest,
): Promise<StatConfiguration> {
  return requestJson<StatConfiguration>(`/stat-configurations/${encodeURIComponent(configId)}`, {
    method: 'PUT',
    body: JSON.stringify(request),
  });
}

/** 软删除租户共享自定义配置。 */
export function deleteStatConfiguration(configId: string): Promise<void> {
  return requestJson<void>(`/stat-configurations/${encodeURIComponent(configId)}`, {
    method: 'DELETE',
  });
}

/** 批量保存配置排序。 */
export function saveStatConfigurationOrder(params: {
  role: 'attacker' | 'defender';
  references: { source: StatConfigurationSource; key: string }[];
}): Promise<void> {
  return requestJson<void>('/stat-configurations/order', {
    method: 'POST',
    body: JSON.stringify({
      role: params.role,
      references: params.references,
    }),
  });
}
