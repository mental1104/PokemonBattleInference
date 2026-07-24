import { computed, reactive, ref, watch } from 'vue';
import {
  getPokemonDetail,
  listStatPresets,
  type PokemonDetail,
  type PokemonSearchItem,
  type StatPreset,
} from '../api/calculator';
import {
  battleConfigurationSpaceAdapter,
  DRAGONITE_EXAMPLE,
  WEAVILE_EXAMPLE,
} from '../api/configurationSpace';
import {
  calculateConfigurationBudget,
  MAX_CONFIGURATION_PAIRS,
  MAX_TOTAL_CANDIDATE_MOVES,
  normalizeCandidateMoveIds,
} from '../domain/configurationBudget';
import type {
  CandidateMoveOption,
  CreateBattleConfigurationJobRequest,
  CreateBattleConfigurationJobResponse,
  FrozenBattleConfigurationSubmission,
} from '../types/battleConfigurationSpace';
import {
  ONE_ON_ONE_CONTRACT_VERSION,
  type MechanismAdmissionPolicy,
  type OneOnOneActionPolicy,
  type OneOnOneConfigurationWeightAssumption,
  type OneOnOneDimensionModes,
  type PokemonMovePoolSelection,
} from '../types/oneOnOneConfigurationSpace';

/** 页面中一侧 Pokémon 的固定配置、候选池和加载状态。 */
export interface BattleSideConfigurationState {
  pokemon: PokemonDetail | null;
  formId: number | null;
  level: number;
  statPreset: string;
  abilityIdentifier: string;
  itemIdentifier: string;
  candidateMoves: CandidateMoveOption[];
  selectedMoveIds: number[];
  movesLoading: boolean;
  error: string | null;
}

const DIMENSIONS: OneOnOneDimensionModes = {
  pokemon: 'fixed',
  form: 'fixed',
  level: 'fixed',
  stats: 'fixed',
  ability: 'fixed',
  item: 'fixed',
  moves: 'candidate_pool',
  special_mechanics: 'disabled',
};

const FALLBACK_ATTACKER_PRESETS: StatPreset[] = [
  {
    key: 'max_atk_neutral',
    label: '满攻',
    assumption: '攻击 EV 拉满，性格不修正攻击。',
  },
  {
    key: 'max_atk_plus',
    label: '极攻',
    assumption: '攻击 EV 拉满，性格提高攻击。',
  },
];

const FALLBACK_DEFENDER_PRESETS: StatPreset[] = [
  {
    key: 'max_hp',
    label: '满 HP',
    assumption: 'HP EV 拉满，其余耐久保持中性。',
  },
  {
    key: 'max_hp_defense_plus',
    label: '极限物耐',
    assumption: 'HP 与防御 EV 拉满，性格提高防御。',
  },
];

/**
 * 创建一侧配置的初始响应式状态。
 *
 * @param defaultPreset 初始能力值预设 identifier。
 * @returns 不包含共享规则上下文的新状态对象。
 */
function createSideState(defaultPreset: string): BattleSideConfigurationState {
  return reactive({
    pokemon: null,
    formId: null,
    level: 50,
    statPreset: defaultPreset,
    abilityIdentifier: 'none',
    itemIdentifier: '',
    candidateMoves: [],
    selectedMoveIds: [],
    movesLoading: false,
    error: null,
  });
}

/**
 * 返回当前选中 ID 是否全部仍属于可执行候选。
 *
 * @param side 待校验的一侧页面状态。
 * @returns 所有选择均存在且 admission.selectable 时返回 true。
 */
function selectedMovesAreAdmitted(side: BattleSideConfigurationState): boolean {
  const selectableMoveIds = new Set(
    side.candidateMoves
      .filter((move) => move.admission.selectable)
      .map((move) => move.move_id),
  );
  return side.selectedMoveIds.every((moveId) => selectableMoveIds.has(moveId));
}

/** 管理通用 1v1 配置页的固定配置、候选池预算、版本切换和冻结提交。 */
export function useBattleInferenceConfiguration() {
  const rulesetId = ref('pokemon-champion');
  const versionGroupId = ref(25);
  const calculationRevision = ref('mock.configuration-space.v1.vg-25');
  const weightAssumption: OneOnOneConfigurationWeightAssumption =
    'uniform_configuration_pair';
  const attackerPolicy: OneOnOneActionPolicy = 'uniform-random';
  const defenderPolicy: OneOnOneActionPolicy = 'uniform-random';
  const mechanismAdmission: MechanismAdmissionPolicy = 'supported_only';

  const attacker = createSideState('max_atk_neutral');
  const defender = createSideState('max_hp');
  const attackerPresets = ref<StatPreset[]>([]);
  const defenderPresets = ref<StatPreset[]>([]);
  const selectionNotice = ref<string | null>(null);
  const error = ref<string | null>(null);
  const submitting = ref(false);
  const frozenSubmission = ref<FrozenBattleConfigurationSubmission | null>(null);
  const createdJob = ref<CreateBattleConfigurationJobResponse | null>(null);
  const candidateRequestVersions = { attacker: 0, defender: 0 };
  const detailRequestVersions = { attacker: 0, defender: 0 };

  const budget = computed(() =>
    calculateConfigurationBudget(
      attacker.selectedMoveIds.length,
      defender.selectedMoveIds.length,
    ),
  );

  const remainingGlobalSlots = computed(() =>
    Math.max(0, MAX_TOTAL_CANDIDATE_MOVES - budget.value.total_candidate_count),
  );

  const validationMessages = computed(() => {
    const messages: string[] = [];
    if (attacker.pokemon === null) messages.push('请选择攻击方 Pokémon。');
    if (defender.pokemon === null) messages.push('请选择防守方 Pokémon。');
    if (attacker.abilityIdentifier === '') {
      messages.push('攻击方 ability_identifier 不能为空。');
    }
    if (defender.abilityIdentifier === '') {
      messages.push('防守方 ability_identifier 不能为空。');
    }
    if (attacker.selectedMoveIds.length === 0) {
      messages.push('攻击方候选技能池至少选择 1 个可执行招式。');
    }
    if (defender.selectedMoveIds.length === 0) {
      messages.push('防守方候选技能池至少选择 1 个可执行招式。');
    }
    if (!selectedMovesAreAdmitted(attacker)) {
      messages.push('攻击方选择中存在已失效或未通过机制准入的招式。');
    }
    if (!selectedMovesAreAdmitted(defender)) {
      messages.push('防守方选择中存在已失效或未通过机制准入的招式。');
    }
    if (budget.value.exceeds_candidate_limit) {
      messages.push('双方候选招式总数不能超过 20。');
    }
    if (budget.value.exceeds_configuration_pair_limit) {
      messages.push('配置对数量超过首版 44,100 硬上限。');
    }
    if (attacker.movesLoading || defender.movesLoading) {
      messages.push('候选池仍在加载，请等待当前 version group 的准入结果。');
    }
    return messages;
  });

  const canSubmit = computed(
    () => validationMessages.value.length === 0 && !submitting.value,
  );

  /** 初始化能力值预设；后端暂不可用时使用与当前计算器语义一致的本地 fixture。 */
  async function loadPresets(): Promise<void> {
    try {
      const presets = await listStatPresets();
      attackerPresets.value = presets.attacker;
      defenderPresets.value = presets.defender;
    } catch (caught) {
      attackerPresets.value = [...FALLBACK_ATTACKER_PRESETS];
      defenderPresets.value = [...FALLBACK_DEFENDER_PRESETS];
      selectionNotice.value =
        caught instanceof Error
          ? `能力值预设 API 暂不可用，已使用页面 fixture：${caught.message}`
          : '能力值预设 API 暂不可用，已使用页面 fixture。';
    }
  }

  /**
   * 读取一侧当前 version group 的候选池，并清除已失效或不再可执行的选择。
   *
   * @param sideName 需要加载的攻击方或防守方。
   */
  async function loadCandidateMoves(
    sideName: 'attacker' | 'defender',
  ): Promise<void> {
    const side = sideName === 'attacker' ? attacker : defender;
    if (side.pokemon === null) {
      side.candidateMoves = [];
      side.selectedMoveIds = [];
      return;
    }

    const requestVersion = ++candidateRequestVersions[sideName];
    side.movesLoading = true;
    side.error = null;
    try {
      const response = await battleConfigurationSpaceAdapter.listCandidateMoves({
        pokemon_id: side.pokemon.pokemon_id,
        ruleset_id: rulesetId.value,
        version_group_id: versionGroupId.value,
      });
      if (requestVersion !== candidateRequestVersions[sideName]) return;

      side.candidateMoves = response.moves;
      calculationRevision.value = response.calculation_revision;
      const selectableMoveIds = new Set(
        response.moves
          .filter((move) => move.admission.selectable)
          .map((move) => move.move_id),
      );
      side.selectedMoveIds = normalizeCandidateMoveIds(
        side.selectedMoveIds.filter((moveId) => selectableMoveIds.has(moveId)),
      );
    } catch (caught) {
      if (requestVersion !== candidateRequestVersions[sideName]) return;
      side.candidateMoves = [];
      side.selectedMoveIds = [];
      side.error =
        caught instanceof Error ? caught.message : '候选技能池加载失败';
    } finally {
      if (requestVersion === candidateRequestVersions[sideName]) {
        side.movesLoading = false;
      }
    }
  }

  /**
   * 将 Pokémon 详情写入一侧固定配置并重载候选池。
   *
   * @param sideName 攻击方或防守方。
   * @param detail 已按当前 ruleset 解析的 Pokémon 详情。
   * @param defaults 示例预设需要覆盖的特性与道具；普通选择可省略。
   */
  async function assignPokemonDetail(
    sideName: 'attacker' | 'defender',
    detail: PokemonDetail,
    defaults?: { abilityIdentifier?: string; itemIdentifier?: string },
  ): Promise<void> {
    const side = sideName === 'attacker' ? attacker : defender;
    side.pokemon = detail;
    side.formId = null;
    side.abilityIdentifier = defaults?.abilityIdentifier ?? 'none';
    side.itemIdentifier = defaults?.itemIdentifier ?? '';
    side.candidateMoves = [];
    side.selectedMoveIds = [];
    frozenSubmission.value = null;
    createdJob.value = null;
    await loadCandidateMoves(sideName);
  }

  /**
   * 处理用户在复用 PokemonSelector 中完成的一侧选择。
   *
   * @param sideName 攻击方或防守方。
   * @param pokemon 选择器返回的轻量 Pokémon 搜索项。
   */
  async function selectPokemon(
    sideName: 'attacker' | 'defender',
    pokemon: PokemonSearchItem,
  ): Promise<void> {
    const side = sideName === 'attacker' ? attacker : defender;
    const requestVersion = ++detailRequestVersions[sideName];
    error.value = null;
    side.error = null;
    try {
      const detail = await getPokemonDetail(pokemon.pokemon_id, rulesetId.value);
      // 用户快速切换 Pokémon 时忽略旧详情，避免晚到响应覆盖更新后的候选池。
      if (requestVersion !== detailRequestVersions[sideName]) return;
      await assignPokemonDetail(sideName, detail);
    } catch (caught) {
      if (requestVersion !== detailRequestVersions[sideName]) return;
      side.error = caught instanceof Error ? caught.message : 'Pokémon 详情加载失败';
    }
  }

  /**
   * 写入一侧候选选择；父层仍会在提交前再次规范化并验证支持状态。
   *
   * @param sideName 攻击方或防守方。
   * @param moveIds 候选组件返回的升序唯一 ID。
   */
  function updateSelectedMoveIds(
    sideName: 'attacker' | 'defender',
    moveIds: readonly number[],
  ): void {
    const side = sideName === 'attacker' ? attacker : defender;
    side.selectedMoveIds = normalizeCandidateMoveIds(moveIds);
    frozenSubmission.value = null;
    createdJob.value = null;
  }

  /** 应用固定快龙 vs 玛纽拉回归预设，并选择各自前四条可执行招式。 */
  async function applyDragoniteVsWeavilePreset(): Promise<void> {
    // 示例属于一次新的显式选择，先让两侧尚未返回的详情请求失效。
    detailRequestVersions.attacker += 1;
    detailRequestVersions.defender += 1;
    selectionNotice.value = '已载入固定快龙 vs 玛纽拉回归预设，可继续修改任意字段。';
    await Promise.all([
      assignPokemonDetail('attacker', DRAGONITE_EXAMPLE, {
        abilityIdentifier: 'multiscale',
        itemIdentifier: '',
      }),
      assignPokemonDetail('defender', WEAVILE_EXAMPLE, {
        abilityIdentifier: 'pressure',
        itemIdentifier: '',
      }),
    ]);
    attacker.statPreset = 'max_atk_plus';
    defender.statPreset = 'max_hp';
    attacker.selectedMoveIds = normalizeCandidateMoveIds(
      attacker.candidateMoves
        .filter((move) => move.admission.selectable)
        .slice(0, 4)
        .map((move) => move.move_id),
    );
    defender.selectedMoveIds = normalizeCandidateMoveIds(
      defender.candidateMoves
        .filter((move) => move.admission.selectable)
        .slice(0, 4)
        .map((move) => move.move_id),
    );
  }

  /**
   * 将一侧页面状态转换成冻结合同的一侧输入。
   *
   * @param side 已完成必填校验的一侧状态。
   * @returns 不引用响应式数组的规范化 DTO。
   */
  function buildSideInput(
    side: BattleSideConfigurationState,
  ): PokemonMovePoolSelection {
    if (side.pokemon === null) {
      throw new Error('cannot build side input without pokemon');
    }
    return {
      fixed: {
        pokemon_id: side.pokemon.pokemon_id,
        form_id: side.formId,
        level: side.level,
        stat_profile_id: side.statPreset,
        ability_identifier: side.abilityIdentifier,
        item_identifier: side.itemIdentifier === '' ? null : side.itemIdentifier,
      },
      candidate_move_ids: normalizeCandidateMoveIds(side.selectedMoveIds),
    };
  }

  /**
   * 生成冻结摘要并调用后台任务 adapter。
   *
   * 客户端预算仅提供即时反馈；真实服务端仍必须重新执行候选准入、规范化和硬上限校验。
   */
  async function submit(): Promise<void> {
    if (!canSubmit.value || attacker.pokemon === null || defender.pokemon === null) {
      return;
    }

    submitting.value = true;
    error.value = null;
    createdJob.value = null;
    const request: CreateBattleConfigurationJobRequest = {
      contract_version: ONE_ON_ONE_CONTRACT_VERSION,
      ruleset_id: rulesetId.value,
      version_group_id: versionGroupId.value,
      calculation_revision: calculationRevision.value,
      dimensions: { ...DIMENSIONS },
      weight_assumption: weightAssumption,
      attacker_policy: attackerPolicy,
      defender_policy: defenderPolicy,
      mechanism_admission: mechanismAdmission,
      attacker: buildSideInput(attacker),
      defender: buildSideInput(defender),
    };

    const attackerMoveNames = request.attacker.candidate_move_ids.map(
      (moveId) =>
        attacker.candidateMoves.find((move) => move.move_id === moveId)
          ?.display_name ?? String(moveId),
    );
    const defenderMoveNames = request.defender.candidate_move_ids.map(
      (moveId) =>
        defender.candidateMoves.find((move) => move.move_id === moveId)
          ?.display_name ?? String(moveId),
    );
    frozenSubmission.value = {
      request,
      attacker_name: attacker.pokemon.display_name,
      defender_name: defender.pokemon.display_name,
      attacker_move_names: attackerMoveNames,
      defender_move_names: defenderMoveNames,
      total_candidate_count: budget.value.total_candidate_count,
      configuration_pair_count: budget.value.configuration_pair_count,
      max_candidate_moves: MAX_TOTAL_CANDIDATE_MOVES,
      max_configuration_pairs: MAX_CONFIGURATION_PAIRS,
    };

    try {
      createdJob.value = await battleConfigurationSpaceAdapter.createJob(request);
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '后台任务创建失败';
    } finally {
      submitting.value = false;
    }
  }

  watch(versionGroupId, async (nextVersionGroupId, previousVersionGroupId) => {
    if (nextVersionGroupId === previousVersionGroupId) return;
    const hadSelection =
      attacker.selectedMoveIds.length > 0 || defender.selectedMoveIds.length > 0;

    // version group 是候选合法性主轴；切换时先清空旧选择，禁止旧世代 move_id 静默混入新任务。
    attacker.selectedMoveIds = [];
    defender.selectedMoveIds = [];
    frozenSubmission.value = null;
    createdJob.value = null;
    if (hadSelection) {
      selectionNotice.value =
        `version_group_id 已从 ${previousVersionGroupId} 切换为 ${nextVersionGroupId}，` +
        '双方旧候选选择已清空并重新执行机制准入。';
    }
    await Promise.all([
      loadCandidateMoves('attacker'),
      loadCandidateMoves('defender'),
    ]);
  });

  return {
    rulesetId,
    versionGroupId,
    calculationRevision,
    dimensions: DIMENSIONS,
    weightAssumption,
    attackerPolicy,
    defenderPolicy,
    mechanismAdmission,
    attacker,
    defender,
    attackerPresets,
    defenderPresets,
    selectionNotice,
    error,
    submitting,
    frozenSubmission,
    createdJob,
    budget,
    remainingGlobalSlots,
    validationMessages,
    canSubmit,
    loadPresets,
    selectPokemon,
    updateSelectedMoveIds,
    applyDragoniteVsWeavilePreset,
    submit,
  };
}
