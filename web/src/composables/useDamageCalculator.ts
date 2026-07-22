import { computed, ref, watch } from 'vue';
import {
  calculateDamage,
  getPokemonDetail,
  listPokemonMoves,
  listStatPresets,
  type CalculateDamageResponse,
  type MoveSearchItem,
  type PokemonDetail,
  type PokemonSearchItem,
  type StatPreset,
} from '../api/calculator';

export type CalculatorState = 'EMPTY' | 'ATTACKER_SELECTED' | 'MOVE_SELECTED' | 'READY' | 'CALCULATING' | 'RESULT';

/** 管理基础伤害计算器的选择状态、加载状态和结果失效语义。 */
export function useDamageCalculator() {
  const rulesetId = ref('pokemon-champion');
  const level = ref(50);
  const attacker = ref<PokemonDetail | null>(null);
  const defender = ref<PokemonDetail | null>(null);
  const move = ref<MoveSearchItem | null>(null);
  const moves = ref<MoveSearchItem[]>([]);
  const attackerPreset = ref('max_atk_neutral');
  const defenderPreset = ref('max_hp');
  const attackerPresets = ref<StatPreset[]>([]);
  const defenderPresets = ref<StatPreset[]>([]);
  const result = ref<CalculateDamageResponse | null>(null);
  const staleResult = ref(false);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const state = computed<CalculatorState>(() => {
    if (loading.value) return 'CALCULATING';
    if (result.value && !staleResult.value) return 'RESULT';
    if (attacker.value && move.value && defender.value) return 'READY';
    if (attacker.value && move.value) return 'MOVE_SELECTED';
    if (attacker.value) return 'ATTACKER_SELECTED';
    return 'EMPTY';
  });

  const canCalculate = computed(() => Boolean(attacker.value && defender.value && move.value && !loading.value));

  /** 初始化配置模板；失败只影响模板按钮，计算前仍会由服务端校验。 */
  async function loadPresets(): Promise<void> {
    try {
      const presets = await listStatPresets();
      attackerPresets.value = presets.attacker;
      defenderPresets.value = presets.defender;
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '无法加载配置模板';
    }
  }

  /** 选择攻击方后读取详情并刷新可计算招式列表。 */
  async function selectAttacker(item: PokemonSearchItem): Promise<void> {
    error.value = null;
    attacker.value = await getPokemonDetail(item.pokemon_id, rulesetId.value);
    move.value = null;
    result.value = null;
    staleResult.value = false;
    moves.value = await listPokemonMoves(item.pokemon_id, rulesetId.value, '');
  }

  /** 根据攻击方和搜索词刷新招式列表。 */
  async function refreshMoves(query: string): Promise<void> {
    if (!attacker.value) {
      moves.value = [];
      return;
    }
    moves.value = await listPokemonMoves(attacker.value.pokemon_id, rulesetId.value, query);
  }

  /** 选择防守方后读取详情。 */
  async function selectDefender(item: PokemonSearchItem): Promise<void> {
    error.value = null;
    defender.value = await getPokemonDetail(item.pokemon_id, rulesetId.value);
  }

  /** 提交当前选择，得到真实 domain 伤害结果。 */
  async function submit(): Promise<void> {
    if (!attacker.value || !defender.value || !move.value) return;
    loading.value = true;
    error.value = null;
    try {
      result.value = await calculateDamage({
        ruleset_id: rulesetId.value,
        attacker: {
          pokemon_id: attacker.value.pokemon_id,
          level: level.value,
          stat_preset: attackerPreset.value,
        },
        defender: {
          pokemon_id: defender.value.pokemon_id,
          level: level.value,
          stat_preset: defenderPreset.value,
        },
        move_id: move.value.move_id,
      });
      staleResult.value = false;
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '计算失败';
    } finally {
      loading.value = false;
    }
  }

  /** 任一输入变化后标记旧结果过期，避免页面继续显示为有效结论。 */
  watch([attacker, defender, move, attackerPreset, defenderPreset], () => {
    if (result.value) staleResult.value = true;
  });

  return {
    rulesetId,
    level,
    attacker,
    defender,
    move,
    moves,
    attackerPreset,
    defenderPreset,
    attackerPresets,
    defenderPresets,
    result,
    staleResult,
    loading,
    error,
    state,
    canCalculate,
    loadPresets,
    selectAttacker,
    selectDefender,
    refreshMoves,
    submit,
  };
}
