import { computed, ref, watch } from 'vue';
import {
  calculateDamage,
  getPokemonDetail,
  listBattleItems,
  listStatPresets,
  type BattleItemOption,
  type CalculateDamageResponse,
  type MoveSearchItem,
  type PokemonDetail,
  type PokemonSearchItem,
  type StatPreset,
} from '../api/calculator';

export type CalculatorState = 'EMPTY' | 'ATTACKER_SELECTED' | 'MOVE_SELECTED' | 'READY' | 'CALCULATING' | 'RESULT';

/**
 * 管理基础伤害计算器的双方选择、异步加载、提交请求和旧结果失效语义。
 *
 * @returns 页面可直接绑定的响应式状态、派生状态和计算器操作函数；攻击方与防守方道具状态彼此独立。
 */
export function useDamageCalculator() {
  const rulesetId = ref('pokemon-champion');
  const level = ref(50);
  const attacker = ref<PokemonDetail | null>(null);
  const defender = ref<PokemonDetail | null>(null);
  const move = ref<MoveSearchItem | null>(null);
  const attackerItemIdentifier = ref('none');
  const defenderItemIdentifier = ref('none');
  const itemOptions = ref<BattleItemOption[]>([]);
  const itemsLoading = ref(false);
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

  /**
   * 初始化当前规则集可选择的已实现战斗持有道具，并修正双方已经失效的选择。
   *
   * @returns 道具列表请求完成后 resolve；请求失败时双方都回退为不携带道具。
   */
  async function loadItems(): Promise<void> {
    itemsLoading.value = true;
    try {
      itemOptions.value = await listBattleItems(rulesetId.value);
      const fallbackIdentifier = itemOptions.value[0]?.identifier ?? 'none';
      if (!itemOptions.value.some((item) => item.identifier === attackerItemIdentifier.value)) {
        attackerItemIdentifier.value = fallbackIdentifier;
      }
      if (!itemOptions.value.some((item) => item.identifier === defenderItemIdentifier.value)) {
        defenderItemIdentifier.value = fallbackIdentifier;
      }
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '无法加载道具列表';
      itemOptions.value = [];
      attackerItemIdentifier.value = 'none';
      defenderItemIdentifier.value = 'none';
    } finally {
      itemsLoading.value = false;
    }
  }

  /**
   * 选择攻击方后读取详情，并清空依赖旧攻击方的招式和伤害结果。
   *
   * @param item 用户从攻击方选择器选中的 Pokémon 搜索结果。
   * @returns 攻击方详情加载完成后 resolve 的 Promise。
   */
  async function selectAttacker(item: PokemonSearchItem): Promise<void> {
    error.value = null;
    attacker.value = await getPokemonDetail(item.pokemon_id, rulesetId.value);
    // 招式列表由 MoveSelector 按新攻击方重新分页读取，旧选择不能继续提交。
    move.value = null;
    result.value = null;
    staleResult.value = false;
  }

  /**
   * 选择防守方后读取详情，保留双方其他已经完成的输入。
   *
   * @param item 用户从防守方选择器选中的 Pokémon 搜索结果。
   * @returns 防守方详情加载完成后 resolve 的 Promise。
   */
  async function selectDefender(item: PokemonSearchItem): Promise<void> {
    error.value = null;
    defender.value = await getPokemonDetail(item.pokemon_id, rulesetId.value);
  }

  /**
   * 提交当前双方 Pokémon、配置、持有道具和招式选择，得到真实 domain 伤害结果。
   *
   * @returns 服务端计算完成后 resolve；输入不完整时直接结束且不发起请求。
   */
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
          item_identifier: attackerItemIdentifier.value === 'none' ? null : attackerItemIdentifier.value,
        },
        defender: {
          pokemon_id: defender.value.pokemon_id,
          level: level.value,
          stat_preset: defenderPreset.value,
          item_identifier: defenderItemIdentifier.value === 'none' ? null : defenderItemIdentifier.value,
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
      defenderItemIdentifier,
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
    defenderItemIdentifier,
    itemOptions,
    itemsLoading,
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
