<script setup lang="ts">
import { ref } from 'vue';
import DamageCalculatorView from './views/DamageCalculatorView.vue';
import BattleInferenceView from './views/BattleInferenceView.vue';

type HomeTab = 'calculator' | 'inference';

const activeTab = ref<HomeTab>('calculator');
</script>

<template>
  <div class="product-shell">
    <nav class="home-tabs" aria-label="首页功能切换">
      <div class="home-tabs__brand">
        <span>POKEOP</span>
        <small>Battle Workbench</small>
      </div>
      <div class="home-tabs__actions">
        <button
          type="button"
          :class="{ 'home-tab--active': activeTab === 'calculator' }"
          @click="activeTab = 'calculator'"
        >
          单次伤害计算
        </button>
        <button
          type="button"
          :class="{ 'home-tab--active': activeTab === 'inference' }"
          @click="activeTab = 'inference'"
        >
          多回合战斗推演
        </button>
      </div>
    </nav>

    <KeepAlive>
      <DamageCalculatorView v-if="activeTab === 'calculator'" />
      <BattleInferenceView v-else />
    </KeepAlive>
  </div>
</template>
