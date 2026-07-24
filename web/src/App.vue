<script setup lang="ts">
import { ref } from 'vue';
import {
  DEFAULT_CONFIGURATION_SPACE_FIXTURE_JOB_ID,
} from './api/configurationSpaceJobs';
import DamageCalculatorView from './views/DamageCalculatorView.vue';
import BattleInferenceView from './views/BattleInferenceView.vue';
import BattleInferenceJobView from './views/BattleInferenceJobView.vue';

type HomeTab = 'calculator' | 'inference' | 'configuration-job';

const initialJobId = readJobId();
const activeTab = ref<HomeTab>(initialJobId === null ? 'calculator' : 'configuration-job');
const activeJobId = ref(initialJobId ?? DEFAULT_CONFIGURATION_SPACE_FIXTURE_JOB_ID);

/**
 * 从当前 URL 恢复配置空间任务 ID。
 *
 * @returns 非空 job_id；参数缺失或仅包含空白时返回 null。
 */
function readJobId(): string | null {
  const value = new URL(window.location.href).searchParams.get('job_id')?.trim();
  return value ? value : null;
}

/**
 * 把当前配置空间任务 ID 写入浏览器地址，支持刷新和离开页面后恢复。
 *
 * @param jobId 需要持久化到查询参数的稳定任务标识。
 */
function persistJobId(jobId: string): void {
  const url = new URL(window.location.href);
  url.searchParams.set('job_id', jobId);
  window.history.replaceState(window.history.state, '', url);
}

/**
 * 切换首页功能页签；首次进入任务结果页时创建有界 fixture 入口。
 *
 * @param tab 用户选择的功能页签。
 */
function selectTab(tab: HomeTab): void {
  activeTab.value = tab;
  if (tab === 'configuration-job') {
    persistJobId(activeJobId.value);
  }
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
          多回合战斗推演
        </button>
        <button
          type="button"
          :class="{ 'home-tab--active': activeTab === 'configuration-job' }"
          @click="selectTab('configuration-job')"
        >
          配置空间任务
        </button>
      </div>
    </nav>

    <KeepAlive>
      <DamageCalculatorView v-if="activeTab === 'calculator'" />
      <BattleInferenceView v-else-if="activeTab === 'inference'" />
      <BattleInferenceJobView v-else :job-id="activeJobId" />
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
