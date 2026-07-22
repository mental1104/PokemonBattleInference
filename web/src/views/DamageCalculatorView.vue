<script setup lang="ts">
import { onMounted } from 'vue';
import CalculationScope from '../components/CalculationScope.vue';
import DamageResult from '../components/DamageResult.vue';
import MoveSelector from '../components/MoveSelector.vue';
import PokemonSelector from '../components/PokemonSelector.vue';
import PokemonSummaryCard from '../components/PokemonSummaryCard.vue';
import StatPresetSelector from '../components/StatPresetSelector.vue';
import { useDamageCalculator } from '../composables/useDamageCalculator';

const calculator = useDamageCalculator();

/** 初始化页面所需的服务端模板。 */
onMounted(() => {
  void calculator.loadPresets();
});
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
      <div class="side-column">
        <PokemonSelector
          title="攻击方 Pokémon"
          :ruleset-id="calculator.rulesetId.value"
          :selected="calculator.attacker.value"
          @select="calculator.selectAttacker"
        />
        <PokemonSummaryCard :pokemon="calculator.attacker.value" />
        <MoveSelector
          :moves="calculator.moves.value"
          :selected="calculator.move.value"
          :disabled="!calculator.attacker.value"
          @select="calculator.move.value = $event"
          @search="calculator.refreshMoves"
        />
        <StatPresetSelector
          v-model="calculator.attackerPreset.value"
          title="攻击配置"
          :presets="calculator.attackerPresets.value"
        />
      </div>

      <div class="side-column">
        <PokemonSelector
          title="防守方 Pokémon"
          :ruleset-id="calculator.rulesetId.value"
          :selected="calculator.defender.value"
          @select="calculator.selectDefender"
        />
        <PokemonSummaryCard :pokemon="calculator.defender.value" />
        <StatPresetSelector
          v-model="calculator.defenderPreset.value"
          title="耐久配置"
          :presets="calculator.defenderPresets.value"
        />
      </div>
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
