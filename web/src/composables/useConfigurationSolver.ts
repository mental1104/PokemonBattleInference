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
  solveConfiguration,
  type ConfigurationGoalKind,
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

/** 管理配置反向求解页面的 Pokémon、机制选择、目标列表和提交状态。 */
export function useConfigurationSolver() {
  const rulesetId = ref('pokemon-champion');
  const level = ref(50);
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
    return Boolean(
      subject.value
        && subjectAbilityIdentifier.value
        && goals.value.length > 0
        && goals.value.every(
          (goal) =>
            goal.target
            && goal.move
            && goal.targetAbilityIdentifier
            && goal.repetitions > 0,
        )
        && selectedPresetKeys.value.length > 0
        && !loading.value,
    );
  });

  /**
   * 创建一条尚未写入已选列表的目标草稿。
   *
   * @param kind attack 表示待配置 Pokémon 主动攻击，defense 表示待配置 Pokémon 承受攻击。
   * @returns 带对应默认配置和随机伤害档的独立目标对象。
   */
  function newGoal(kind: ConfigurationGoalKind): EditableSolverGoal {
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
   * 设置某条目标中的对手 Pokémon，并并行读取详情与合法特性。
   *
   * @param goal 需要更新的目标草稿或已选目标对象。
   * @param item 搜索选择器返回的 Pokémon。
   * @returns 详情和特性均加载成功时返回 true；失败时清空目标并返回 false。
   */
  async function selectGoalTarget(
    goal: EditableSolverGoal,
    item: PokemonSearchItem,
  ): Promise<boolean> {
    error.value = null;
    goal.move = null;
    goal.targetAbilityIdentifier = '';
    goal.targetAbilityOptions = [];
    goal.targetAbilitiesLoading = true;
    result.value = null;
    try {
      const [detail, abilities] = await Promise.all([
        getPokemonDetail(item.pokemon_id, rulesetId.value),
        listPokemonAbilities(item.pokemon_id, rulesetId.value),
      ]);
      goal.target = detail;
      goal.targetAbilityOptions = abilities;
      goal.targetAbilityIdentifier = abilities[0]?.identifier ?? '';
      if (!goal.targetAbilityIdentifier) {
        error.value = '目标 Pokémon 在当前规则集下没有可选择的特性';
      }
      return true;
    } catch (caught) {
      goal.target = null;
      error.value = caught instanceof Error ? caught.message : '无法加载目标 Pokémon 资料';
      return false;
    } finally {
      goal.targetAbilitiesLoading = false;
    }
  }

  /**
   * 根据弹窗中已经确认的 Pokémon 新增一条完整目标。
   *
   * 未成功读取目标详情时不会把空白对象写入已选目标列表，避免用户把“新增中”误认为
   * 已经选中的目标。
   *
   * @param kind attack 放入攻目标列，defense 放入防目标列。
   * @param item 用户在新增弹窗中确认的 Pokémon。
   * @returns 新增成功时返回目标对象；加载失败时返回 null。
   */
  async function addGoalWithTarget(
    kind: ConfigurationGoalKind,
    item: PokemonSearchItem,
  ): Promise<EditableSolverGoal | null> {
    const goal = newGoal(kind);
    if (!(await selectGoalTarget(goal, item))) return null;

    goals.value.push(goal);
    return goal;
  }

  /**
   * 删除指定目标；允许清空全部目标，空列表表示当前没有求解约束。
   *
   * @param goalId 要删除的目标 ID。
   */
  function removeGoal(goalId: string): void {
    goals.value = goals.value.filter((goal) => goal.id !== goalId);
  }

  /** 提交当前多目标反向求解请求。 */
  async function submit(): Promise<void> {
    if (!subject.value || !canSubmit.value) return;
    loading.value = true;
    error.value = null;
    try {
      result.value = await solveConfiguration({
        ruleset_id: rulesetId.value,
        subject_pokemon_id: subject.value.pokemon_id,
        subject_ability_identifier: subjectAbilityIdentifier.value,
        subject_item_identifier:
          subjectItemIdentifier.value === 'none' ? null : subjectItemIdentifier.value,
        level: level.value,
        goals: goals.value.map((goal) => ({
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
        })),
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
    [subjectAbilityIdentifier, subjectItemIdentifier, selectedPresetKeys, goals],
    () => {
      if (result.value) result.value = null;
    },
    { deep: true },
  );

  return {
    rulesetId,
    level,
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
    loadPresets,
    loadItems,
    selectSubject,
    selectGoalTarget,
    addGoalWithTarget,
    removeGoal,
    submit,
  };
}
