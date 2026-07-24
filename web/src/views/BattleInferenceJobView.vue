<script setup lang="ts">
import { computed, watch } from 'vue';
import {
  createBattleInferenceJobClient,
  type BattleInferenceJobClient,
} from '../api/configurationSpaceJobs';
import { useConfigurationSpaceJob } from '../composables/useConfigurationSpaceJob';
import type {
  BattleInferenceJobStatus,
  ConfigurationRunStatus,
  TopConfigurationSort,
} from '../types/configurationSpaceJob';
import BattleGraphExplorer from '../components/inference/BattleGraphExplorer.vue';

/** 配置空间任务结果页的输入。 */
interface Props {
  /** 从 URL 查询参数恢复的后台任务 ID。 */
  jobId: string;
  /** 测试或宿主页面注入的客户端；未提供时按 job_id 选择 fixture/HTTP adapter。 */
  client?: BattleInferenceJobClient;
}

const props = defineProps<Props>();

const {
  snapshot,
  topConfigurations,
  configurationIssues,
  topSort,
  issueStatus,
  issueErrorCode,
  loading,
  topLoading,
  issueLoading,
  cancelling,
  actionMessage,
  errorMessage,
  issueTotal,
  activeGraphHandle,
  activeGraphConfigurationId,
  canLoadMoreIssues,
  start,
  selectTopSort,
  applyIssueFilters,
  loadMoreIssues,
  cancelJob,
  retryConfiguration,
  exploreConfiguration,
  closeGraphExplorer,
} = useConfigurationSpaceJob();

const completedPercent = computed(() => {
  if (snapshot.value === null || snapshot.value.counts.total === 0) {
    return 0;
  }
  return (snapshot.value.counts.completed / snapshot.value.counts.total) * 100;
});

const stateNodePercent = computed(() => resourcePercent(
  snapshot.value?.resources.state_nodes.used ?? 0,
  snapshot.value?.resources.state_nodes.limit ?? 0,
));
const edgePercent = computed(() => resourcePercent(
  snapshot.value?.resources.edges.used ?? 0,
  snapshot.value?.resources.edges.limit ?? 0,
));

const topSortLabels: Record<TopConfigurationSort, string> = {
  'overall-win-rate': '综合胜率',
  'worst-matchup': '最差对局表现',
  'expected-winning-turns': '期望获胜回合',
};

const statusLabels: Record<BattleInferenceJobStatus, string> = {
  queued: '排队中',
  running: '运行中',
  completed: '完整完成',
  partial: '部分覆盖',
  cancelled: '已取消',
  failed: '任务失败',
};

const configurationStatusLabels: Record<ConfigurationRunStatus, string> = {
  pending: '未开始',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  truncated: '已截断',
  cancelled: '已取消',
};

/**
 * 计算资源或数量进度条的百分比，并限制在 0～100 之间。
 *
 * @param used 已使用数量。
 * @param limit 总数量或预算上限。
 * @returns 可安全用于 CSS width 的百分比。
 */
function resourcePercent(used: number, limit: number): number {
  if (limit <= 0) {
    return 0;
  }
  return Math.min(100, Math.max(0, (used / limit) * 100));
}

/**
 * 格式化 0～100 的百分比数值。
 *
 * @param value 后端返回的百分比；null 表示尚不可用。
 * @returns 两位小数百分比或明确的不可用文本。
 */
function formatPercent(value: number | null): string {
  return value === null ? '不可用' : `${value.toFixed(2)}%`;
}

/**
 * 使用中文分组格式展示配置数、节点数和边数。
 *
 * @param value 非负计数。
 * @returns 带千位分隔符的文本。
 */
function formatCount(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value);
}

/**
 * 把 ISO 时间转换为可比较的本地日期时间。
 *
 * @param value ISO 时间；null 表示该生命周期阶段尚未发生。
 * @returns 本地日期时间或短横线。
 */
function formatDateTime(value: string | null): string {
  if (value === null) {
    return '—';
  }
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value));
}

/**
 * 返回任务状态对应的语义 class。
 *
 * @param status 任务生命周期状态。
 * @returns 只用于视觉区分的 class 名称。
 */
function jobStatusClass(status: BattleInferenceJobStatus): string {
  return `job-status--${status}`;
}

/**
 * 返回单配置状态对应的语义 class。
 *
 * @param status 单配置执行状态。
 * @returns 只用于视觉区分的 class 名称。
 */
function configurationStatusClass(status: ConfigurationRunStatus): string {
  return `configuration-status--${status}`;
}

/**
 * 判断某个 Top-K 排序是否可用。
 *
 * @param sort 稳定排序标识。
 * @returns 后端快照声明可用时返回 true。
 */
function sortAvailable(sort: TopConfigurationSort): boolean {
  return snapshot.value?.top_sort_capabilities.find((item) => item.sort === sort)?.available ?? false;
}

/**
 * 返回不可用排序的后端原因，供 title 和可访问说明使用。
 *
 * @param sort 稳定排序标识。
 * @returns 禁用原因；可用或快照缺失时为空字符串。
 */
function sortDisabledReason(sort: TopConfigurationSort): string {
  return snapshot.value?.top_sort_capabilities.find((item) => item.sort === sort)?.disabled_reason ?? '';
}

watch(
  () => [props.jobId, props.client] as const,
  ([jobId, injectedClient]) => {
    const client = injectedClient ?? createBattleInferenceJobClient(jobId);
    void start(jobId, client);
  },
  { immediate: true },
);
</script>

<template>
  <main class="configuration-job-shell">
    <header class="configuration-job-hero">
      <div>
        <p class="eyebrow">CONFIGURATION SPACE JOB</p>
        <h1>配置空间推演结果</h1>
        <p>
          概率只描述已覆盖配置；覆盖率、未完成权重、失败与截断始终独立展示。
        </p>
      </div>
      <div class="configuration-job-identity">
        <span>JOB ID</span>
        <code data-test="job-id">{{ jobId }}</code>
      </div>
    </header>

    <p v-if="errorMessage" class="job-feedback job-feedback--error" role="alert">
      {{ errorMessage }}
    </p>
    <p v-if="actionMessage" class="job-feedback job-feedback--action" role="status">
      {{ actionMessage }}
    </p>

    <section v-if="loading && !snapshot" class="job-loading" aria-live="polite">
      正在恢复任务状态与当前结果窗口…
    </section>

    <template v-if="snapshot">
      <section class="job-overview-card">
        <div class="job-overview-card__heading">
          <div>
            <span class="job-status" :class="jobStatusClass(snapshot.status)" data-test="job-status">
              {{ statusLabels[snapshot.status] }}
            </span>
            <h2>任务生命周期</h2>
          </div>
          <button
            v-if="snapshot.can_cancel"
            type="button"
            class="job-cancel-button"
            :disabled="cancelling"
            data-test="cancel-job"
            @click="cancelJob"
          >
            {{ cancelling ? '正在取消…' : '取消任务' }}
          </button>
        </div>
        <dl class="job-time-grid">
          <div><dt>创建</dt><dd>{{ formatDateTime(snapshot.created_at) }}</dd></div>
          <div><dt>开始</dt><dd>{{ formatDateTime(snapshot.started_at) }}</dd></div>
          <div><dt>更新</dt><dd>{{ formatDateTime(snapshot.updated_at) }}</dd></div>
          <div><dt>完成</dt><dd>{{ formatDateTime(snapshot.completed_at) }}</dd></div>
        </dl>
        <div v-if="snapshot.stop_reason_code" class="stop-reason" data-test="stop-reason">
          <strong>{{ snapshot.stop_reason_code }}</strong>
          <span>{{ snapshot.stop_reason_message }}</span>
        </div>
      </section>

      <section class="job-section">
        <div class="job-section__heading">
          <div>
            <p class="eyebrow">PROGRESS & BUDGET</p>
            <h2>数量进度与资源预算</h2>
          </div>
          <strong>{{ formatCount(snapshot.counts.completed) }} / {{ formatCount(snapshot.counts.total) }}</strong>
        </div>

        <div class="job-progress-track" role="progressbar" aria-label="配置对完成进度" :aria-valuenow="completedPercent" aria-valuemin="0" aria-valuemax="100">
          <i :style="{ width: `${completedPercent}%` }" />
        </div>

        <div class="count-metric-grid">
          <article><span>成功</span><strong>{{ formatCount(snapshot.counts.succeeded) }}</strong></article>
          <article class="metric--failed"><span>失败</span><strong>{{ formatCount(snapshot.counts.failed) }}</strong></article>
          <article class="metric--truncated"><span>截断</span><strong>{{ formatCount(snapshot.counts.truncated) }}</strong></article>
          <article class="metric--running"><span>运行中</span><strong>{{ formatCount(snapshot.counts.running) }}</strong></article>
          <article><span>未开始</span><strong>{{ formatCount(snapshot.counts.pending) }}</strong></article>
          <article class="metric--cancelled"><span>已取消</span><strong>{{ formatCount(snapshot.counts.cancelled) }}</strong></article>
        </div>

        <div class="resource-grid">
          <article>
            <div><span>累计状态节点</span><strong>{{ formatCount(snapshot.resources.state_nodes.used) }} / {{ formatCount(snapshot.resources.state_nodes.limit) }}</strong></div>
            <div class="resource-track"><i :style="{ width: `${stateNodePercent}%` }" /></div>
          </article>
          <article>
            <div><span>累计概率边</span><strong>{{ formatCount(snapshot.resources.edges.used) }} / {{ formatCount(snapshot.resources.edges.limit) }}</strong></div>
            <div class="resource-track"><i :style="{ width: `${edgePercent}%` }" /></div>
          </article>
        </div>
      </section>

      <section class="job-section aggregate-section" data-test="aggregate-summary">
        <div class="job-section__heading">
          <div>
            <p class="eyebrow">COVERED CONFIGURATIONS</p>
            <h2>已覆盖配置中的胜负平概率</h2>
          </div>
          <small>不是无条件完整胜率</small>
        </div>
        <div class="aggregate-grid">
          <article class="aggregate-card aggregate-card--win"><span>胜</span><strong>{{ formatPercent(snapshot.aggregate.covered_probability.win_percent) }}</strong></article>
          <article class="aggregate-card aggregate-card--loss"><span>负</span><strong>{{ formatPercent(snapshot.aggregate.covered_probability.loss_percent) }}</strong></article>
          <article class="aggregate-card"><span>平</span><strong>{{ formatPercent(snapshot.aggregate.covered_probability.draw_percent) }}</strong></article>
          <article class="aggregate-card aggregate-card--coverage"><span>配置覆盖率</span><strong>{{ formatPercent(snapshot.aggregate.configuration_coverage_percent) }}</strong></article>
          <article class="aggregate-card"><span>已覆盖权重</span><strong>{{ formatPercent(snapshot.aggregate.covered_weight_percent) }}</strong></article>
          <article class="aggregate-card aggregate-card--unfinished"><span>未完成权重</span><strong>{{ formatPercent(snapshot.aggregate.unfinished_weight_percent) }}</strong></article>
        </div>
      </section>

      <section class="job-metadata-grid">
        <article class="job-section metadata-card">
          <p class="eyebrow">CALCULATION CONTRACT</p>
          <h2>计算合同</h2>
          <dl>
            <div><dt>规则集</dt><dd>{{ snapshot.metadata.ruleset_id }}</dd></div>
            <div><dt>Version Group</dt><dd>{{ snapshot.metadata.version_group_id }}</dd></div>
            <div><dt>计算版本</dt><dd>{{ snapshot.metadata.calculation_revision }}</dd></div>
            <div><dt>配置权重</dt><dd>{{ snapshot.metadata.configuration_weight_assumption }}</dd></div>
            <div><dt>攻击方策略</dt><dd>{{ snapshot.metadata.attacker_action_policy }}</dd></div>
            <div><dt>防守方策略</dt><dd>{{ snapshot.metadata.defender_action_policy }}</dd></div>
          </dl>
        </article>
        <article class="job-section metadata-card">
          <p class="eyebrow">MECHANISM COVERAGE</p>
          <h2>机制覆盖</h2>
          <div class="mechanism-columns">
            <div>
              <strong>已纳入</strong>
              <span v-for="item in snapshot.metadata.included_mechanisms" :key="item">{{ item }}</span>
            </div>
            <div>
              <strong>未纳入</strong>
              <span v-for="item in snapshot.metadata.excluded_mechanisms" :key="item">{{ item }}</span>
            </div>
          </div>
        </article>
      </section>

      <section class="job-section top-k-section">
        <div class="job-section__heading top-k-heading">
          <div>
            <p class="eyebrow">TOP-K CONFIGURATIONS</p>
            <h2>配置表现排序</h2>
          </div>
          <div class="sort-controls" aria-label="Top-K 排序">
            <button
              v-for="capability in snapshot.top_sort_capabilities"
              :key="capability.sort"
              type="button"
              :class="{ 'sort-control--active': topSort === capability.sort }"
              :disabled="!sortAvailable(capability.sort) || topLoading"
              :title="sortDisabledReason(capability.sort)"
              :data-test="`sort-${capability.sort}`"
              @click="selectTopSort(capability.sort)"
            >
              {{ topSortLabels[capability.sort] }}
            </button>
          </div>
        </div>

        <p v-if="topLoading" class="panel-loading">正在更新 Top-K 窗口…</p>
        <div class="top-configuration-list" data-test="top-configuration-list">
          <article
            v-for="item in topConfigurations"
            :key="item.configuration_id"
            class="top-configuration-card"
            data-test="top-configuration-item"
          >
            <div class="top-configuration-card__rank">#{{ item.rank }}</div>
            <div class="top-configuration-card__body">
              <div class="configuration-card-heading">
                <code>{{ item.configuration_id }}</code>
                <span class="configuration-status" :class="configurationStatusClass(item.status)">
                  {{ configurationStatusLabels[item.status] }}
                </span>
              </div>
              <div class="moveset-grid">
                <div>
                  <strong>{{ item.attacker.pokemon_name }}</strong>
                  <span v-for="move in item.attacker.moves" :key="move.move_id">{{ move.name }}</span>
                </div>
                <div>
                  <strong>{{ item.defender.pokemon_name }}</strong>
                  <span v-for="move in item.defender.moves" :key="move.move_id">{{ move.name }}</span>
                </div>
              </div>
              <div class="configuration-result-grid">
                <span>胜 <strong>{{ formatPercent(item.win_percent) }}</strong></span>
                <span>负 <strong>{{ formatPercent(item.loss_percent) }}</strong></span>
                <span>平 <strong>{{ formatPercent(item.draw_percent) }}</strong></span>
                <span>期望回合 <strong>{{ item.expected_turns?.toFixed(2) ?? '不可用' }}</strong></span>
              </div>
              <div class="configuration-card-footer">
                <span v-if="item.graph">
                  {{ formatCount(item.graph.unique_state_count) }} 节点 ·
                  {{ formatCount(item.graph.edge_count) }} 边 ·
                  最大 {{ item.graph.max_turn_number }} 回合
                </span>
                <span v-else>图规模尚不可用</span>
                <button
                  type="button"
                  :disabled="item.status !== 'completed'"
                  :data-configuration-id="item.configuration_id"
                  data-test="explore-configuration"
                  @click="exploreConfiguration(item.configuration_id)"
                >
                  按需探索完整图
                </button>
              </div>
            </div>
          </article>
        </div>
      </section>

      <section class="job-section issues-section">
        <div class="job-section__heading">
          <div>
            <p class="eyebrow">FAILURES & TRUNCATIONS</p>
            <h2>具体失败与截断用例</h2>
          </div>
          <strong>{{ formatCount(issueTotal) }} 条</strong>
        </div>
        <div class="issue-filters">
          <label>
            <span>状态</span>
            <select v-model="issueStatus" data-test="issue-status-filter" @change="applyIssueFilters">
              <option value="all">全部</option>
              <option value="failed">失败</option>
              <option value="truncated">截断</option>
            </select>
          </label>
          <label>
            <span>错误代码</span>
            <select v-model="issueErrorCode" data-test="issue-code-filter" @change="applyIssueFilters">
              <option value="">全部错误代码</option>
              <option v-for="code in snapshot.issue_error_codes" :key="code" :value="code">{{ code }}</option>
            </select>
          </label>
        </div>

        <p v-if="issueLoading && configurationIssues.length === 0" class="panel-loading">
          正在读取问题用例窗口…
        </p>
        <div class="issue-list" data-test="configuration-issue-list">
          <article
            v-for="item in configurationIssues"
            :key="item.configuration_id"
            class="issue-card"
            :class="`issue-card--${item.status}`"
            data-test="configuration-issue-item"
          >
            <div class="issue-card__heading">
              <div>
                <span>{{ item.status === 'failed' ? '失败' : '截断' }}</span>
                <code>{{ item.error_code }}</code>
              </div>
              <code>{{ item.configuration_id }}</code>
            </div>
            <div class="moveset-grid moveset-grid--compact">
              <div>
                <strong>{{ item.attacker.pokemon_name }}</strong>
                <span v-for="move in item.attacker.moves" :key="move.move_id">{{ move.name }}</span>
              </div>
              <div>
                <strong>{{ item.defender.pokemon_name }}</strong>
                <span v-for="move in item.defender.moves" :key="move.move_id">{{ move.name }}</span>
              </div>
            </div>
            <p>{{ item.reason }}</p>
            <small>{{ item.diagnostic_summary }}</small>
            <div class="issue-card__footer">
              <span>{{ formatCount(item.unique_state_count) }} 节点 · {{ formatCount(item.edge_count) }} 边 · 最大 {{ item.max_turn_number }} 回合</span>
              <button type="button" data-test="retry-configuration" @click="retryConfiguration(item.configuration_id)">
                重试入口
              </button>
            </div>
          </article>
        </div>
        <button
          v-if="canLoadMoreIssues"
          type="button"
          class="load-more-button"
          :disabled="issueLoading"
          data-test="load-more-issues"
          @click="loadMoreIssues"
        >
          {{ issueLoading ? '正在加载…' : '加载更多' }}
        </button>
      </section>

      <section v-if="activeGraphHandle" class="job-section on-demand-graph" data-test="on-demand-graph">
        <div class="job-section__heading">
          <div>
            <p class="eyebrow">ON-DEMAND GRAPH</p>
            <h2>配置 {{ activeGraphConfigurationId }} 的完整图</h2>
          </div>
          <button type="button" class="close-graph-button" @click="closeGraphExplorer">关闭</button>
        </div>
        <p>
          当前句柄由单配置按需接口创建；Top-K 批量摘要未携带 graph artifact。
        </p>
        <BattleGraphExplorer
          :key="activeGraphHandle.graph_id"
          :handle="activeGraphHandle"
          @rerun="activeGraphConfigurationId && exploreConfiguration(activeGraphConfigurationId)"
        />
      </section>
    </template>
  </main>
</template>

<style src="../configuration-job.css"></style>
