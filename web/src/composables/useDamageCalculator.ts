import { computed, ref, watch } from 'vue';
import {
  calculateDamage,
  getPokemonDetail,
  listBattleItems,
  listPokemonAbilities,
  listStatPresets,
  type BattleAbilityOption,
  type BattleItemOption,
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
  const attackerItemIdentifier = ref('none');
  const itemOptions = ref<BattleItemOption[]>([]);
  const itemsLoading = ref(false);
  const attackerAbilityIdentifier = ref('');
  const defenderAbilityIdentifier = ref('');
  const attackerAbilityOptions = ref<BattleAbilityOption[]>([]);
  const defenderAbilityOptions = ref<BattleAbilityOption[]>([]);
  const attackerAbilitiesLoading = ref(false);
  const defenderAbilitiesLoading = ref(false);
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
    if (
      attacker.value &&
      move.value &&
      defender.value &&
      attackerAbilityIdentifier.value &&
      defenderAbilityIdentifier.value
    ) {
      return 'READY';
    }
    if (attacker.value && move.value) return 'MOVE_SELECTED';
    if (attacker.value) return 'ATTACKER_SELECTED';
    return 'EMPTY';
  });

  const canCalculate = computed(() => Boolean(
    attacker.value &&
      defender.value &&
      move.value &&
      attackerAbilityIdentifier.value &&
      defenderAbilityIdentifier.value &&
      !loading.value,
  ));

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

  /** 初始化当前规则集可选择的已实现战斗持有道具。 */
  async function loadItems(): Promise<void> {
    itemsLoading.value = true;
    try {
      itemOptions.value = await listBattleItems(rulesetId.value);
      if (!itemOptions.value.some((item) => item.identifier === attackerItemIdentifier.value)) {
        attackerItemIdentifier.value = itemOptions.value[0]?.identifier ?? 'none';
      }
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '无法加载道具列表';
      itemOptions.value = [];
      attackerItemIdentifier.value = 'none';
    } finally {
      itemsLoading.value = false;
    }
  }

  /**
   * 选择攻击方后读取详情和合法特性，并清空依赖旧攻击方的输入与结果。
   *
   * @param item 用户从攻击方选择器选中的 Pokémon 搜索结果。
   */
  async function selectAttacker(item: PokemonSearchItem): Promise<void> {
    error.value = null;
    move.value = null;
    attackerAbilityIdentifier.value = '';
    attackerAbilityOptions.value = [];
    attackerAbilitiesLoading.value = true;
    result.value = null;
    staleResult.value = false;
    try {
      const [detail, abilities] = await Promise.all([
        getPokemonDetail(item.pokemon_id, rulesetId.value),
        listPokemonAbilities(item.pokemon_id, rulesetId.value),
      ]);
      attacker.value = detail;
      attackerAbilityOptions.value = abilities;
      attackerAbilityIdentifier.value = abilities[0]?.identifier ?? '';
      if (!attackerAbilityIdentifier.value) {
        error.value = '攻击方在当前规则集下没有可选择的特性';
      }
    } catch (caught) {
      attacker.value = null;
      error.value = caught instanceof Error ? caught.message : '无法加载攻击方资料';
    } finally {
      attackerAbilitiesLoading.value = false;
    }
  }

  /** 选择防守方后读取详情和合法特性，并默认选中第一个特性。 */
  async function selectDefender(item: PokemonSearchItem): Promise<void> {
    error.value = null;
    defenderAbilityIdentifier.value = '';
    defenderAbilityOptions.value = [];
    defenderAbilitiesLoading.value = true;
    try {
      const [detail, abilities] = await Promise.all([
        getPokemonDetail(item.pokemon_id, rulesetId.value),
        listPokemonAbilities(item.pokemon_id, rulesetId.value),
      ]);
      defender.value = detail;
      defenderAbilityOptions.value = abilities;
      defenderAbilityIdentifier.value = abilities[0]?.identifier ?? '';
      if (!defenderAbilityIdentifier.value) {
        error.value = '防守方在当前规则集下没有可选择的特性';
      }
    } catch (caught) {
      defender.value = null;
      error.value = caught instanceof Error ? caught.message : '无法加载防守方资料';
    } finally {
      defenderAbilitiesLoading.value = false;
    }
  }

  /** 提交当前选择，得到真实 domain 伤害结果。 */
  async function submit(): Promise<void> {
    if (
      !attacker.value ||
      !defender.value ||
      !move.value ||
      !attackerAbilityIdentifier.value ||
      !defenderAbilityIdentifier.value
    ) return;
    loading.value = true;
    error.value = null;
    try {
      result.value = await calculateDamage({
        ruleset_id: rulesetId.value,
        attacker: {
          pokemon_id: attacker.value.pokemon_id,
          level: level.value,
          stat_preset: attackerPreset.value,
          ability_identifier: attackerAbilityIdentifier.value,
          item_identifier: attackerItemIdentifier.value === 'none' ? null : attackerItemIdentifier.value,
        },
        defender: {
          pokemon_id: defender.value.pokemon_id,
          level: level.value,
          stat_preset: defenderPreset.value,
          ability_identifier: defenderAbilityIdentifier.value,
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
  watch(
    [
      attacker,
      defender,
      move,
      attackerPreset,
      defenderPreset,
      attackerItemIdentifier,
      attackerAbilityIdentifier,
      defenderAbilityIdentifier,
    ],
    () => {
      if (result.value) staleResult.value = true;
    },
  );

  return {
    rulesetId,
    level,
    attacker,
    defender,
    move,
    attackerItemIdentifier,
    itemOptions,
    itemsLoading,
    attackerAbilityIdentifier,
    defenderAbilityIdentifier,
    attackerAbilityOptions,
    defenderAbilityOptions,
    attackerAbilitiesLoading,
    defenderAbilitiesLoading,
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
    loadItems,
    selectAttacker,
    selectDefender,
    submit,
  };
}
