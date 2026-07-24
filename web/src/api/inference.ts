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
  numerator: string;
  denominator: string;
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

export interface BattleInferenceCompletenessResult {
  graph_complete: boolean;
  solver_status: string;
  truncation_reasons: string[];
  diagnostics: string[];
  warnings: string[];
}

export interface BattleInferenceSummaryResult {
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
  completeness: BattleInferenceCompletenessResult;
}

export interface ExplorationPathStepResult {
  source_node_id: number;
  edge_id: number;
  target_node_id: number;
}

export interface ExplorationCursorResult {
  steps: ExplorationPathStepResult[];
}

export interface BattleExplorationResult {
  root_node_id: number;
  graph_id: string;
  calculation_revision: string;
  expires_at: string;
  cursor: ExplorationCursorResult;
  expandable: boolean;
}

export interface BattleJourneyResult {
  summary: BattleInferenceSummaryResult;
  exploration: BattleExplorationResult;
}

export interface MoveSlotDetailResult {
  move_id: number;
  current_pp: number;
  max_pp: number;
  disabled: boolean;
  locked: boolean;
}

export interface StatusDetailResult {
  kind: string;
  turns_asleep: number | null;
  toxic_counter: number | null;
  turns_remaining: number | null;
  source_id: string | null;
}

export interface StatStagesDetailResult {
  attack: number;
  defense: number;
  special_attack: number;
  special_defense: number;
  speed: number;
  accuracy: number;
  evasion: number;
}

export interface BattlerDetailResult {
  pokemon_id: number;
  name: string;
  ability: string;
  item: string;
  current_hp: number;
  max_hp: number;
  moves: MoveSlotDetailResult[];
  major_status: StatusDetailResult | null;
  volatile_statuses: StatusDetailResult[];
  stat_stages: StatStagesDetailResult;
  last_move_id: number | null;
  choice_lock_move_id: number | null;
  item_consumed: boolean;
  first_turn: boolean;
}

export interface SideConditionsDetailResult {
  reflect: boolean;
  light_screen: boolean;
  aurora_veil: boolean;
}

export interface BattleFieldDetailResult {
  weather: string | null;
  terrain: string | null;
  attacker_side_conditions: SideConditionsDetailResult;
  defender_side_conditions: SideConditionsDetailResult;
}

export interface BattleNodeDetailResult {
  node_id: number;
  turn_number: number;
  phase: string;
  outcome: string;
  termination_reason: string | null;
  attacker: BattlerDetailResult;
  defender: BattlerDetailResult;
  field: BattleFieldDetailResult;
  terminal: boolean;
  has_outgoing_edges: boolean;
}

export interface RandomResultDetailResult {
  event_type: string;
  event_id: string;
  outcome_id: string;
  numeric_value: number | null;
}

export interface BattleEventDetailResult {
  kind: string;
  turn_number: number;
  actor: string | null;
  target: string | null;
  move_id: number | null;
  source_identifier: string | null;
  value: number | null;
  before_value: number | null;
  after_value: number | null;
}

export interface DamageRandomMetadataResult {
  raw_roll_index: number;
  raw_roll_value: number;
  final_damage: number;
  actual_hp_loss: number;
}

export interface TransitionEventPathDetailResult {
  random_results: RandomResultDetailResult[];
  damage_rolls: DamageRandomMetadataResult[];
  battle_events: BattleEventDetailResult[];
}

export interface TransitionLabelFieldsResult {
  selected_move_ids: number[];
  acting_sides: string[];
  target_sides: string[];
  result_keys: string[];
  source_identifiers: string[];
}

export interface TransitionOutcomeResult {
  edge_id: number;
  target_node_id: number;
  probability: ProbabilityResult;
  cumulative_probability: ProbabilityResult;
  label_fields: TransitionLabelFieldsResult;
  raw_random_values: number[];
  random_results: RandomResultDetailResult[];
  damage_rolls: DamageRandomMetadataResult[];
  battle_event_paths: BattleEventDetailResult[][];
  event_paths: TransitionEventPathDetailResult[];
}

export interface TransitionGroupSummaryResult {
  minimum_damage: number | null;
  maximum_damage: number | null;
  minimum_hp_loss: number | null;
  maximum_hp_loss: number | null;
}

export interface TransitionGroupResult {
  group_id: string;
  kind: string;
  label_key: string;
  probability: ProbabilityResult;
  raw_result_count: number;
  distinct_outcome_count: number;
  summary: TransitionGroupSummaryResult;
  expanded: boolean;
  outcomes: TransitionOutcomeResult[];
}

export interface BattleReportStepResult {
  depth: number;
  source_node_id: number;
  edge_id: number;
  target_node_id: number;
  edge_probability: ProbabilityResult;
  cumulative_probability: ProbabilityResult;
  event_paths: TransitionEventPathDetailResult[];
}

export interface BattleReportResult {
  graph_id: string;
  calculation_revision: string;
  root_node_id: number;
  current_node_id: number;
  depth: number;
  cumulative_probability: ProbabilityResult;
  steps: BattleReportStepResult[];
}

export interface BattleGraphExplorationResult {
  graph_id: string;
  calculation_revision: string;
  cursor: ExplorationCursorResult;
  node: BattleNodeDetailResult;
  transition_groups: TransitionGroupResult[];
  cumulative_probability: ProbabilityResult;
  breadcrumbs: ExplorationPathStepResult[];
  battle_report: BattleReportResult;
  terminal: boolean;
}

export interface BattleTransitionGroupOutcomesResult {
  graph_id: string;
  calculation_revision: string;
  cursor: ExplorationCursorResult;
  current_node_id: number;
  cumulative_probability: ProbabilityResult;
  transition_group: TransitionGroupResult;
}

interface ApiErrorDetail {
  code?: string;
  message?: string;
}

interface ApiErrorPayload {
  detail?: string | ApiErrorDetail;
}

/** 表示 inference API 返回的稳定 HTTP 错误及可选业务错误码。 */
export class InferenceApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  /**
   * 创建可供页面区分 graph 过期、资源不存在和冲突的请求错误。
   *
   * @param status HTTP 状态码。
   * @param code 后端 detail 中的稳定业务错误码；普通字符串错误时为 null。
   * @param message 用户可读错误文本。
   */
  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = 'InferenceApiError';
    this.status = status;
    this.code = code;
  }
}

/**
 * 读取 FastAPI JSON 响应，并把 detail 错误转换为用户可读异常。
 *
 * @param path 相对于 `/api/v1` 的接口路径。
 * @param init fetch 请求参数。
 * @returns 通过泛型声明的 JSON 响应。
 * @throws InferenceApiError 当服务端返回非 2xx 状态时抛出稳定错误。
 */
async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  const payload = (await response.json()) as T & ApiErrorPayload;
  if (!response.ok) {
    const detail = payload.detail;
    const code = typeof detail === 'object' && detail !== null ? detail.code ?? null : null;
    const message =
      typeof detail === 'string'
        ? detail
        : detail?.message ?? `请求失败：HTTP ${response.status}`;
    throw new InferenceApiError(response.status, code, message);
  }
  return payload;
}

/**
 * 构造只包含计算版本和真实 edge cursor 的渐进探索请求体。
 *
 * @param calculationRevision 当前前端支持的计算语义版本。
 * @param cursor 服务端上一次返回的真实 edge 序列。
 * @returns 可直接 JSON 序列化的请求体。
 */
function explorationRequestBody(
  calculationRevision: string,
  cursor: ExplorationCursorResult,
): { calculation_revision: string; cursor: ExplorationCursorResult } {
  return {
    calculation_revision: calculationRevision,
    cursor,
  };
}

/**
 * 执行快龙 vs 玛纽拉的受控多回合推演。
 *
 * @param request 页面选择的快龙特性、玛纽拉方案和能力预设。
 * @returns 分离全局 summary 与渐进 exploration 入口的顶层结果。
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

/**
 * 读取 cursor 当前节点和默认收起的 TransitionGroup 列表。
 *
 * @param graphId 首次推演返回的 graph ID。
 * @param calculationRevision 首次推演返回的计算语义版本。
 * @param cursor 服务端上一次返回的真实路径 cursor。
 * @returns 当前节点、折叠 groups、累计概率、breadcrumb 与结构化战报。
 */
export async function exploreBattleGraph(
  graphId: string,
  calculationRevision: string,
  cursor: ExplorationCursorResult,
): Promise<BattleGraphExplorationResult> {
  return requestJson<BattleGraphExplorationResult>(
    `/inference/graphs/${encodeURIComponent(graphId)}/explore`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(explorationRequestBody(calculationRevision, cursor)),
    },
  );
}

/**
 * 按需读取当前节点中一个 TransitionGroup 的归并 outcomes。
 *
 * @param graphId 当前完整状态图标识。
 * @param calculationRevision 当前计算语义版本。
 * @param cursor 当前真实路径 cursor。
 * @param groupId 用户主动展开的 group ID。
 * @returns 只包含目标 group outcomes 的窄响应。
 */
export async function loadBattleTransitionGroupOutcomes(
  graphId: string,
  calculationRevision: string,
  cursor: ExplorationCursorResult,
  groupId: string,
): Promise<BattleTransitionGroupOutcomesResult> {
  return requestJson<BattleTransitionGroupOutcomesResult>(
    `/inference/graphs/${encodeURIComponent(graphId)}/groups/${encodeURIComponent(groupId)}/outcomes`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(explorationRequestBody(calculationRevision, cursor)),
    },
  );
}

/**
 * 沿当前节点的一条正式 edge 前进，并读取目标节点的新窗口。
 *
 * @param graphId 当前完整状态图标识。
 * @param calculationRevision 当前计算语义版本。
 * @param cursor 当前真实路径 cursor。
 * @param edgeId 用户从归并 outcome 中选择的正式 edge ID。
 * @returns 已由 application 校验并前进一步的探索响应。
 */
export async function advanceBattleExploration(
  graphId: string,
  calculationRevision: string,
  cursor: ExplorationCursorResult,
  edgeId: number,
): Promise<BattleGraphExplorationResult> {
  return requestJson<BattleGraphExplorationResult>(
    `/inference/graphs/${encodeURIComponent(graphId)}/advance`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ...explorationRequestBody(calculationRevision, cursor),
        edge_id: edgeId,
      }),
    },
  );
}

/**
 * 返回上一级或截断到指定祖先深度。
 *
 * @param graphId 当前完整状态图标识。
 * @param calculationRevision 当前计算语义版本。
 * @param cursor 当前真实路径 cursor。
 * @param depth 目标祖先深度；省略时返回上一级。
 * @returns 截断真实 edge prefix 后恢复的探索响应。
 */
export async function backtrackBattleExploration(
  graphId: string,
  calculationRevision: string,
  cursor: ExplorationCursorResult,
  depth?: number,
): Promise<BattleGraphExplorationResult> {
  return requestJson<BattleGraphExplorationResult>(
    `/inference/graphs/${encodeURIComponent(graphId)}/backtrack`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ...explorationRequestBody(calculationRevision, cursor),
        ...(depth === undefined ? {} : { depth }),
      }),
    },
  );
}
