<script setup lang="ts">
import { onMounted } from 'vue';
import type { PokemonSearchItem } from '../api/calculator';
import CalculationScope from '../components/CalculationScope.vue';
import DamageResult from '../components/DamageResult.vue';
import MoveSelector from '../components/MoveSelector.vue';
import PokemonSelector from '../components/PokemonSelector.vue';
import PokemonSummaryCard from '../components/PokemonSummaryCard.vue';
import StatPresetSelector from '../components/StatPresetSelector.vue';
import { useDamageCalculator } from '../composables/useDamageCalculator';
import { useRecentPokemon } from '../composables/useRecentPokemon';

const calculator = useDamageCalculator();
const { items: recentPokemon, remember: rememberPokemon } = useRecentPokemon();

/** 初始化页面所需的服务端模板。 */
onMounted(() => {
  void calculator.loadPresets();
});

/**
 * 记录攻击方选择并交给 calculator 加载详情。
 *
 * @param pokemon 用户在攻击方选择器中选中的 Pokémon。
 * @returns 详情和可用招式加载完成后 resolve 的 Promise。
 */
async function selectAttacker(pokemon: PokemonSearchItem): Promise<void> {
  // 先更新页面内存，使防守方选择器无需等待详情请求即可看到最近记录。
  rememberPokemon(pokemon);
  await calculator.selectAttacker(pokemon);
}

/**
 * 记录防守方选择并交给 calculator 加载详情。
 *
 * @param pokemon 用户在防守方选择器中选中的 Pokémon。
 * @returns 防守方详情加载完成后 resolve 的 Promise。
 */
async function selectDefender(pokemon: PokemonSearchItem): Promise<void> {
  // 两侧共享同一个 store，但只更新当前被操作一侧的 calculator 选择。
  rememberPokemon(pokemon);
  await calculator.selectDefender(pokemon);
}
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div>
        <h1>Pokémon 伤害计算器</h1>
        <p>Champion · 朱紫 · Lv.{{ calculator.level.value }}</p>
      </div>
      <div class="state-pill">{{ calculator.state.value }}</div>
    </header>

    <section class="calculator-grid">
      <div class="side-column" data-testid="attacker-column">
        <PokemonSelector
          title="攻击方 Pokémon"
          :ruleset-id="calculator.rulesetId.value"
          :selected="calculator.attacker.value"
          :recent-pokemon="recentPokemon"
          @select="selectAttacker"
        />
        <PokemonSummaryCard :pokemon="calculator.attacker.value" />
        <StatPresetSelector
          v-model="calculator.attackerPreset.value"
          data-testid="attacker-config"
          title="攻击配置"
          :presets="calculator.attackerPresets.value"
        />
      </div>

      <div class="side-column" data-testid="defender-column">
        <PokemonSelector
          title="防守方 Pokémon"
          :ruleset-id="calculator.rulesetId.value"
          :selected="calculator.defender.value"
          :recent-pokemon="recentPokemon"
          @select="selectDefender"
        />
        <PokemonSummaryCard :pokemon="calculator.defender.value" />
        <StatPresetSelector
          v-model="calculator.defenderPreset.value"
          data-testid="defender-config"
          title="耐久配置"
          :presets="calculator.defenderPresets.value"
        />
      </div>
    </section>

    <section class="move-stage" data-testid="move-stage" aria-label="攻击方招式选择">
      <MoveSelector
        :pokemon-id="calculator.attacker.value?.pokemon_id ?? null"
        :ruleset-id="calculator.rulesetId.value"
        :selected="calculator.move.value"
        :disabled="!calculator.attacker.value"
        @select="calculator.move.value = $event"
        @clear-selection="calculator.move.value = null"
      />
    </section>

    <section class="action-band">
      <button
        class="primary-button"
        type="button"
        :disabled="!calculator.canCalculate.value"
        @click="calculator.submit"
      >
        {{ calculator.loading.value ? '计算中' : '开始计算' }}
      </button>
      <p v-if="calculator.error.value" class="error">{{ calculator.error.value }}</p>
      <p v-else-if="calculator.staleResult.value" class="muted">输入已变化，当前结果需要重新计算。</p>
    </section>

    <DamageResult :result="calculator.result.value" :stale="calculator.staleResult.value" />
    <CalculationScope :scope="calculator.result.value?.scope ?? null" />
  </main>
</template>

<style scoped>
.move-stage {
  width: min(800px, 100%);
  margin: 20px auto 0;
}
</style>
