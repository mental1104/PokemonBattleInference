/** 冻结通用 1v1 技能池推演的前端合同与组合计算语义。 */

export const ONE_ON_ONE_CONTRACT_VERSION = 'one-on-one-move-pool.v1' as const;
export const MAX_TOTAL_CANDIDATE_MOVES = 20;
export const MOVE_SET_SIZE = 4;

export const CONFIGURATION_DIMENSION_MODES = [
  'fixed',
  'candidate_pool',
  'disabled',
] as const;
export type ConfigurationDimensionMode = (typeof CONFIGURATION_DIMENSION_MODES)[number];

export const CONFIGURATION_WEIGHT_ASSUMPTIONS = ['uniform_configuration_pair'] as const;
export type OneOnOneConfigurationWeightAssumption =
  (typeof CONFIGURATION_WEIGHT_ASSUMPTIONS)[number];

export const ONE_ON_ONE_ACTION_POLICIES = [
  'first-legal-action',
  'uniform-random',
] as const;
export type OneOnOneActionPolicy = (typeof ONE_ON_ONE_ACTION_POLICIES)[number];

export const MECHANISM_ADMISSION_POLICIES = ['supported_only'] as const;
export type MechanismAdmissionPolicy = (typeof MECHANISM_ADMISSION_POLICIES)[number];

export const CONFIGURATION_EXECUTION_STATUSES = [
  'success',
  'failed',
  'truncated',
] as const;
export type ConfigurationExecutionStatus = (typeof CONFIGURATION_EXECUTION_STATUSES)[number];

export const CONFIGURATION_TASK_STATUSES = [
  'pending',
  'running',
  'completed',
  'failed',
  'cancelled',
] as const;
export type ConfigurationTaskStatus = (typeof CONFIGURATION_TASK_STATUSES)[number];

/** 保存首版各配置维度的固定、候选池或禁用模式。 */
export interface OneOnOneDimensionModes {
  pokemon: ConfigurationDimensionMode;
  form: ConfigurationDimensionMode;
  level: ConfigurationDimensionMode;
  stats: ConfigurationDimensionMode;
  ability: ConfigurationDimensionMode;
  item: ConfigurationDimensionMode;
  moves: ConfigurationDimensionMode;
  special_mechanics: ConfigurationDimensionMode;
}

/** 保存一侧不会参与首版组合枚举的固定战斗配置。 */
export interface FixedPokemonConfiguration {
  pokemon_id: number;
  form_id: number | null;
  level: number;
  stat_profile_id: string;
  ability_identifier: string;
  item_identifier: string | null;
}

/** 保存一侧固定配置和候选招式池。 */
export interface PokemonMovePoolSelection {
  fixed: FixedPokemonConfiguration;
  candidate_move_ids: number[];
}

/** 声明通用 1v1 技能池批量推演输入。 */
export interface OneOnOneMovePoolCommand {
  contract_version: typeof ONE_ON_ONE_CONTRACT_VERSION;
  ruleset_id: string;
  version_group_id: number;
  calculation_revision: string;
  dimensions: OneOnOneDimensionModes;
  weight_assumption: OneOnOneConfigurationWeightAssumption;
  attacker_policy: OneOnOneActionPolicy;
  defender_policy: OneOnOneActionPolicy;
  mechanism_admission: MechanismAdmissionPolicy;
  attacker: PokemonMovePoolSelection;
  defender: PokemonMovePoolSelection;
}

/** 使用最简分数表达概率或配置权重，避免前端误把精确结果改为普通浮点数。 */
export interface ExactRatio {
  numerator: number;
  denominator: number;
}

/** 保存轻量状态图规模，不包含完整节点和边。 */
export interface GraphStatisticsSummary {
  node_count: number;
  edge_count: number;
  max_turn_number: number;
}

/** 保存结果列表展示所需的配置 ID 与双方规范化技能组。 */
export interface ConfigurationReference {
  configuration_id: string;
  attacker_move_ids: number[];
  defender_move_ids: number[];
}

/** 保存一个成功配置的精确概率摘要。 */
export interface SuccessfulConfigurationSummary {
  configuration: ConfigurationReference;
  configuration_weight: ExactRatio;
  win_probability: ExactRatio;
  loss_probability: ExactRatio;
  draw_probability: ExactRatio;
  graph_statistics: GraphStatisticsSummary;
  status: 'success';
}

/** 保存一个失败配置的分页诊断。 */
export interface FailedConfigurationDetail {
  configuration: ConfigurationReference;
  configuration_weight: ExactRatio;
  reason_code: string;
  message: string;
  graph_statistics: GraphStatisticsSummary | null;
  status: 'failed';
}

/** 保存一个触发运行保护的配置诊断。 */
export interface TruncatedConfigurationDetail {
  configuration: ConfigurationReference;
  configuration_weight: ExactRatio;
  reason_codes: string[];
  graph_statistics: GraphStatisticsSummary;
  status: 'truncated';
}

export type ConfigurationExecutionResult =
  | SuccessfulConfigurationSummary
  | FailedConfigurationDetail
  | TruncatedConfigurationDetail;

/** 分别记录成功、失败和截断配置的数量与权重覆盖。 */
export interface ConfigurationCoverageSummary {
  total_configuration_count: number;
  success_count: number;
  failed_count: number;
  truncated_count: number;
  success_weight: ExactRatio;
  failed_weight: ExactRatio;
  truncated_weight: ExactRatio;
}

/** 按完整配置分母聚合胜、负、平和未解析质量。 */
export interface BatchProbabilitySummary {
  win_probability: ExactRatio;
  loss_probability: ExactRatio;
  draw_probability: ExactRatio;
  unresolved_configuration_weight: ExactRatio;
}

/** 保存精确任务纳入和排除的机制集合。 */
export interface MechanismCoverageSummary {
  included: string[];
  excluded_partial: string[];
  excluded_unsupported: string[];
}

/** 保存批量任务全局摘要；该类型刻意不包含完整状态图字段。 */
export interface OneOnOneBatchSummary {
  task_id: string;
  contract_version: typeof ONE_ON_ONE_CONTRACT_VERSION;
  ruleset_id: string;
  version_group_id: number;
  calculation_revision: string;
  weight_assumption: OneOnOneConfigurationWeightAssumption;
  attacker_policy: OneOnOneActionPolicy;
  defender_policy: OneOnOneActionPolicy;
  coverage: ConfigurationCoverageSummary;
  probabilities: BatchProbabilitySummary;
  mechanism_coverage: MechanismCoverageSummary;
  top_configurations: SuccessfulConfigurationSummary[];
}

/** 保存后台任务可轮询的数量进度和取消状态。 */
export interface ConfigurationTaskProgress {
  task_id: string;
  status: ConfigurationTaskStatus;
  total_configuration_count: number;
  processed_count: number;
  success_count: number;
  failed_count: number;
  truncated_count: number;
  cancellation_requested: boolean;
}

/** 保存失败与截断配置的分页结果，不携带完整状态图。 */
export interface ConfigurationIssuePage {
  task_id: string;
  offset: number;
  limit: number;
  total: number;
  items: Array<FailedConfigurationDetail | TruncatedConfigurationDetail>;
}

/** 保存按需重算返回的完整图，并与轻量批量摘要隔离。 */
export interface OnDemandGraphResult<GraphArtifact> {
  configuration_id: string;
  calculation_revision: string;
  root_node_id: number;
  graph_artifact: GraphArtifact;
}

/** 声明从批量结果进入单配置完整状态图的按需重算请求。 */
export interface OnDemandGraphRequest {
  task_id: string;
  configuration_id: string;
  calculation_revision: string;
  max_nodes: number;
  max_edges: number;
  max_turns: number;
}

/** 保存规范化配置身份所需字段。 */
export interface NormalizedOneOnOneConfigurationIdentity {
  contract_version: typeof ONE_ON_ONE_CONTRACT_VERSION;
  ruleset_id: string;
  version_group_id: number;
  calculation_revision: string;
  attacker: FixedPokemonConfiguration;
  attacker_move_ids: readonly number[];
  defender: FixedPokemonConfiguration;
  defender_move_ids: readonly number[];
}

/** 描述共享 fixture 中一个候选数量与预期技能组数。 */
export interface MoveSetCountFixtureCase {
  candidate_count: number;
  expected_move_set_count: number;
}

/** 描述 Python 与 TypeScript 共同消费的 v1 合同 fixture。 */
export interface OneOnOneContractFixture {
  contract_version: typeof ONE_ON_ONE_CONTRACT_VERSION;
  enum_values: {
    dimension_mode: ConfigurationDimensionMode[];
    configuration_weight_assumption: OneOnOneConfigurationWeightAssumption[];
    action_policy: OneOnOneActionPolicy[];
    mechanism_admission_policy: MechanismAdmissionPolicy[];
    configuration_execution_status: ConfigurationExecutionStatus[];
    configuration_task_status: ConfigurationTaskStatus[];
  };
  move_set_cases: MoveSetCountFixtureCase[];
  max_budget_case: {
    attacker_candidate_count: number;
    defender_candidate_count: number;
    expected_configuration_pair_count: number;
  };
  command: OneOnOneMovePoolCommand;
  expected: {
    attacker_move_set_count: number;
    defender_move_set_count: number;
    configuration_pair_count: number;
    normalized_attacker_move_ids: number[];
    normalized_defender_move_ids: number[];
    configuration_id: string;
  };
  batch_summary: OneOnOneBatchSummary;
  issue_page: ConfigurationIssuePage;
  task_progress: ConfigurationTaskProgress;
  on_demand_graph_request: OnDemandGraphRequest;
}

/** 返回首版一侧候选池生成的无序技能组数量。 */
export function countMoveSets(candidateCount: number): number {
  assertPositiveInteger('candidateCount', candidateCount);
  if (candidateCount < MOVE_SET_SIZE) {
    return 1;
  }
  return combination(candidateCount, MOVE_SET_SIZE);
}

/** 返回满足双方总候选预算的配置对数量。 */
export function countConfigurationPairs(
  attackerCandidateCount: number,
  defenderCandidateCount: number,
): number {
  assertPositiveInteger('attackerCandidateCount', attackerCandidateCount);
  assertPositiveInteger('defenderCandidateCount', defenderCandidateCount);
  if (attackerCandidateCount + defenderCandidateCount > MAX_TOTAL_CANDIDATE_MOVES) {
    throw new Error('candidate move counts must total at most 20');
  }
  return countMoveSets(attackerCandidateCount) * countMoveSets(defenderCandidateCount);
}

/** 返回去重、递增排序后的正整数招式 ID。 */
export function normalizeMoveIds(moveIds: readonly number[]): number[] {
  if (moveIds.length === 0) {
    throw new Error('move ids must not be empty');
  }
  for (const moveId of moveIds) {
    assertPositiveInteger('moveId', moveId);
  }
  const unique = new Set(moveIds);
  if (unique.size !== moveIds.length) {
    throw new Error('move ids must be unique');
  }
  return [...unique].sort((left, right) => left - right);
}

/** 构造与 Python 一致的数组型 canonical JSON 配置 ID。 */
export function buildConfigurationId(
  configuration: NormalizedOneOnOneConfigurationIdentity,
): string {
  if (configuration.contract_version !== ONE_ON_ONE_CONTRACT_VERSION) {
    throw new Error('unsupported one-on-one contract version');
  }
  assertIdentityText('ruleset_id', configuration.ruleset_id);
  assertPositiveInteger('version_group_id', configuration.version_group_id);
  assertIdentityText('calculation_revision', configuration.calculation_revision);
  validateFixedConfiguration(configuration.attacker);
  validateFixedConfiguration(configuration.defender);
  const payload = [
    configuration.contract_version,
    configuration.ruleset_id,
    configuration.version_group_id,
    configuration.calculation_revision,
    pokemonIdentityPayload(configuration.attacker, configuration.attacker_move_ids),
    pokemonIdentityPayload(configuration.defender, configuration.defender_move_ids),
  ];
  return `one-on-one-configuration:${JSON.stringify(payload)}`;
}

/** 把一侧固定配置和技能组转换为位置稳定的身份数组。 */
function pokemonIdentityPayload(
  configuration: FixedPokemonConfiguration,
  moveIds: readonly number[],
): unknown[] {
  const normalizedMoveIds = normalizeMoveIds(moveIds);
  if (normalizedMoveIds.length > MOVE_SET_SIZE) {
    throw new Error('a normalized move set can contain at most four moves');
  }
  return [
    configuration.pokemon_id,
    configuration.form_id,
    configuration.level,
    configuration.stat_profile_id,
    configuration.ability_identifier,
    configuration.item_identifier,
    normalizedMoveIds,
  ];
}

/** 校验固定配置与 Python 合同使用相同的身份约束。 */
function validateFixedConfiguration(configuration: FixedPokemonConfiguration): void {
  assertPositiveInteger('pokemon_id', configuration.pokemon_id);
  if (configuration.form_id !== null) {
    assertPositiveInteger('form_id', configuration.form_id);
  }
  if (!Number.isSafeInteger(configuration.level) || configuration.level < 1 || configuration.level > 100) {
    throw new Error('level must be an integer from 1 to 100');
  }
  assertIdentityText('stat_profile_id', configuration.stat_profile_id);
  assertIdentityText('ability_identifier', configuration.ability_identifier);
  if (configuration.item_identifier !== null) {
    assertIdentityText('item_identifier', configuration.item_identifier);
  }
}

/** 校验参与配置身份的字符串为 ASCII 非空规范化文本。 */
function assertIdentityText(fieldName: string, value: string): void {
  if (value.length === 0 || value.trim() !== value || !/^[\x00-\x7F]+$/.test(value)) {
    throw new Error(`${fieldName} must be a normalized ASCII identifier`);
  }
}

/** 计算小规模非负整数的组合数。 */
function combination(total: number, selected: number): number {
  const effectiveSelected = Math.min(selected, total - selected);
  let result = 1;
  for (let index = 1; index <= effectiveSelected; index += 1) {
    result = (result * (total - effectiveSelected + index)) / index;
  }
  return result;
}

/** 校验数值为排除小数、负数和零的安全整数。 */
function assertPositiveInteger(fieldName: string, value: number): void {
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`${fieldName} must be a positive integer`);
  }
}
