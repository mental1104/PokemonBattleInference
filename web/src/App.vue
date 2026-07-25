<script setup lang="ts">
import { ref } from 'vue';
import DamageCalculatorView from './views/DamageCalculatorView.vue';
import BattleInferenceView from './views/BattleInferenceView.vue';

type HomeTab = 'calculator' | 'inference';

const activeTab = ref<HomeTab>('calculator');

/**
 * 切换首页主要产品能力。
 *
 * @param tab 单次伤害计算或固定配置多回合精确推演。
 */
function selectTab(tab: HomeTab): void {
  activeTab.value = tab;
}
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
          @click="selectTab('calculator')"
        >
          单次伤害计算
        </button>
        <button
          type="button"
          :class="{ 'home-tab--active': activeTab === 'inference' }"
          @click="selectTab('inference')"
        >
          固定配置精确推演
        </button>
      </div>
    </nav>

    <KeepAlive>
      <DamageCalculatorView v-if="activeTab === 'calculator'" />
      <BattleInferenceView v-else />
    </KeepAlive>
  </div>
</template>

<style scoped>
@media (max-width: 760px) {
  .home-tabs {
    align-items: stretch;
    flex-direction: column;
  }

  .home-tabs__actions {
    overflow-x: auto;
    width: 100%;
  }

  .home-tabs__actions button {
    flex: 0 0 auto;
  }
}
</style>
