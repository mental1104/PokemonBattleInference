import { computed, ref } from 'vue';
import {
  getPokemonDetail,
  listStatPresets,
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
  rollPolicy: DamageRollPolicy;
}

const DEFAULT_PRESETS = ['max_hp_def_plus', 'max_hp_spdef_plus', 'max_spatk_plus', 'max_atk_plus'];

/** 管理配置反向求解页面的选择、目标列表和提交状态。 */
export function useConfigurationSolver() {
  const rulesetId = ref('pokemon-champion');
  const level = ref(50);
  const subject = ref<PokemonDetail | null>(null);
  const goals = ref<EditableSolverGoal[]>([newGoal()]);
  const statPresets = ref<StatPreset[]>([]);
  const selectedPresetKeys = ref<string[]>([...DEFAULT_PRESETS]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  const result = ref<SolveConfigurationResponse | null>(null);

  const canSubmit = computed(() => {
    return Boolean(
      subject.value
        && goals.value.length > 0
        && goals.value.every((goal) => goal.target && goal.move && goal.repetitions > 0)
        && selectedPresetKeys.value.length > 0
        && !loading.value,
    );
  });

  /** 创建一条默认防守目标，使用最高伤害档验证稳定存活。 */
  function newGoal(): EditableSolverGoal {
    return {
      id: `goal-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      kind: 'defense',
      target: null,
      move: null,
      repetitions: 1,
      targetPreset: 'max_atk_neutral',
      rollPolicy: 'max',
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

  /**
   * 设置待配置 Pokémon。
   *
   * @param item 搜索选择器返回的 Pokémon。
   */
  async function selectSubject(item: PokemonSearchItem): Promise<void> {
    error.value = null;
    subject.value = await getPokemonDetail(item.pokemon_id, rulesetId.value);
    result.value = null;
  }

  /**
   * 设置某条目标中的对手 Pokémon。
   *
   * @param goal 需要更新的目标对象。
   * @param item 搜索选择器返回的 Pokémon。
   */
  async function selectGoalTarget(goal: EditableSolverGoal, item: PokemonSearchItem): Promise<void> {
    error.value = null;
    goal.target = await getPokemonDetail(item.pokemon_id, rulesetId.value);
    goal.move = null;
    result.value = null;
  }

  /** 新增一条目标。 */
  function addGoal(): void {
    goals.value.push(newGoal());
  }

  /**
   * 删除指定目标；保留至少一条目标，避免页面进入不可提交的空列表。
   *
   * @param goalId 要删除的目标 ID。
   */
  function removeGoal(goalId: string): void {
    if (goals.value.length === 1) return;
    goals.value = goals.value.filter((goal) => goal.id !== goalId);
  }

  /**
   * 切换可搜索配置模板。
   *
   * @param key 配置模板 key。
   */
  function togglePreset(key: string): void {
    if (selectedPresetKeys.value.includes(key)) {
      selectedPresetKeys.value = selectedPresetKeys.value.filter((item) => item !== key);
    } else {
      selectedPresetKeys.value = [...selectedPresetKeys.value, key];
    }
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
        level: level.value,
        goals: goals.value.map((goal) => ({
          goal_id: goal.id,
          kind: goal.kind,
          target_pokemon_id: goal.target?.pokemon_id ?? 0,
          move_id: goal.move?.move_id ?? 0,
          required_turns: goal.repetitions,
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

  return {
    rulesetId,
    level,
    subject,
    goals,
    statPresets,
    selectedPresetKeys,
    loading,
    error,
    result,
    canSubmit,
    visibleEvidence,
    loadPresets,
    selectSubject,
    selectGoalTarget,
    addGoal,
    removeGoal,
    togglePreset,
    submit,
  };
}
