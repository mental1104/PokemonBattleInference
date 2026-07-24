const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export type DragoniteAbility = 'multiscale' | 'inner-focus';
export type WeavilePlan = 'ice-punch' | 'fake-out-pressure';
export type BattleSide = 'attacker' | 'defender';

/** 前端已知的结构化战斗事件类别；服务端新增类别仍可通过 fallback 展示。 */
export type BattleEventKind =
  | 'turn-started'
  | 'move-selected'
  | 'action-ordered'
  | 'move-used'
  | 'action-blocked'
  | 'hit'
  | 'miss'
  | 'damage'
  | 'hp-changed'
  | 'pp-changed'
  | 'ability-triggered'
  | 'item-triggered'
  | 'status-applied'
  | 'status-prevented'
  | 'fainted'
  | 'turn-ended'
  | (string & {});

export interface BattleJourneyRequest {
  dragonite_ability: DragoniteAbility;
  weavile_plan: WeavilePlan;
  dragonite_stat_preset: string;
  weavile_stat_preset: string;
}

/** 保存精确分数文本和仅用于视觉展示的浮点近似值。 */
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

/** 表示 cursor 中一条真实选择边，允许状态合流和循环回边重复节点。 */
export interface ExplorationPathStepResult {
  source_node_id: number;
  edge_id: number;
  target_node_id: number;
}

/** 保存服务端校验过的有序 edge 序列。 */
export interface ExplorationCursorResult {
  steps: ExplorationPathStepResult[];
}

/** 保存首次推演返回、可跨 HTTP 请求继续探索的图句柄。 */
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

/** 保存一个招式槽在当前节点的 PP 和可用状态。 */
export interface MoveSlotDetailResult {
  move_id: number;
  current_pp: number;
  max_pp: number;
  disabled: boolean;
  locked: boolean;
}

/** 保存主状态或临时状态的结构化快照。 */
export interface StatusDetailResult {
  kind: string;
  turns_asleep: number | null;
  toxic_counter: number | null;
  turns_remaining: number | null;
  source_id: string | null;
}

/** 保存当前节点一侧 Pokémon 的动态状态。 */
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
  last_move_id: number | null;
  choice_lock_move_id: number | null;
  item_consumed: boolean;
  first_turn: boolean;
}

/** 保存 cursor 当前节点的关键展示字段。 */
export interface BattleNodeDetailResult {
  node_id: number;
  turn_number: number;
  phase: string;
  outcome: string;
  termination_reason: string | null;
  attacker: BattlerDetailResult;
  defender: BattlerDetailResult;
  terminal: boolean;
  has_outgoing_edges: boolean;
}

/** 保存一条结构化战斗事实，不包含自由字符串战报。 */
export interface BattleEventResult {
  kind: BattleEventKind;
  turn_number: number;
  actor: BattleSide | null;
  target: BattleSide | null;
  move_id: number | null;
  source_identifier: string | null;
  value: number | null;
  before_value: number | null;
  after_value: number | null;
}

/** 保存伤害随机档投影出的最终伤害和实际 HP 损失。 */
export interface DamageRandomMetadataResult {
  raw_roll_index: number;
  raw_roll_value: number;
  final_damage: number;
  actual_hp_loss: number;
}

/** 保存同一正式边的一条原始事件解释路径。 */
export interface TransitionEventPathResult {
  random_results: RandomResultDetailResult[];
  damage_rolls: DamageRandomMetadataResult[];
  battle_events: BattleEventResult[];
}

/** 保存一项随机机制的稳定结果。 */
export interface RandomResultDetailResult {
  event_type: string;
  event_id: string;
  outcome_id: string;
  numeric_value: number | null;
}

/** 保存 presenter 生成分支标签所需的结构化字段。 */
export interface TransitionLabelFieldsResult {
  selected_move_ids: number[];
  acting_sides: string[];
  target_sides: string[];
  result_keys: string[];
  source_identifiers: string[];
}

/** 保存一个已经按后继状态归并、可供用户选择的正式 outcome。 */
export interface TransitionOutcomeResult {
  edge_id: number;
  target_node_id: number;
  probability: ProbabilityResult;
  cumulative_probability: ProbabilityResult;
  label_fields: TransitionLabelFieldsResult;
  raw_random_values: number[];
  random_results: RandomResultDetailResult[];
  damage_rolls: DamageRandomMetadataResult[];
  battle_event_paths: BattleEventResult[][];
  event_paths: TransitionEventPathResult[];
}

/** 保存折叠分支组可展示的伤害和 HP 损失区间。 */
export interface TransitionGroupSummaryResult {
  minimum_damage: number | null;
  maximum_damage: number | null;
  minimum_hp_loss: number | null;
  maximum_hp_loss: number | null;
}

/** 保存当前节点一个默认折叠或按需展开的分支组。 */
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

/** 保存 cursor 中一条实际选择边对应的结构化战报阶段。 */
export interface BattleReportStepResult {
  depth: number;
  source_node_id: number;
  edge_id: number;
  target_node_id: number;
  edge_probability: ProbabilityResult;
  cumulative_probability: ProbabilityResult;
  event_paths: TransitionEventPathResult[];
}

/** 保存严格按 cursor edge 顺序返回的完整结构化战报。 */
export interface BattleReportResult {
  graph_id: string;
  calculation_revision: string;
  root_node_id: number;
  current_node_id: number;
  depth: number;
  cumulative_probability: ProbabilityResult;
  steps: BattleReportStepResult[];
}

/** 保存 explore、advance 或 backtrack 后的完整当前探索视图。 */
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

/** 保存按需展开一个分支组后的窄响应。 */
export interface BattleTransitionGroupOutcomesResult {
  graph_id: string;
  calculation_revision: string;
  cursor: ExplorationCursorResult;
  current_node_id: number;
  cumulative_probability: ProbabilityResult;
  transition_group: TransitionGroupResult;
}

/** 组合渐进探索请求必须携带的图句柄、计算版本和真实 cursor。 */
export interface BattleGraphRequestContext {
  graphId: string;
  calculationRevision: string;
  cursor: ExplorationCursorResult;
}

interface ApiErrorPayload {
  detail?: string | {
    code?: string;
    message?: string;
  };
}

/**
 * 读取 FastAPI JSON 响应，并把字符串或结构化 detail 转换为用户可读异常。
 *
 * @param path 相对于 `/api/v1` 的接口路径。
 * @param init fetch 请求参数。
 * @returns 通过泛型声明的 JSON 响应。
 * @throws Error HTTP 非成功状态时抛出后端 detail 中的稳定消息。
 */
async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  const payload = (await response.json()) as T & ApiErrorPayload;
  if (!response.ok) {
    const detail = payload.detail;
    const message =
      typeof detail === 'string'
        ? detail
        : detail?.message ?? `请求失败：HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

/**
 * 构造只包含 calculation revision 和真实 edge cursor 的探索请求体。
 *
 * @param context 当前图句柄及 cursor。
 * @returns 可直接序列化给探索 API 的请求对象。
 */
function explorationRequestBody(context: BattleGraphRequestContext): {
  calculation_revision: string;
  cursor: ExplorationCursorResult;
} {
  return {
    calculation_revision: context.calculationRevision,
    cursor: context.cursor,
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
 * 读取根节点或当前 cursor 节点，并取得同步的结构化战报。
 *
 * @param context 当前图句柄、计算版本和真实 cursor。
 * @returns 当前节点、折叠分支组及完整 battle report。
 */
export async function exploreBattleGraph(
  context: BattleGraphRequestContext,
): Promise<BattleGraphExplorationResult> {
  return requestJson<BattleGraphExplorationResult>(
    `/inference/graphs/${encodeURIComponent(context.graphId)}/explore`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(explorationRequestBody(context)),
    },
  );
}

/**
 * 按需展开当前节点的一个分支组，不预取其他 outcome。
 *
 * @param context 当前图句柄、计算版本和真实 cursor。
 * @param groupId 当前节点返回的稳定 group ID。
 * @returns 只包含指定 group outcomes 的窄响应。
 */
export async function loadTransitionGroupOutcomes(
  context: BattleGraphRequestContext,
  groupId: string,
): Promise<BattleTransitionGroupOutcomesResult> {
  return requestJson<BattleTransitionGroupOutcomesResult>(
    `/inference/graphs/${encodeURIComponent(context.graphId)}/groups/${encodeURIComponent(groupId)}/outcomes`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(explorationRequestBody(context)),
    },
  );
}

/**
 * 沿当前节点的一条正式 edge 前进，并用服务端返回值替换本地 cursor 与战报。
 *
 * @param context 当前图句柄、计算版本和真实 cursor。
 * @param edgeId 当前节点 outcome 返回的正式 edge ID。
 * @returns 前进一步后的完整探索视图。
 */
export async function advanceBattleExploration(
  context: BattleGraphRequestContext,
  edgeId: number,
): Promise<BattleGraphExplorationResult> {
  return requestJson<BattleGraphExplorationResult>(
    `/inference/graphs/${encodeURIComponent(context.graphId)}/advance`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ...explorationRequestBody(context),
        edge_id: edgeId,
      }),
    },
  );
}

/**
 * 返回上一级或截断到指定祖先深度，并取得服务端同步后的 battle report。
 *
 * @param context 当前图句柄、计算版本和真实 cursor。
 * @param depth 目标祖先深度；省略时只返回上一级。
 * @returns 回退后的完整探索视图。
 */
export async function backtrackBattleExploration(
  context: BattleGraphRequestContext,
  depth?: number,
): Promise<BattleGraphExplorationResult> {
  return requestJson<BattleGraphExplorationResult>(
    `/inference/graphs/${encodeURIComponent(context.graphId)}/backtrack`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        ...explorationRequestBody(context),
        depth,
      }),
    },
  );
}
