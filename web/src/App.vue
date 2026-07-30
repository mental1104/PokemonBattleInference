<script setup lang="ts">
import { computed, ref } from 'vue';
import DamageCalculatorView from './views/DamageCalculatorView.vue';
import BattleInferenceView from './views/BattleInferenceView.vue';
import ConfigurationSolverView from './views/ConfigurationSolverView.vue';
import InferenceJobDetailView from './views/InferenceJobDetailView.vue';

type HomeTab = 'calculator' | 'inference' | 'solver';
type AppView = 'home' | 'inference-job';

const activeTab = ref<HomeTab>('calculator');
const currentView = ref<AppView>(initialView());
const activeJobId = ref<string | null>(initialJobId());

const showJobDetail = computed(
  () => currentView.value === 'inference-job' && activeJobId.value !== null,
);

/**
 * 切换首页主要产品能力。
 *
 * @param tab 单次伤害计算、固定配置推演或配置反向求解。
 */
function selectTab(tab: HomeTab): void {
  activeTab.value = tab;
  currentView.value = 'home';
  activeJobId.value = null;
  window.history.pushState({}, '', '/');
}

/** 返回任务详情入口的初始视图。 */
function initialView(): AppView {
  const params = new URLSearchParams(window.location.search);
  return params.get('view') === 'inference-job' && params.get('job_id') ? 'inference-job' : 'home';
}

/** 返回 URL 中可恢复的任务 ID。 */
function initialJobId(): string | null {
  const params = new URLSearchParams(window.location.search);
  return params.get('view') === 'inference-job' ? params.get('job_id') : null;
}

/** 打开后台任务详情，并把稳定 job_id 写入 URL。 */
function openInferenceJob(jobId: string): void {
  currentView.value = 'inference-job';
  activeJobId.value = jobId;
  const params = new URLSearchParams({ view: 'inference-job', job_id: jobId });
  window.history.pushState({}, '', `/?${params.toString()}`);
}

/** 从任务详情返回固定配置推演页。 */
function backToInference(): void {
  currentView.value = 'home';
  activeJobId.value = null;
  activeTab.value = 'inference';
  window.history.pushState({}, '', '/');
}
</script>

<template>
  <div class="product-shell">
    <nav class="home-tabs" aria-label="首页功能切换">
      <div class="home-tabs__brand">
        <span>POKEOP</span>
        <small>Battle Workbench</small>
      </div>
      <div v-if="!showJobDetail" class="home-tabs__actions">
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
        <button
          type="button"
          :class="{ 'home-tab--active': activeTab === 'solver' }"
          @click="selectTab('solver')"
        >
          配置反向求解
        </button>
      </div>
    </nav>

    <InferenceJobDetailView
      v-if="showJobDetail && activeJobId"
      :job-id="activeJobId"
      @back="backToInference"
    />
    <KeepAlive v-else>
      <DamageCalculatorView v-if="activeTab === 'calculator'" />
      <BattleInferenceView v-else-if="activeTab === 'inference'" @open-job="openInferenceJob" />
      <ConfigurationSolverView v-else />
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
