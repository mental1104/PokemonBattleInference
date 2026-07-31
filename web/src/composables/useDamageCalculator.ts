import { computed, ref, watch } from 'vue';
import {
  calculateDamage,
  createNeutralBattleStatStages,
  getPokemonDetail,
  hasNonNeutralBattleStatStages,
  listBattleItems,
  listPokemonAbilities,
  listStatPresets,
  type BattleAbilityOption,
  type BattleItemOption,
  type BattleStatStages,
  type CalculateDamageResponse,
  type CalculatorPokemonInput,
  type MoveSearchItem,
  type PokemonDetail,
  type PokemonSearchItem,
  type StatPreset,
} from '../api/calculator';

export type CalculatorState = 'EMPTY' | 'ATTACKER_SELECTED' | 'MOVE_SELECTED' | 'READY' | 'CALCULATING' | 'RESULT';

/**
 * 管理基础伤害计算器的双方选择、异步加载、提交请求和旧结果失效语义。
 *
 * @returns 页面可直接绑定的响应式状态、派生状态和计算器操作函数；双方道具、特性与能力等级彼此独立。
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
  const attackerAbilityIdentifier = ref('');
  const defenderAbilityIdentifier = ref('');
  const attackerAbilityOptions = ref<BattleAbilityOption[]>([]);
  const defenderAbilityOptions = ref<BattleAbilityOption[]>([]);
  const attackerAbilitiesLoading = ref(false);
  const defenderAbilitiesLoading = ref(false);
  const attackerStatStages = ref<BattleStatStages>(createNeutralBattleStatStages());
  const defenderStatStages = ref<BattleStatStages>(createNeutralBattleStatStages());
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
   * 选择攻击方后并行读取详情和合法特性，并清空依赖旧攻击方的招式、能力等级与伤害结果。
   *
   * @param item 用户从攻击方选择器选中的 Pokémon 搜索结果。
   * @returns 攻击方详情与特性列表加载完成后 resolve 的 Promise。
   */
  async function selectAttacker(item: PokemonSearchItem): Promise<void> {
    error.value = null;
    move.value = null;
    attackerAbilityIdentifier.value = '';
    attackerAbilityOptions.value = [];
    attackerStatStages.value = createNeutralBattleStatStages();
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

  /**
   * 选择防守方后并行读取详情和合法特性，并把新 Pokémon 的能力等级重置为中性。
   *
   * @param item 用户从防守方选择器选中的 Pokémon 搜索结果。
   * @returns 防守方详情和特性加载完成后 resolve 的 Promise。
   */
  async function selectDefender(item: PokemonSearchItem): Promise<void> {
    error.value = null;
    defenderAbilityIdentifier.value = '';
    defenderAbilityOptions.value = [];
    defenderStatStages.value = createNeutralBattleStatStages();
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

  /**
   * 构造一侧计算请求；中性能力等级保持兼容旧请求，不额外发送七个零值字段。
   *
   * @param pokemon 当前侧已加载的可信 Pokémon 详情。
   * @param statPreset 当前侧配置模板或持久化快照标识。
   * @param abilityIdentifier 当前侧必选且属于该 Pokémon 的特性 identifier。
   * @param itemIdentifier 当前侧道具 identifier；none 会转换成 null。
   * @param statStages 当前侧七项 -6 到 +6 的战斗能力等级。
   * @returns 可直接放入 CalculateDamageRequest 的单侧输入。
   */
  function buildPokemonInput(
    pokemon: PokemonDetail,
    statPreset: string,
    abilityIdentifier: string,
    itemIdentifier: string,
    statStages: BattleStatStages,
  ): CalculatorPokemonInput {
    const input: CalculatorPokemonInput = {
      pokemon_id: pokemon.pokemon_id,
      level: level.value,
      stat_preset: statPreset,
      ability_identifier: abilityIdentifier,
      item_identifier: itemIdentifier === 'none' ? null : itemIdentifier,
    };
    if (hasNonNeutralBattleStatStages(statStages)) {
      // 复制快照，避免请求序列化期间用户继续操作而改变已提交对象。
      input.stat_stages = { ...statStages };
    }
    return input;
  }

  /**
   * 提交当前双方 Pokémon、配置、持有道具、必选特性、能力等级和招式，得到真实 domain 伤害结果。
   *
   * @returns 服务端计算完成后 resolve；任一必填输入不完整时直接结束且不发起请求。
   */
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
        attacker: buildPokemonInput(
          attacker.value,
          attackerPreset.value,
          attackerAbilityIdentifier.value,
          attackerItemIdentifier.value,
          attackerStatStages.value,
        ),
        defender: buildPokemonInput(
          defender.value,
          defenderPreset.value,
          defenderAbilityIdentifier.value,
          defenderItemIdentifier.value,
          defenderStatStages.value,
        ),
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
      attackerAbilityIdentifier,
      defenderAbilityIdentifier,
      attackerStatStages,
      defenderStatStages,
    ],
    () => {
      if (result.value) staleResult.value = true;
    },
    { deep: true },
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
    attackerAbilityIdentifier,
    defenderAbilityIdentifier,
    attackerAbilityOptions,
    defenderAbilityOptions,
    attackerAbilitiesLoading,
    defenderAbilitiesLoading,
    attackerStatStages,
    defenderStatStages,
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