<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import ConfigurationSpeedGoalFeature from './components/ConfigurationSpeedGoalFeature.vue';
import './components/configurationSpeedGoals.css';
import { provideConfigurationSolver } from './composables/useConfigurationSolver';
import DamageCalculatorView from './views/DamageCalculatorView.vue';
import BattleInferenceView from './views/BattleInferenceView.vue';
import ConfigurationSolverView from './views/ConfigurationSolverView.vue';
import InferenceJobDetailView from './views/InferenceJobDetailView.vue';

type HomeTab = 'calculator' | 'inference' | 'solver';
type AppView = 'home' | 'inference-job';

const activeTab = ref<HomeTab>('calculator');
const currentView = ref<AppView>(initialView());
const activeJobId = ref<string | null>(initialJobId());
const solverFeatureReady = ref(false);

// 主页面和 Teleport 速度目标组件必须共享同一组目标与结果状态。
provideConfigurationSolver();

const showJobDetail = computed(
  () => currentView.value === 'inference-job' && activeJobId.value !== null,
);

watch(activeTab, async (tab) => {
  solverFeatureReady.value = false;
  if (tab !== 'solver') return;
  // 等主求解视图生成 .goal-columns 后再挂载 Teleport，避免首次切换找不到目标节点。
  await nextTick();
  solverFeatureReady.value = true;
});

/**
 * 切换首页主要产品能力。
 *
 * @param tab 单次伤害计算、配置反向求解或固定配置推演。
 */
function selectTab(tab: HomeTab): void {
  activeTab.value = tab;
  currentView.value = 'home';
  activeJobId.value = null;
  window.history.pushState({}, '', '/');
}

/**
 * 返回任务详情入口的初始视图。
 *
 * @returns URL 包含有效任务参数时返回 inference-job，否则返回 home。
 */
function initialView(): AppView {
  const params = new URLSearchParams(window.location.search);
  return params.get('view') === 'inference-job' && params.get('job_id') ? 'inference-job' : 'home';
}

/**
 * 返回 URL 中可恢复的任务 ID。
 *
 * @returns 当前为任务详情入口时返回 job_id，否则返回 null。
 */
function initialJobId(): string | null {
  const params = new URLSearchParams(window.location.search);
  return params.get('view') === 'inference-job' ? params.get('job_id') : null;
}

/**
 * 打开后台任务详情，并把稳定 job_id 写入 URL。
 *
 * @param jobId 后台推演任务的稳定标识。
 */
function openInferenceJob(jobId: string): void {
  currentView.value = 'inference-job';
  activeJobId.value = jobId;
  const params = new URLSearchParams({ view: 'inference-job', job_id: jobId });
  window.history.pushState({}, '', `/?${params.toString()}`);
}

/** 从任务详情返回固定配置推演页，并清理 URL 中的任务参数。 */
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
          :class="{ 'home-tab--active': activeTab === 'solver' }"
          @click="selectTab('solver')"
        >
          配置反向求解
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
    <ConfigurationSpeedGoalFeature
      v-if="!showJobDetail && activeTab === 'solver' && solverFeatureReady"
    />
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
