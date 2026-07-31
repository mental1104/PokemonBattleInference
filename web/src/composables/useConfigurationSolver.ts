import { computed, ref, watch } from 'vue';
import {
  getPokemonDetail,
  listBattleItems,
  listPokemonAbilities,
  listStatPresets,
  type BattleAbilityOption,
  type BattleItemOption,
  type MoveSearchItem,
  type PokemonDetail,
  type PokemonSearchItem,
  type StatPreset,
} from '../api/calculator';
import {
  searchConfigurationSpreads,
  solveConfiguration,
  type ConfigurationGoalKind,
  type ConfigurationGoalRequest,
  type ConfigurationSearchMode,
  type DamageRollPolicy,
  type GoalVerification,
  type SolveConfigurationResponse,
} from '../api/configurationSolver';

export interface EditableSolverGoal {
  id: string;
  kind: ConfigurationGoalKind;
  target: PokemonDetail | null;
  move: MoveSearchItem | null;
  repetitions: number;
  targetPreset: string;
  targetAbilityIdentifier: string;
  targetAbilityOptions: BattleAbilityOption[];
  targetAbilitiesLoading: boolean;
  targetItemIdentifier: string;
  rollPolicy: DamageRollPolicy;
}

const DEFAULT_PRESETS = ['max_hp_def_plus', 'max_hp_spdef_plus', 'max_spatk_plus', 'max_atk_plus'];

/** 管理配置反向求解页面的 Pokémon、机制选择、目标列表、搜索模式和提交状态。 */
export function useConfigurationSolver() {
  const rulesetId = ref('pokemon-champion');
  const level = ref(50);
  const searchMode = ref<ConfigurationSearchMode>('preset');
  const subject = ref<PokemonDetail | null>(null);
  const subjectAbilityIdentifier = ref('');
  const subjectAbilityOptions = ref<BattleAbilityOption[]>([]);
  const subjectAbilitiesLoading = ref(false);
  const subjectItemIdentifier = ref('none');
  const itemOptions = ref<BattleItemOption[]>([]);
  const itemsLoading = ref(false);
  const goals = ref<EditableSolverGoal[]>([]);
  const statPresets = ref<StatPreset[]>([]);
  const selectedPresetKeys = ref<string[]>([...DEFAULT_PRESETS]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const result = ref<SolveConfigurationResponse | null>(null);

  const canSubmit = computed(() => {
    const searchInputReady = searchMode.value === 'spread'
      || selectedPresetKeys.value.length > 0;
    return Boolean(
      subject.value
        && subjectAbilityIdentifier.value
        && goals.value.length > 0
        && goals.value.every(isGoalComplete)
        && searchInputReady
        && !loading.value,
    );
  });

  /**
   * 判断一条目标是否已经包含可提交的 Pokémon、招式和机制选择。
   *
   * @param goal 新增或编辑弹窗中的目标草稿。
   * @returns 所有必填字段完整且次数有效时返回 true。
   */
  function isGoalComplete(goal: EditableSolverGoal): boolean {
    return Boolean(
      goal.target
        && goal.move
        && goal.targetPreset
        && goal.targetAbilityIdentifier
        && goal.repetitions > 0,
    );
  }

  /**
   * 创建一条尚未写入已选列表的目标草稿。
   *
   * @param kind attack 表示待配置 Pokémon 主动攻击，defense 表示待配置 Pokémon 承受攻击。
   * @returns 带对应默认配置和随机伤害档的独立目标对象。
   */
  function createGoalDraft(kind: ConfigurationGoalKind): EditableSolverGoal {
    return {
      id: `goal-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      kind,
      target: null,
      move: null,
      repetitions: 1,
      targetPreset: kind === 'attack' ? 'max_hp' : 'max_atk_neutral',
      targetAbilityIdentifier: '',
      targetAbilityOptions: [],
      targetAbilitiesLoading: false,
      targetItemIdentifier: 'none',
      rollPolicy: kind === 'attack' ? 'min' : 'max',
    };
  }

  /**
   * 为编辑弹窗复制一份与已选列表隔离的目标快照。
   *
   * @param goal 当前已保存的目标。
   * @returns 可独立修改的浅层业务快照；数组字段会额外复制，避免取消编辑时污染列表。
   */
  function cloneGoal(goal: EditableSolverGoal): EditableSolverGoal {
    return {
      ...goal,
      target: goal.target === null ? null : {
        ...goal.target,
        types: [...goal.target.types],
        type_names: [...goal.target.type_names],
        base_stats: { ...goal.target.base_stats },
      },
      move: goal.move === null ? null : { ...goal.move },
      targetAbilityOptions: [...goal.targetAbilityOptions],
      targetAbilitiesLoading: false,
    };
  }

  /** 初始化页面所需的搜索模板。 */
  async function loadPresets(): Promise<void> {
    try {
      const presets = await listStatPresets();
      statPresets.value = [...presets.defender, ...presets.attacker].filter(
        (preset, index, values) => values.findIndex((item) => item.key === preset.key) === index,
      );
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '无法加载配置模板';
    }
  }

  /** 初始化当前规则集可展示的道具目录，并修正已经失效的选择。 */
  async function loadItems(): Promise<void> {
    itemsLoading.value = true;
    try {
      itemOptions.value = await listBattleItems(rulesetId.value);
      const fallbackIdentifier = itemOptions.value[0]?.identifier ?? 'none';
      if (!itemOptions.value.some((item) => item.identifier === subjectItemIdentifier.value)) {
        subjectItemIdentifier.value = fallbackIdentifier;
      }
      for (const goal of goals.value) {
        if (!itemOptions.value.some((item) => item.identifier === goal.targetItemIdentifier)) {
          goal.targetItemIdentifier = fallbackIdentifier;
        }
      }
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '无法加载道具列表';
      itemOptions.value = [];
      subjectItemIdentifier.value = 'none';
      for (const goal of goals.value) goal.targetItemIdentifier = 'none';
    } finally {
      itemsLoading.value = false;
    }
  }

  /**
   * 设置待配置 Pokémon，并并行读取详情与当前规则集合法特性。
   *
   * @param item 搜索选择器返回的 Pokémon。
   */
  async function selectSubject(item: PokemonSearchItem): Promise<void> {
    error.value = null;
    subjectAbilityIdentifier.value = '';
    subjectAbilityOptions.value = [];
    subjectAbilitiesLoading.value = true;
    result.value = null;
    try {
      const [detail, abilities] = await Promise.all([
        getPokemonDetail(item.pokemon_id, rulesetId.value),
        listPokemonAbilities(item.pokemon_id, rulesetId.value),
      ]);
      subject.value = detail;
      subjectAbilityOptions.value = abilities;
      subjectAbilityIdentifier.value = abilities[0]?.identifier ?? '';
      if (!subjectAbilityIdentifier.value) {
        error.value = '待配置 Pokémon 在当前规则集下没有可选择的特性';
      }
    } catch (caught) {
      subject.value = null;
      error.value = caught instanceof Error ? caught.message : '无法加载待配置 Pokémon 资料';
    } finally {
      subjectAbilitiesLoading.value = false;
    }
  }

  /**
   * 原子地设置目标草稿中的 Pokémon，并读取详情与合法特性。
   *
   * 网络请求和特性完整性校验全部成功后才替换草稿内容；失败时保留原 Pokémon、招式和机制
   * 选择。弹窗保存前不会修改已选列表，因此取消编辑不会产生任何列表副作用。
   *
   * @param goal 新增或编辑弹窗中的独立目标草稿。
   * @param item 搜索选择器返回的 Pokémon。
   * @returns 详情和默认特性均加载成功时返回 true；失败时保留原状态并返回 false。
   */
  async function selectGoalTarget(
    goal: EditableSolverGoal,
    item: PokemonSearchItem,
  ): Promise<boolean> {
    error.value = null;
    goal.targetAbilitiesLoading = true;
    try {
      const [detail, abilities] = await Promise.all([
        getPokemonDetail(item.pokemon_id, rulesetId.value),
        listPokemonAbilities(item.pokemon_id, rulesetId.value),
      ]);
      const defaultAbilityIdentifier = abilities[0]?.identifier ?? '';
      if (!defaultAbilityIdentifier) {
        error.value = '目标 Pokémon 在当前规则集下没有可选择的特性';
        return false;
      }

      // 所有依赖均已准备完成后再一次性提交草稿状态，避免旧目标出现半更新。
      goal.target = detail;
      goal.move = null;
      goal.targetAbilityOptions = abilities;
      goal.targetAbilityIdentifier = defaultAbilityIdentifier;
      goal.targetItemIdentifier = 'none';
      goal.targetPreset = goal.kind === 'attack' ? 'max_hp' : 'max_atk_neutral';
      return true;
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '无法加载目标 Pokémon 资料';
      return false;
    } finally {
      goal.targetAbilitiesLoading = false;
    }
  }

  /**
   * 将完整弹窗草稿保存为列表中的一条紧凑目标。
   *
   * 相同 id 表示编辑已有目标并执行原子替换；新 id 表示新增。保存时再次复制草稿，保证弹窗关闭后
   * 不会继续持有列表对象的可变引用。
   *
   * @param draft 已完成 Pokémon、配置、道具、特性、招式和次数选择的目标草稿。
   * @returns 保存成功时返回 true；必填字段不完整时返回 false 并设置页面错误。
   */
  function saveGoalDraft(draft: EditableSolverGoal): boolean {
    if (!isGoalComplete(draft)) {
      error.value = '请完成目标 Pokémon、配置、道具、特性和招式选择';
      return false;
    }

    const savedGoal = cloneGoal(draft);
    const existingIndex = goals.value.findIndex((goal) => goal.id === draft.id);
    if (existingIndex < 0) {
      goals.value.push(savedGoal);
    } else {
      goals.value.splice(existingIndex, 1, savedGoal);
    }
    result.value = null;
    error.value = null;
    return true;
  }

  /**
   * 删除指定目标；允许清空全部目标，空列表表示当前没有求解约束。
   *
   * @param goalId 要删除的目标 ID。
   */
  function removeGoal(goalId: string): void {
    goals.value = goals.value.filter((goal) => goal.id !== goalId);
  }

  /**
   * 把页面中的目标快照转换成模板求解和属性反推共用的 API 输入。
   *
   * @returns 保留目标 Pokémon、招式、配置、机制和伤害档口径的请求数组。
   */
  function goalRequests(): ConfigurationGoalRequest[] {
    return goals.value.map((goal) => ({
      goal_id: goal.id,
      kind: goal.kind,
      target_pokemon_id: goal.target?.pokemon_id ?? 0,
      move_id: goal.move?.move_id ?? 0,
      required_turns: goal.repetitions,
      target_ability_identifier: goal.targetAbilityIdentifier,
      target_item_identifier:
        goal.targetItemIdentifier === 'none' ? null : goal.targetItemIdentifier,
      target_stat_preset: goal.targetPreset,
      damage_roll_policy: goal.rollPolicy,
    }));
  }

  /**
   * 按当前全局模式提交模板验证或 EV/IV/性格反推请求。
   *
   * 模板模式保持已有配置选择并最多返回三条；反推模式不提交待配置 Pokémon 的模板，
   * 由服务端在合法 EV、IV 与性格空间中最多返回十条候选。
   */
  async function submit(): Promise<void> {
    if (!subject.value || !canSubmit.value) return;
    loading.value = true;
    error.value = null;
    try {
      const commonRequest = {
        ruleset_id: rulesetId.value,
        subject_pokemon_id: subject.value.pokemon_id,
        subject_ability_identifier: subjectAbilityIdentifier.value,
        subject_item_identifier:
          subjectItemIdentifier.value === 'none' ? null : subjectItemIdentifier.value,
        level: level.value,
        goals: goalRequests(),
      };
      result.value = searchMode.value === 'spread'
        ? await searchConfigurationSpreads({
          ...commonRequest,
          max_candidates: 10,
        })
        : await solveConfiguration({
          ...commonRequest,
          allowed_stat_presets: selectedPresetKeys.value,
          max_candidates: 3,
        });
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '求解失败';
    } finally {
      loading.value = false;
    }
  }

  /** 返回用于不可达场景展示的目标证据。 */
  const visibleEvidence = computed<GoalVerification[]>(() => {
    if (!result.value) return [];
    if (result.value.reachable) return result.value.candidates[0]?.goals ?? [];
    return result.value.rejected_goals;
  });

  watch(
    [searchMode, subjectAbilityIdentifier, subjectItemIdentifier, selectedPresetKeys, goals],
    () => {
      if (result.value) result.value = null;
    },
    { deep: true },
  );

  return {
    rulesetId,
    level,
    searchMode,
    subject,
    subjectAbilityIdentifier,
    subjectAbilityOptions,
    subjectAbilitiesLoading,
    subjectItemIdentifier,
    itemOptions,
    itemsLoading,
    goals,
    statPresets,
    selectedPresetKeys,
    loading,
    error,
    result,
    canSubmit,
    visibleEvidence,
    isGoalComplete,
    createGoalDraft,
    cloneGoal,
    loadPresets,
    loadItems,
    selectSubject,
    selectGoalTarget,
    saveGoalDraft,
    removeGoal,
    submit,
  };
}
