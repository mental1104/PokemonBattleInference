import {
  computed,
  getCurrentInstance,
  inject,
  provide,
  ref,
  watch,
  type InjectionKey,
} from 'vue';
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
  type ConfigurationGoalKind,
  type ConfigurationGoalRequest,
  type ConfigurationSearchMode,
  type DamageRollPolicy,
  type GoalVerification,
} from '../api/configurationSolver';
import {
  searchConfigurationSpreadsWithSpeed,
  solveConfigurationWithSpeed,
  type ConfigurationSpeedGoalRequest,
  type SpeedAwareSolveConfigurationResponse,
  type SpeedGoalVerification,
} from '../api/configurationSpeedGoals';

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

export interface EditableSpeedGoal {
  id: string;
  target: PokemonDetail | null;
  targetPreset: string;
  targetLoading: boolean;
}

const DEFAULT_PRESETS = ['max_hp_def_plus', 'max_hp_spdef_plus', 'max_spatk_plus', 'max_atk_plus'];

/**
 * 创建配置反向求解页面的一套独立状态。
 *
 * 状态同时维护攻目标、防目标和严格速度目标；App 会把同一实例提供给主页面与速度目标
 * Teleport 组件。单元测试直接调用时仍会得到独立实例，避免跨用例污染。
 *
 * @returns 包含页面状态、目标编辑方法、提交动作和结果证据的组合式 API。
 */
export function createConfigurationSolver() {
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
  const speedGoals = ref<EditableSpeedGoal[]>([]);
  const statPresets = ref<StatPreset[]>([]);
  const selectedPresetKeys = ref<string[]>([...DEFAULT_PRESETS]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const result = ref<SpeedAwareSolveConfigurationResponse | null>(null);

  const canSubmit = computed(() => {
    const searchInputReady = searchMode.value === 'spread'
      || selectedPresetKeys.value.length > 0;
    const hasAnyGoal = goals.value.length > 0 || speedGoals.value.length > 0;
    return Boolean(
      subject.value
        && subjectAbilityIdentifier.value
        && hasAnyGoal
        && goals.value.every(isGoalComplete)
        && speedGoals.value.every(isSpeedGoalComplete)
        && searchInputReady
        && !loading.value,
    );
  });

  /**
   * 判断一条伤害目标是否已经包含可提交的 Pokémon、招式和机制选择。
   *
   * @param goal 新增或编辑弹窗中的伤害目标草稿。
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
   * 判断速度目标是否已经选择参照 Pokémon 与明确配置。
   *
   * @param goal 新增或编辑中的速度目标草稿。
   * @returns 可以提交严格速度比较时返回 true。
   */
  function isSpeedGoalComplete(goal: EditableSpeedGoal): boolean {
    return Boolean(goal.target && goal.targetPreset);
  }

  /**
   * 创建一条尚未写入已选列表的伤害目标草稿。
   *
   * @param kind attack 表示待配置 Pokémon 主动攻击，defense 表示承受攻击。
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
   * 创建一条严格速度目标草稿。
   *
   * @returns 默认使用极限速度配置作为参照的独立目标对象。
   */
  function createSpeedGoalDraft(): EditableSpeedGoal {
    return {
      id: `speed-goal-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      target: null,
      targetPreset: 'max_speed_plus',
      targetLoading: false,
    };
  }

  /**
   * 为伤害目标编辑弹窗复制一份与已选列表隔离的快照。
   *
   * @param goal 当前已保存的伤害目标。
   * @returns 可独立修改的深层业务快照。
   */
  function cloneGoal(goal: EditableSolverGoal): EditableSolverGoal {
    return {
      ...goal,
      target: clonePokemonDetail(goal.target),
      move: goal.move === null ? null : { ...goal.move },
      targetAbilityOptions: [...goal.targetAbilityOptions],
      targetAbilitiesLoading: false,
    };
  }

  /**
   * 为速度目标编辑弹窗复制一份与已选列表隔离的快照。
   *
   * @param goal 当前已保存的速度目标。
   * @returns 取消编辑不会污染原列表的目标副本。
   */
  function cloneSpeedGoal(goal: EditableSpeedGoal): EditableSpeedGoal {
    return {
      ...goal,
      target: clonePokemonDetail(goal.target),
      targetLoading: false,
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

  /** 初始化当前规则集可展示的道具目录，并修正已经失效的伤害目标选择。 */
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
   * 原子地设置伤害目标草稿中的 Pokémon，并读取详情与合法特性。
   *
   * @param goal 新增或编辑弹窗中的独立伤害目标草稿。
   * @param item 搜索选择器返回的 Pokémon。
   * @returns 详情和默认特性均加载成功时返回 true；失败时保留原状态。
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

      // 所有依赖均准备完成后再一次性提交草稿，避免旧目标出现半更新。
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
   * 设置速度目标的参照 Pokémon；速度比较不读取道具、特性或招式。
   *
   * @param goal 新增或编辑中的速度目标草稿。
   * @param item 用户选中的参照 Pokémon。
   * @returns 目标详情加载成功时返回 true；失败时保留旧目标并返回 false。
   */
  async function selectSpeedGoalTarget(
    goal: EditableSpeedGoal,
    item: PokemonSearchItem,
  ): Promise<boolean> {
    error.value = null;
    goal.targetLoading = true;
    try {
      const detail = await getPokemonDetail(item.pokemon_id, rulesetId.value);
      goal.target = detail;
      goal.targetPreset = 'max_speed_plus';
      return true;
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '无法加载速度目标 Pokémon 资料';
      return false;
    } finally {
      goal.targetLoading = false;
    }
  }

  /**
   * 将完整伤害目标草稿保存为列表中的紧凑目标。
   *
   * @param draft 已完成 Pokémon、配置、机制、招式和次数选择的草稿。
   * @returns 保存成功时返回 true；必填字段不完整时返回 false。
   */
  function saveGoalDraft(draft: EditableSolverGoal): boolean {
    if (!isGoalComplete(draft)) {
      error.value = '请完成目标 Pokémon、配置、道具、特性和招式选择';
      return false;
    }
    saveById(goals.value, cloneGoal(draft));
    result.value = null;
    error.value = null;
    return true;
  }

  /**
   * 将完整速度目标草稿保存为速度列中的紧凑目标。
   *
   * @param draft 已选择参照 Pokémon 和配置的草稿。
   * @returns 保存成功时返回 true；信息不完整时返回 false。
   */
  function saveSpeedGoalDraft(draft: EditableSpeedGoal): boolean {
    if (!isSpeedGoalComplete(draft)) {
      error.value = '请完成速度目标 Pokémon 和配置选择';
      return false;
    }
    saveById(speedGoals.value, cloneSpeedGoal(draft));
    result.value = null;
    error.value = null;
    return true;
  }

  /** 删除指定伤害目标。 */
  function removeGoal(goalId: string): void {
    goals.value = goals.value.filter((goal) => goal.id !== goalId);
  }

  /** 删除指定严格速度目标。 */
  function removeSpeedGoal(goalId: string): void {
    speedGoals.value = speedGoals.value.filter((goal) => goal.id !== goalId);
  }

  /** 把页面中的伤害目标快照转换成 API 输入。 */
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

  /** 把页面中的严格速度目标转换成 API 输入。 */
  function speedGoalRequests(): ConfigurationSpeedGoalRequest[] {
    return speedGoals.value.map((goal) => ({
      goal_id: goal.id,
      target_pokemon_id: goal.target?.pokemon_id ?? 0,
      target_stat_preset: goal.targetPreset,
    }));
  }

  /**
   * 按全局模式提交模板验证或 EV、IV 与性格反推请求。
   *
   * 两种模式都会把伤害目标和严格速度目标作为同一套配置必须同时满足的约束。
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
        speed_goals: speedGoalRequests(),
      };
      result.value = searchMode.value === 'spread'
        ? await searchConfigurationSpreadsWithSpeed({
          ...commonRequest,
          max_candidates: 10,
        })
        : await solveConfigurationWithSpeed({
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

  /** 返回当前候选或不可达响应中的伤害目标证据。 */
  const visibleEvidence = computed<GoalVerification[]>(() => {
    if (!result.value) return [];
    if (result.value.reachable) return result.value.candidates[0]?.goals ?? [];
    return result.value.rejected_goals;
  });

  /** 返回当前候选或不可达响应中的严格速度目标证据。 */
  const visibleSpeedEvidence = computed<SpeedGoalVerification[]>(() => {
    if (!result.value) return [];
    if (result.value.reachable) return result.value.candidates[0]?.speed_goals ?? [];
    return result.value.rejected_speed_goals;
  });

  watch(
    [
      searchMode,
      subjectAbilityIdentifier,
      subjectItemIdentifier,
      selectedPresetKeys,
      goals,
      speedGoals,
    ],
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
    speedGoals,
    statPresets,
    selectedPresetKeys,
    loading,
    error,
    result,
    canSubmit,
    visibleEvidence,
    visibleSpeedEvidence,
    isGoalComplete,
    isSpeedGoalComplete,
    createGoalDraft,
    createSpeedGoalDraft,
    cloneGoal,
    cloneSpeedGoal,
    loadPresets,
    loadItems,
    selectSubject,
    selectGoalTarget,
    selectSpeedGoalTarget,
    saveGoalDraft,
    saveSpeedGoalDraft,
    removeGoal,
    removeSpeedGoal,
    submit,
  };
}

export type ConfigurationSolverState = ReturnType<typeof createConfigurationSolver>;

const CONFIGURATION_SOLVER_KEY: InjectionKey<ConfigurationSolverState> = Symbol(
  'configuration-solver',
);

/**
 * 在 App 根组件提供一套共享求解状态。
 *
 * @returns 已提供给后代组件的求解状态，供根组件必要时直接访问。
 */
export function provideConfigurationSolver(): ConfigurationSolverState {
  const solver = createConfigurationSolver();
  provide(CONFIGURATION_SOLVER_KEY, solver);
  return solver;
}

/**
 * 读取上层提供的共享求解状态；测试或独立挂载时创建隔离实例。
 *
 * @returns 当前组件树共享的求解状态，或调用方专属的新状态。
 */
export function useConfigurationSolver(): ConfigurationSolverState {
  if (getCurrentInstance() !== null) {
    return inject(CONFIGURATION_SOLVER_KEY, null) ?? createConfigurationSolver();
  }
  return createConfigurationSolver();
}

/**
 * 深复制 Pokémon 详情，避免弹窗草稿修改嵌套数组或种族值时污染已保存目标。
 *
 * @param pokemon 原始详情；null 表示尚未选择。
 * @returns 与原对象无可变嵌套引用共享的新对象，或 null。
 */
function clonePokemonDetail(pokemon: PokemonDetail | null): PokemonDetail | null {
  if (pokemon === null) return null;
  return {
    ...pokemon,
    types: [...pokemon.types],
    type_names: [...pokemon.type_names],
    base_stats: { ...pokemon.base_stats },
  };
}

/**
 * 按稳定 ID 新增或原子替换目标快照。
 *
 * @param collection 当前响应式数组的可变值。
 * @param item 已经完成深复制的目标快照。
 */
function saveById<T extends { id: string }>(collection: T[], item: T): void {
  const existingIndex = collection.findIndex((candidate) => candidate.id === item.id);
  if (existingIndex < 0) {
    collection.push(item);
  } else {
    collection.splice(existingIndex, 1, item);
  }
}
