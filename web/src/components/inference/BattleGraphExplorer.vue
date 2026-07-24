<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type {
  BattleExplorationResult,
  BattleGraphExplorationResult,
  TransitionOutcomeResult,
} from '../../api/inference';
import { useBattleExploration } from '../../composables/useBattleExploration';
import BattleGraphNode from './BattleGraphNode.vue';
import TransitionGroupCard from './TransitionGroupCard.vue';
import TransitionOutcomeList from './TransitionOutcomeList.vue';

/** 路径聚焦式状态图浏览器的只读入口。 */
interface Props {
  /** 首次完整推演返回的 graph handle。 */
  handle: BattleExplorationResult;
}

const props = defineProps<Props>();

/**
 * 向父页面发送 graph 生命周期操作和当前服务端 exploration。
 *
 * explorationChange 只传递纯 DTO，不暴露内部 cache、组件实例或节点引用。
 */
const emit = defineEmits<{
  rerun: [];
  explorationChange: [exploration: BattleGraphExplorationResult | null];
}>();

const BREADCRUMB_WINDOW_SIZE = 7;
const breadcrumbWindowStart = ref(0);
const {
  current,
  pathEntries,
  expandedGroupId,
  outcomes,
  loading,
  outcomesLoading,
  error,
  expired,
  canBacktrack,
  start,
  toggleGroup,
  advance,
  goToDepth,
  back,
} = useBattleExploration();

const visibleBreadcrumbs = computed(() =>
  pathEntries.value.slice(
    breadcrumbWindowStart.value,
    breadcrumbWindowStart.value + BREADCRUMB_WINDOW_SIZE,
  ),
);

const canPageBreadcrumbsBackward = computed(() => breadcrumbWindowStart.value > 0);
const canPageBreadcrumbsForward = computed(
  () => breadcrumbWindowStart.value + BREADCRUMB_WINDOW_SIZE < pathEntries.value.length,
);

/**
 * 把 breadcrumb 窗口移动到最新路径尾部，限制实际渲染节点数量。
 */
function focusLatestBreadcrumbs(): void {
  breadcrumbWindowStart.value = Math.max(0, pathEntries.value.length - BREADCRUMB_WINDOW_SIZE);
}

/**
 * 以固定窗口大小向前或向后分页轻量 breadcrumb。
 *
 * @param direction -1 查看更早祖先，1 查看更近当前节点的路径步骤。
 */
function pageBreadcrumbs(direction: -1 | 1): void {
  const maximumStart = Math.max(0, pathEntries.value.length - BREADCRUMB_WINDOW_SIZE);
  const next = breadcrumbWindowStart.value + direction * BREADCRUMB_WINDOW_SIZE;
  breadcrumbWindowStart.value = Math.min(maximumStart, Math.max(0, next));
}

/**
 * 跳转到用户点击的真实路径深度，并让窗口重新聚焦当前祖先。
 *
 * @param depth breadcrumb 对应的 cursor edge 深度。
 */
async function selectBreadcrumb(depth: number): Promise<void> {
  await goToDepth(depth);
  focusLatestBreadcrumbs();
}

/**
 * 选择 outcome 后进入目标节点；旧 outcome 子树会随响应切换被卸载。
 *
 * @param outcome 当前分支组中由服务端归并后的正式 edge。
 */
async function selectOutcome(outcome: TransitionOutcomeResult): Promise<void> {
  await advance(outcome);
  focusLatestBreadcrumbs();
}

/**
 * 通知页面重新执行完整推演，以创建新的 graph 生命周期。
 */
function requestRerun(): void {
  emit('rerun');
}

watch(
  () => props.handle,
  async (handle) => {
    breadcrumbWindowStart.value = 0;
    await start(handle);
    focusLatestBreadcrumbs();
  },
  { immediate: true },
);

watch(
  current,
  (exploration) => {
    // 父页面只保存服务端返回的 DTO，因此左侧组件卸载后战报仍可继续渲染。
    emit('explorationChange', exploration);
  },
  { immediate: true },
);
</script>

<template>
  <section class="battle-graph-explorer" aria-label="路径聚焦式状态图浏览器">
    <header class="battle-graph-explorer__header">
      <div>
        <p>PROGRESSIVE GRAPH EXPLORATION</p>
        <h2>路径聚焦式状态图</h2>
        <small>只保留当前窗口；完整胜负概率仍以上方 summary 为准。</small>
      </div>
      <button v-if="canBacktrack && !expired" type="button" class="battle-graph-explorer__back" @click="back">
        ← 返回上一级
      </button>
    </header>

    <div v-if="expired" class="battle-graph-explorer__expired" role="alert">
      <strong>状态图已过期</strong>
      <p>{{ error }}</p>
      <button type="button" @click="requestRerun">重新完整推演</button>
    </div>

    <template v-else>
      <nav v-if="pathEntries.length" class="battle-graph-explorer__breadcrumbs" aria-label="探索路径">
        <button
          v-if="canPageBreadcrumbsBackward"
          type="button"
          class="battle-graph-explorer__breadcrumb-page"
          aria-label="查看更早祖先"
          @click="pageBreadcrumbs(-1)"
        >
          …
        </button>
        <button
          v-for="entry in visibleBreadcrumbs"
          :key="`${entry.depth}:${entry.nodeId}`"
          type="button"
          class="battle-graph-explorer__breadcrumb"
          :class="{ 'battle-graph-explorer__breadcrumb--current': entry.depth === current?.cursor.steps.length }"
          :data-depth="entry.depth"
          @click="selectBreadcrumb(entry.depth)"
        >
          <span>{{ entry.depth === 0 ? 'ROOT' : `STEP ${entry.depth}` }}</span>
          <strong>{{ entry.label }}</strong>
          <small>node #{{ entry.nodeId }}</small>
        </button>
        <button
          v-if="canPageBreadcrumbsForward"
          type="button"
          class="battle-graph-explorer__breadcrumb-page"
          aria-label="查看更近当前节点的路径"
          @click="pageBreadcrumbs(1)"
        >
          …
        </button>
      </nav>

      <p v-if="error" class="battle-graph-explorer__error" role="alert">{{ error }}</p>
      <p v-if="loading && !current" class="battle-graph-explorer__loading">正在加载根节点…</p>

      <div
        v-if="current"
        :key="`${current.graph_id}:${current.cursor.steps.length}:${current.node.node_id}`"
        class="battle-graph-explorer__window"
        data-testid="exploration-window"
      >
        <BattleGraphNode :node="current.node" :cumulative-probability="current.cumulative_probability" />

        <div v-if="!current.terminal" class="battle-graph-explorer__connector" aria-hidden="true">│</div>

        <section v-if="!current.terminal" class="battle-graph-explorer__groups">
          <header>
            <strong>下一步概率分支</strong>
            <small>{{ current.transition_groups.length }} 组 · 点击后才加载 outcomes</small>
          </header>
          <template v-for="group in current.transition_groups" :key="group.group_id">
            <TransitionGroupCard
              :group="group"
              :expanded="expandedGroupId === group.group_id"
              :loading="outcomesLoading"
              @toggle="toggleGroup"
            />
            <TransitionOutcomeList
              v-if="expandedGroupId === group.group_id && !outcomesLoading"
              :key="`${current.cursor.steps.length}:${group.group_id}`"
              :group-id="group.group_id"
              :outcomes="outcomes"
              :disabled="loading"
              @select="selectOutcome"
            />
          </template>
          <p v-if="current.transition_groups.length === 0" class="battle-graph-explorer__empty">
            当前非终局节点没有可用分支，请重新推演或检查图完整性。
          </p>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.battle-graph-explorer {
  margin-top: 42px;
  border: 1px solid #d3ddd6;
  border-radius: 20px;
  padding: 22px;
  background:
    radial-gradient(circle at 100% 0, rgba(42, 108, 81, 0.08), transparent 28%),
    rgba(247, 250, 248, 0.96);
  box-shadow: 0 18px 42px rgba(40, 64, 53, 0.06);
}

.battle-graph-explorer__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
}

.battle-graph-explorer__header p,
.battle-graph-explorer__header h2,
.battle-graph-explorer__header small,
.battle-graph-explorer__expired p,
.battle-graph-explorer__error,
.battle-graph-explorer__loading,
.battle-graph-explorer__empty {
  margin: 0;
}

.battle-graph-explorer__header p {
  color: #9d3039;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.16em;
}

.battle-graph-explorer__header h2 {
  margin-top: 5px;
  color: #173d31;
  font-size: 27px;
}

.battle-graph-explorer__header small {
  display: block;
  margin-top: 6px;
  color: #748078;
}

.battle-graph-explorer__back,
.battle-graph-explorer__expired button {
  min-height: 38px;
  border: 1px solid #9bb8a9;
  border-radius: 10px;
  padding: 0 13px;
  background: #fff;
  color: #286b52;
  font-weight: 800;
}

.battle-graph-explorer__breadcrumbs {
  display: flex;
  align-items: stretch;
  gap: 6px;
  overflow: hidden;
  margin-top: 18px;
  border-radius: 13px;
  padding: 7px;
  background: #e9efeb;
}

.battle-graph-explorer__breadcrumb,
.battle-graph-explorer__breadcrumb-page {
  flex: 1 1 0;
  min-width: 0;
  border: 0;
  border-radius: 8px;
  padding: 8px 9px;
  background: rgba(255, 255, 255, 0.75);
  color: #637269;
  text-align: left;
}

.battle-graph-explorer__breadcrumb:hover,
.battle-graph-explorer__breadcrumb--current {
  background: #fff;
  box-shadow: 0 5px 14px rgba(37, 69, 54, 0.08);
}

.battle-graph-explorer__breadcrumb span,
.battle-graph-explorer__breadcrumb strong,
.battle-graph-explorer__breadcrumb small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.battle-graph-explorer__breadcrumb span,
.battle-graph-explorer__breadcrumb small {
  font-size: 8px;
}

.battle-graph-explorer__breadcrumb strong {
  margin: 3px 0;
  color: #294437;
  font-size: 10px;
}

.battle-graph-explorer__breadcrumb-page {
  flex: 0 0 34px;
  text-align: center;
  font-weight: 900;
}

.battle-graph-explorer__window {
  width: min(720px, 100%);
  margin: 18px auto 0;
}

.battle-graph-explorer__connector {
  height: 26px;
  color: #87a797;
  text-align: center;
  line-height: 26px;
}

.battle-graph-explorer__groups {
  display: grid;
  gap: 8px;
}

.battle-graph-explorer__groups > header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 3px;
}

.battle-graph-explorer__groups > header strong {
  color: #294438;
  font-size: 13px;
}

.battle-graph-explorer__groups > header small,
.battle-graph-explorer__empty,
.battle-graph-explorer__loading {
  color: #7a867f;
  font-size: 11px;
}

.battle-graph-explorer__error,
.battle-graph-explorer__expired {
  margin-top: 16px;
  border-radius: 12px;
  padding: 13px;
  background: #fff0f1;
  color: #8f343c;
}

.battle-graph-explorer__expired {
  display: grid;
  justify-items: start;
  gap: 8px;
}

.battle-graph-explorer__loading {
  margin-top: 18px;
  text-align: center;
}

@media (max-width: 700px) {
  .battle-graph-explorer {
    padding: 16px;
  }

  .battle-graph-explorer__header {
    align-items: stretch;
    flex-direction: column;
  }

  .battle-graph-explorer__breadcrumbs {
    overflow-x: auto;
  }

  .battle-graph-explorer__breadcrumb {
    flex-basis: 120px;
  }

  .battle-graph-explorer__groups > header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
