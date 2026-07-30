<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import {
  cancelInferenceJob,
  createJobCaseGraph,
  getInferenceJob,
  listSucceededJobCases,
} from '../api/fixedBattle';
import type { InferenceJobSummary } from '../types/fixedBattle';
import type {
  InferenceJobCaseSummary,
  InferenceJobExplanationBucket,
  InferenceJobExplanationProbability,
} from '../types/fixedBattle';
import type { BattleJourneyResult } from '../api/inference';
import BattleGraphTreeScreen from '../components/inference/BattleGraphTreeScreen.vue';
import { createBattleReportPresenterContext } from '../presenters/battleEventPresenter';

interface Props {
  /** 从 URL 查询参数恢复的后台任务 ID。 */
  jobId: string;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  /** 返回固定配置推演首页。 */
  back: [];
}>();

const job = ref<InferenceJobSummary | null>(null);
const loading = ref(false);
const errorMessage = ref<string | null>(null);
const actionMessage = ref<string | null>(null);
const graphLoading = ref(false);
const graphJourney = ref<BattleJourneyResult | null>(null);
const resultCase = ref<InferenceJobCaseSummary | null>(null);
const treeScreenOpen = ref(false);
let pollTimer: ReturnType<typeof setInterval> | null = null;
let requestVersion = 0;

const canPoll = computed(() =>
  job.value !== null && ['pending', 'preparing', 'running', 'cancel_requested'].includes(job.value.status),
);

const canOpenGraph = computed(() =>
  job.value?.status === 'succeeded' && job.value.progress.counts.succeeded > 0,
);

const reportContext = computed(() =>
  graphJourney.value === null
    ? null
    : createBattleReportPresenterContext(graphJourney.value.summary),
);

/** 初次进入和 job_id 变化时恢复任务详情。 */
onMounted(() => {
  void refresh();
  startPolling();
});

/** 组件卸载时释放轮询 timer。 */
onUnmounted(() => {
  stopPolling();
});

watch(
  () => props.jobId,
  () => {
      job.value = null;
      resultCase.value = null;
      void refresh();
    },
);

/** 读取后台任务最新快照，并避免旧响应覆盖新 job_id。 */
async function refresh(): Promise<void> {
  const version = requestVersion + 1;
  requestVersion = version;
  loading.value = job.value === null;
  try {
    const next = await getInferenceJob(props.jobId);
    if (version === requestVersion) {
      job.value = next;
      errorMessage.value = null;
      if (next.status === 'succeeded') {
        await loadResultCase(next.job_id, version);
      } else if (version === requestVersion) {
        resultCase.value = null;
      }
    }
  } catch (caught) {
    if (version === requestVersion) {
      errorMessage.value = caught instanceof Error ? caught.message : '任务详情加载失败';
    }
  } finally {
    if (version === requestVersion) {
      loading.value = false;
    }
  }
}

/**
 * 读取固定任务唯一成功 case 的持久化概率摘要。
 *
 * Args:
 *   jobId: 当前详情页的后台任务 ID。
 *   version: 当前请求世代；旧 job_id 的响应不得覆盖新页面。
 */
async function loadResultCase(jobId: string, version: number): Promise<void> {
  const cases = await listSucceededJobCases(jobId);
  if (version === requestVersion) {
    resultCase.value = cases.items[0] ?? null;
  }
}

/** 为运行中任务建立低频轮询。 */
function startPolling(): void {
  if (pollTimer !== null) return;
  pollTimer = setInterval(() => {
    if (document.visibilityState === 'visible' && canPoll.value) {
      void refresh();
    }
  }, 2500);
}

/** 停止详情页轮询。 */
function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

/** 请求取消当前任务并刷新最新状态。 */
async function cancelJob(): Promise<void> {
  if (job.value === null || !job.value.can_cancel) return;
  actionMessage.value = null;
  errorMessage.value = null;
  try {
    job.value = await cancelInferenceJob(job.value.job_id);
    actionMessage.value = '已请求取消任务。';
  } catch (caught) {
    errorMessage.value = caught instanceof Error ? caught.message : '取消任务失败';
  }
}

/** 为当前已完成固定任务生成完整图并打开树状图/战报大屏。 */
async function openGraphAndReport(): Promise<void> {
  if (job.value === null || !canOpenGraph.value) return;
  graphLoading.value = true;
  actionMessage.value = null;
  errorMessage.value = null;
  try {
    const cases = await listSucceededJobCases(job.value.job_id);
    const configuration = cases.items[0];
    if (configuration === undefined) {
      throw new Error('当前任务没有可打开的成功配置。');
    }
    graphJourney.value = await createJobCaseGraph(
      job.value.job_id,
      configuration.configuration_id,
    );
    treeScreenOpen.value = true;
  } catch (caught) {
    errorMessage.value = caught instanceof Error ? caught.message : '完整图创建失败';
  } finally {
    graphLoading.value = false;
  }
}

/** 格式化阶段标签。 */
function phaseLabel(phase: string): string {
  const labels: Record<string, string> = {
    queued: '已提交',
    preparing_battle: '准备配置',
    running: '运行中',
    building_graph: '构建状态图',
    expanding_actions: '展开动作组合',
    graph_built: '状态图完成',
    solving_probabilities: '求解概率',
    cancel_requested: '取消中',
    completed: '完成',
    cancelled: '已取消',
    failed: '失败',
  };
  return labels[phase] ?? phase;
}

/** 格式化状态标签。 */
function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '等待执行',
    preparing: '准备中',
    running: '运行中',
    cancel_requested: '取消中',
    succeeded: '已完成',
    completed_with_failures: '部分完成',
    cancelled: '已取消',
    failed: '失败',
  };
  return labels[status] ?? status;
}

/** 使用中文分组格式展示计数。 */
function formatCount(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value);
}

/** 返回当前任务总体进度条百分比。 */
function jobProgressPercent(current: InferenceJobSummary): number {
  if (current.progress.counts.total <= 0) return 0;
  const completedRatio =
    current.progress.counts.completed / current.progress.counts.total;
  const runningRatio =
    current.progress.running_case === null
      ? 0
      : current.progress.running_case.percent / 100 / current.progress.counts.total;
  return Math.min(100, Math.max(0, (completedRatio + runningRatio) * 100));
}

/**
 * 把精确概率转换为百分比展示。
 *
 * @param probability 后端持久化的分数概率；null 表示任务未成功。
 * @returns 两位小数百分比或不可用文本。
 */
function probabilityLabel(
  probability: { decimal: number } | null | undefined,
): string {
  return probability == null ? '—' : `${(probability.decimal * 100).toFixed(2)}%`;
}

/**
 * 把精确概率转换为分数展示。
 *
 * @param probability 后端持久化的分数概率；null 表示任务未成功。
 * @returns numerator / denominator 文本或短横线。
 */
function probabilityFraction(
  probability: { numerator: string; denominator: string } | null | undefined,
): string {
  return probability == null ? '—' : `${probability.numerator} / ${probability.denominator}`;
}

/**
 * 把归因概率片段转换为百分比展示。
 *
 * @param probability 后端归因 JSON 中的精确概率片段。
 * @returns 两位小数百分比。
 */
function explanationPercent(probability: InferenceJobExplanationProbability): string {
  return `${(probability.decimal * 100).toFixed(2)}%`;
}

/**
 * 返回 root 行动簇标题。
 *
 * @param bucket 后端按行动对聚合后的胜率贡献桶。
 * @returns 当前首版以 move ID 展示双方行动；缺失时展示未解析。
 */
function explanationBucketTitle(bucket: InferenceJobExplanationBucket): string {
  const attacker = bucket.attacker_move_id === null ? '未解析' : `#${bucket.attacker_move_id}`;
  const defender = bucket.defender_move_id === null ? '未解析' : `#${bucket.defender_move_id}`;
  return `己方 ${attacker} × 对方 ${defender}`;
}

/**
 * 计算一个行动簇对最终己方胜率的贡献占比。
 *
 * @param bucket 后端按行动对聚合后的胜率贡献桶。
 * @returns 0 到 100 的 CSS 宽度百分比。
 */
function attackerContributionWidth(bucket: InferenceJobExplanationBucket): number {
  const total = resultCase.value?.attacker_win_probability?.decimal ?? 0;
  if (total <= 0) return 0;
  return Math.min(100, Math.max(0, (bucket.attacker_win_contribution.decimal / total) * 100));
}

/** 将 ISO 时间显示为本地日期时间。 */
function formatDateTime(value: string | null): string {
  if (value === null) return '—';
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
</script>

<template>
  <main class="app-shell job-detail-view">
    <header class="job-detail-hero">
      <div>
        <p class="battle-configuration-eyebrow">INFERENCE JOB</p>
        <h1>推演任务详情</h1>
        <code>{{ jobId }}</code>
      </div>
      <div class="job-detail-actions">
        <button type="button" class="secondary-button" @click="emit('back')">返回</button>
        <button type="button" class="secondary-button" @click="refresh">刷新</button>
        <button
          v-if="job?.can_cancel"
          type="button"
          class="primary-button"
          @click="cancelJob"
        >
          取消任务
        </button>
        <button
          v-if="canOpenGraph"
          type="button"
          class="primary-button"
          :disabled="graphLoading"
          @click="openGraphAndReport"
        >
          {{ graphLoading ? '正在生成图' : '打开树状图和战报' }}
        </button>
      </div>
    </header>

    <p v-if="loading" class="job-detail-feedback">正在加载任务详情…</p>
    <p v-if="errorMessage" class="error job-detail-feedback" role="alert">{{ errorMessage }}</p>
    <p v-if="actionMessage" class="job-detail-feedback job-detail-feedback--ok" role="status">{{ actionMessage }}</p>

    <template v-if="job">
      <section class="job-detail-card">
        <div class="job-detail-status">
          <span>{{ statusLabel(job.status) }}</span>
          <strong>{{ phaseLabel(job.phase) }}</strong>
        </div>
        <dl class="job-detail-grid">
          <div><dt>创建时间</dt><dd>{{ formatDateTime(job.created_at) }}</dd></div>
          <div><dt>开始时间</dt><dd>{{ formatDateTime(job.started_at) }}</dd></div>
          <div><dt>更新时间</dt><dd>{{ formatDateTime(job.updated_at) }}</dd></div>
          <div><dt>完成时间</dt><dd>{{ formatDateTime(job.finished_at) }}</dd></div>
          <div><dt>取消请求</dt><dd>{{ formatDateTime(job.cancel_requested_at) }}</dd></div>
          <div><dt>运行时长</dt><dd>{{ job.progress.elapsed_seconds?.toFixed(1) ?? '—' }} 秒</dd></div>
        </dl>
      </section>

      <section class="job-detail-card">
        <p class="battle-configuration-eyebrow">PROGRESS</p>
        <h2>可靠进度指标</h2>
        <div
          v-if="job.progress.running_case"
          class="job-detail-progress"
          :title="[
            `节点：${formatCount(job.progress.running_case.observed_nodes)} / ${formatCount(job.progress.running_case.node_limit)}`,
            `边：${formatCount(job.progress.running_case.observed_edges)} / ${formatCount(job.progress.running_case.edge_limit)}`,
            `已展开节点：${formatCount(job.progress.running_case.expanded_nodes)}`,
            `待展开队列：${formatCount(job.progress.running_case.frontier_nodes)}`,
            `动作组合：${formatCount(job.progress.running_case.action_pairs_completed)} / ${formatCount(job.progress.running_case.action_pairs_total)}`,
          ].join('\n')"
        >
          <div class="job-detail-progress__meta">
            <span>{{ phaseLabel(job.progress.running_case.phase) }}</span>
            <strong>{{ jobProgressPercent(job).toFixed(1) }}%</strong>
          </div>
          <div class="job-detail-progress__track">
            <div
              class="job-detail-progress__bar"
              :style="{ width: `${jobProgressPercent(job)}%` }"
            />
          </div>
        </div>
        <dl class="job-detail-grid">
          <div><dt>配置完成</dt><dd>{{ job.progress.counts.completed }} / {{ job.progress.counts.total }}</dd></div>
          <div><dt>运行中</dt><dd>{{ job.progress.counts.running }}</dd></div>
          <div><dt>等待</dt><dd>{{ job.progress.counts.pending }}</dd></div>
          <div><dt>成功</dt><dd>{{ job.progress.counts.succeeded }}</dd></div>
          <div><dt>失败</dt><dd>{{ job.progress.counts.failed }}</dd></div>
          <div><dt>取消</dt><dd>{{ job.progress.counts.cancelled }}</dd></div>
          <div><dt>节点预算使用</dt><dd>{{ formatCount(job.progress.state_nodes.used) }} / {{ formatCount(job.progress.state_nodes.limit) }}</dd></div>
          <div><dt>边预算使用</dt><dd>{{ formatCount(job.progress.state_edges.used) }} / {{ formatCount(job.progress.state_edges.limit) }}</dd></div>
        </dl>
      </section>

      <section v-if="resultCase" class="job-detail-card">
        <div class="job-result-heading">
          <div>
            <p class="battle-configuration-eyebrow">EXACT RESULT</p>
            <h2>所有可能性的概率总和</h2>
          </div>
          <small>树状图只是按需打开某条路径；这里是 worker 已完成的整体精确解。</small>
        </div>
        <div class="job-result-grid">
          <article>
            <span>己方胜率</span>
            <strong>{{ probabilityLabel(resultCase.attacker_win_probability) }}</strong>
            <small>{{ probabilityFraction(resultCase.attacker_win_probability) }}</small>
          </article>
          <article>
            <span>对方胜率</span>
            <strong>{{ probabilityLabel(resultCase.defender_win_probability) }}</strong>
            <small>{{ probabilityFraction(resultCase.defender_win_probability) }}</small>
          </article>
          <article>
            <span>平局</span>
            <strong>{{ probabilityLabel(resultCase.draw_probability) }}</strong>
            <small>{{ probabilityFraction(resultCase.draw_probability) }}</small>
          </article>
          <article>
            <span>期望回合</span>
            <strong>{{ resultCase.expected_turns ?? '—' }}</strong>
            <small>{{ resultCase.expected_turns_kind ?? 'unavailable' }}</small>
          </article>
        </div>
        <dl class="job-detail-grid">
          <div><dt>己方技能 ID</dt><dd>{{ resultCase.attacker_move_ids.join(' / ') }}</dd></div>
          <div><dt>对方技能 ID</dt><dd>{{ resultCase.defender_move_ids.join(' / ') }}</dd></div>
          <div><dt>结果图规模</dt><dd>{{ formatCount(resultCase.node_count) }} nodes · {{ formatCount(resultCase.edge_count) }} edges</dd></div>
        </dl>
      </section>

      <section v-if="resultCase?.explanation" class="job-detail-card">
        <div class="job-result-heading">
          <div>
            <p class="battle-configuration-eyebrow">WHY THIS RESULT</p>
            <h2>胜率归因</h2>
          </div>
          <small>
            按 root 行动对聚合全部概率质量；每个桶仍覆盖其内部所有随机路径。
          </small>
        </div>
        <div class="job-explanation-summary">
          <article>
            <span>覆盖概率</span>
            <strong>{{ explanationPercent(resultCase.explanation.coverage) }}</strong>
          </article>
          <article>
            <span>归因口径</span>
            <strong>{{ resultCase.explanation.basis }}</strong>
          </article>
          <article>
            <span>省略小桶</span>
            <strong>{{ resultCase.explanation.omitted_bucket_count }}</strong>
          </article>
        </div>
        <div class="job-explanation-list">
          <article
            v-for="bucket in resultCase.explanation.buckets"
            :key="`${bucket.attacker_move_id ?? 'x'}:${bucket.defender_move_id ?? 'x'}:${bucket.representative_target_node_id ?? 'none'}`"
            class="job-explanation-bucket"
          >
            <header>
              <div>
                <strong>{{ explanationBucketTitle(bucket) }}</strong>
                <small>
                  覆盖 {{ explanationPercent(bucket.probability) }} ·
                  条件己方胜 {{ explanationPercent(bucket.conditional_attacker_win) }} ·
                  {{ bucket.path_count }} 条内部事件路径
                </small>
              </div>
              <span>
                贡献 {{ explanationPercent(bucket.attacker_win_contribution) }}
              </span>
            </header>
            <div class="job-explanation-meter">
              <div :style="{ width: `${attackerContributionWidth(bucket)}%` }" />
            </div>
            <dl>
              <div>
                <dt>对方胜贡献</dt>
                <dd>{{ explanationPercent(bucket.defender_win_contribution) }}</dd>
              </div>
              <div>
                <dt>平局贡献</dt>
                <dd>{{ explanationPercent(bucket.draw_contribution) }}</dd>
              </div>
              <div>
                <dt>代表目标节点</dt>
                <dd>{{ bucket.representative_target_node_id ?? '—' }}</dd>
              </div>
            </dl>
          </article>
        </div>
      </section>

      <section v-else-if="resultCase" class="job-detail-card">
        <p class="battle-configuration-eyebrow">WHY THIS RESULT</p>
        <h2>胜率归因</h2>
        <p class="job-detail-muted">
          这条结果没有持久化归因。新完成的任务会在 worker 写入最终概率时同时保存总结型归因。
        </p>
      </section>

      <section class="job-detail-card">
        <p class="battle-configuration-eyebrow">CONTRACT</p>
        <h2>任务合同</h2>
        <dl class="job-detail-grid">
          <div><dt>任务类型</dt><dd>{{ job.job_type }}</dd></div>
          <div><dt>规则集</dt><dd>{{ job.ruleset_id }}</dd></div>
          <div><dt>Version Group</dt><dd>{{ job.version_group_id }}</dd></div>
          <div><dt>计算版本</dt><dd>{{ job.calculation_revision }}</dd></div>
        </dl>
      </section>

      <section v-if="job.error_code || job.error_message" class="job-detail-card job-detail-card--error">
        <p class="battle-configuration-eyebrow">DIAGNOSTIC</p>
        <h2>{{ job.error_code ?? '任务诊断' }}</h2>
        <p>{{ job.error_message }}</p>
      </section>
    </template>

    <BattleGraphTreeScreen
      v-if="treeScreenOpen && graphJourney && reportContext"
      :handle="graphJourney.exploration"
      :context="reportContext"
      @close="treeScreenOpen = false"
      @rerun="openGraphAndReport"
    />
  </main>
</template>

<style scoped>
.job-detail-view {
  display: grid;
  gap: 18px;
}

.job-detail-hero,
.job-detail-card {
  background: var(--surface, #fff);
  border: 1px solid var(--border, #d9dee8);
  border-radius: 14px;
  padding: 20px;
}

.job-detail-hero {
  align-items: center;
  display: flex;
  gap: 16px;
  justify-content: space-between;
}

.job-detail-hero h1 {
  margin: 4px 0;
}

.job-detail-hero code {
  overflow-wrap: anywhere;
}

.job-detail-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
}

.job-detail-feedback {
  margin: 0;
}

.job-detail-feedback--ok {
  color: #174232;
  font-weight: 800;
}

.job-detail-status {
  align-items: center;
  display: flex;
  gap: 10px;
  justify-content: space-between;
}

.job-detail-status span {
  border: 1px solid #bfd8ca;
  border-radius: 999px;
  color: #174232;
  font-weight: 800;
  padding: 6px 10px;
}

.job-detail-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 16px 0 0;
}

.job-detail-grid div {
  background: #f7f8fa;
  border-radius: 10px;
  min-width: 0;
  padding: 12px;
}

.job-detail-grid dt {
  color: #667085;
  font-size: 0.78rem;
}

.job-detail-grid dd {
  font-weight: 800;
  margin: 4px 0 0;
  overflow-wrap: anywhere;
}

.job-detail-progress {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}

.job-detail-progress__meta {
  align-items: center;
  display: flex;
  font-size: 0.85rem;
  justify-content: space-between;
}

.job-detail-progress__track {
  background: #e9f0ec;
  border-radius: 999px;
  height: 10px;
  overflow: hidden;
}

.job-detail-progress__bar {
  background: linear-gradient(90deg, #2f6f55, #b92b37);
  border-radius: inherit;
  height: 100%;
  transition: width 180ms ease;
}

.job-result-heading {
  align-items: end;
  display: flex;
  gap: 16px;
  justify-content: space-between;
}

.job-result-heading h2 {
  margin: 4px 0 0;
}

.job-result-heading small {
  color: #667085;
  max-width: 420px;
}

.job-result-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 16px;
}

.job-result-grid article {
  border: 1px solid #d9e4de;
  border-radius: 10px;
  display: grid;
  gap: 6px;
  padding: 14px;
}

.job-result-grid span,
.job-result-grid small {
  color: #667085;
}

.job-result-grid strong {
  font-size: 1.45rem;
}

.job-explanation-summary {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 16px;
}

.job-explanation-summary article {
  background: #f3f8f5;
  border: 1px solid #d4e4db;
  border-radius: 10px;
  display: grid;
  gap: 5px;
  padding: 12px;
}

.job-explanation-summary span,
.job-explanation-summary small,
.job-explanation-bucket small,
.job-explanation-bucket dt,
.job-detail-muted {
  color: #667085;
}

.job-explanation-summary strong,
.job-explanation-bucket header span {
  color: #173d31;
  font-weight: 900;
}

.job-explanation-list {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.job-explanation-bucket {
  border: 1px solid #d9e4de;
  border-radius: 12px;
  display: grid;
  gap: 10px;
  padding: 12px;
}

.job-explanation-bucket header {
  align-items: start;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.job-explanation-bucket header div {
  display: grid;
  gap: 3px;
}

.job-explanation-meter {
  background: #edf2ef;
  border-radius: 999px;
  height: 8px;
  overflow: hidden;
}

.job-explanation-meter div {
  background: #2f6f55;
  border-radius: inherit;
  height: 100%;
}

.job-explanation-bucket dl {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 0;
}

.job-explanation-bucket dd {
  font-weight: 800;
  margin: 2px 0 0;
}

.job-detail-muted {
  margin: 12px 0 0;
}

.job-detail-card--error {
  border-color: #e2b7bc;
}

@media (max-width: 760px) {
  .job-detail-hero {
    align-items: stretch;
    flex-direction: column;
  }

  .job-detail-actions {
    justify-content: stretch;
  }

  .job-detail-grid {
    grid-template-columns: 1fr;
  }

  .job-result-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .job-result-grid {
    grid-template-columns: 1fr;
  }

  .job-explanation-summary,
  .job-explanation-bucket dl {
    grid-template-columns: 1fr;
  }

  .job-explanation-bucket header {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
