<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import {
  exploreBattleGraph,
  type BattleExplorationResult,
  type BattleNodeDetailResult,
} from '../../api/inference';
import {
  listWinningPathGroups,
  type WinningPathGroupResult,
  type WinningPathGroupsResult,
  type WinningPathWinner,
} from '../../api/winningPaths';
import WinningPathPrefixTree from './WinningPathPrefixTree.vue';

/** 胜利路径查询面板的只读入口。 */
interface Props {
  /** 首次推演返回、仍受 TTL 约束的 graph handle。 */
  handle: BattleExplorationResult;
  /** 用户从胜率卡片选择的绝对获胜侧。 */
  winner: WinningPathWinner;
  /** 招式 ID 到用户可读名称的映射。 */
  moveNames: Record<number, string>;
}

const props = defineProps<Props>();
const loading = ref(false);
const locating = ref(false);
const error = ref('');
const pages = ref<WinningPathGroupsResult[]>([]);
const expandedPathKey = ref<string | null>(null);
const locatedNode = ref<BattleNodeDetailResult | null>(null);

const latestPage = computed(() => pages.value[pages.value.length - 1] ?? null);
const groups = computed(() => pages.value.flatMap((page) => page.path_groups));
const winnerLabel = computed(() => (props.winner === 'attacker' ? '攻击方' : '防守方'));

/**
 * 查询首页并清空另一个胜者或上一张 graph 的旧数据。
 */
async function loadFirstPage(): Promise<void> {
  loading.value = true;
  error.value = '';
  pages.value = [];
  expandedPathKey.value = null;
  locatedNode.value = null;
  try {
    const page = await listWinningPathGroups(
      props.handle.graph_id,
      props.handle.calculation_revision,
      props.winner,
    );
    pages.value = [page];
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '胜利路径查询失败';
  } finally {
    loading.value = false;
  }
}

/**
 * 使用后端不透明游标追加下一页，避免重复或遗漏已返回路径组。
 */
async function loadMore(): Promise<void> {
  const current = latestPage.value;
  if (current === null || !current.has_more || current.next_cursor === null || loading.value) {
    return;
  }
  loading.value = true;
  error.value = '';
  try {
    const page = await listWinningPathGroups(
      props.handle.graph_id,
      props.handle.calculation_revision,
      props.winner,
      10,
      current.next_cursor,
    );
    pages.value = [...pages.value, page];
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '加载更多胜利路径失败';
  } finally {
    loading.value = false;
  }
}

/**
 * 展开或收起一个路径组的离散伤害、剩余 HP 与关键事件细节。
 *
 * @param pathKey 后端按配置和行动序列生成的稳定路径组键。
 */
function toggleDetails(pathKey: string): void {
  expandedPathKey.value = expandedPathKey.value === pathKey ? null : pathKey;
}

/**
 * 使用代表性 edge cursor 读取真实状态图终点，并把页面滚动回图浏览区域。
 *
 * @param group 用户选择定位的归并胜利路径组。
 */
async function locateInGraph(group: WinningPathGroupResult): Promise<void> {
  locating.value = true;
  error.value = '';
  try {
    const exploration = await exploreBattleGraph(
      props.handle.graph_id,
      props.handle.calculation_revision,
      { steps: group.representative_path.map((step) => ({ ...step })) },
    );
    locatedNode.value = exploration.node;
    await nextTick();
    document.querySelector('.battle-exploration-layout')?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '状态图定位失败';
  } finally {
    locating.value = false;
  }
}

/**
 * 把可空招式 ID 转换为紧凑用户标签。
 *
 * @param moveId 当前联合行动中的招式 ID。
 * @returns 优先使用招式名、其次使用 ID、最后返回未记录。
 */
function moveLabel(moveId: number | null): string {
  if (moveId === null) {
    return '未记录';
  }
  return props.moveNames[moveId] ?? `招式 #${moveId}`;
}

/**
 * 格式化后端概率近似值。
 *
 * @param percent 百分制近似概率。
 * @returns 保留四位小数的百分比文本。
 */
function formatPercent(percent: number): string {
  return `${percent.toFixed(4)}%`;
}

watch(
  () => [props.handle.graph_id, props.winner] as const,
  loadFirstPage,
  { immediate: true },
);
</script>

<template>
  <section class="winning-path-panel" aria-label="胜利路径 Top-K 与行动前缀树">
    <header class="winning-path-panel__header">
      <div>
        <p>WINNING PATH TOP-K</p>
        <h2>{{ winnerLabel }}胜利路径</h2>
        <small>先按配置隔离，再按双方每回合联合行动序列归并。</small>
      </div>
      <div v-if="latestPage" class="winning-path-panel__coverage">
        <span>本页覆盖胜者概率质量</span>
        <strong>
          {{ latestPage.returned_coverage ? formatPercent(latestPage.returned_coverage.percent) : '不可用' }}
        </strong>
        <small>
          {{ latestPage.query_complete ? '查询完整' : '有限查询；循环或预算已显式压缩' }}
        </small>
      </div>
    </header>

    <div v-if="latestPage" class="winning-path-config">
      <div>
        <span>{{ latestPage.configuration.attacker.name }}</span>
        <small>招式 {{ latestPage.configuration.attacker.move_ids.map(moveLabel).join(' / ') }}</small>
      </div>
      <i>VS</i>
      <div>
        <span>{{ latestPage.configuration.defender.name }}</span>
        <small>招式 {{ latestPage.configuration.defender.move_ids.map(moveLabel).join(' / ') }}</small>
      </div>
      <code>{{ latestPage.configuration.configuration_key }}</code>
    </div>

    <p v-if="error" class="winning-path-panel__error" role="alert">{{ error }}</p>
    <p v-if="loading && pages.length === 0" class="winning-path-panel__empty">正在查询胜利路径…</p>

    <template v-if="latestPage">
      <article class="winning-path-tree">
        <div class="winning-path-tree__title">
          <div>
            <strong>当前页行动前缀树</strong>
            <small>伤害档位与剩余 HP 不参与一级路径键。</small>
          </div>
          <span>{{ latestPage.path_groups.length }} 组</span>
        </div>
        <div class="winning-path-tree__scroll">
          <WinningPathPrefixTree
            :node="latestPage.prefix_tree"
            :move-names="moveNames"
            root
          />
        </div>
      </article>

      <div class="winning-path-list">
        <article v-for="(group, index) in groups" :key="group.path_key" class="winning-path-row">
          <div class="winning-path-row__rank">#{{ index + 1 }}</div>
          <div class="winning-path-row__main">
            <div class="winning-path-row__summary">
              <strong>第 {{ group.terminal_turn }} 回合终局</strong>
              <span>{{ formatPercent(group.probability.percent) }}</span>
              <small>
                {{ group.raw_path_count }} 条图路径 · 约 {{ group.raw_history_count_estimate }} 条事件历史
              </small>
            </div>
            <ol class="winning-path-actions">
              <li v-for="action in group.actions" :key="`${group.path_key}:${action.turn_number}`">
                <span>T{{ action.turn_number }}</span>
                <strong>{{ moveLabel(action.attacker_move_id) }}</strong>
                <i>×</i>
                <strong>{{ moveLabel(action.defender_move_id) }}</strong>
                <em v-if="action.ambiguous">多候选</em>
              </li>
            </ol>
            <div class="winning-path-row__buttons">
              <button type="button" @click="toggleDetails(group.path_key)">
                {{ expandedPathKey === group.path_key ? '收起随机细节' : '展开随机细节' }}
              </button>
              <button type="button" :disabled="locating" @click="locateInGraph(group)">
                定位状态图
              </button>
            </div>
            <div v-if="expandedPathKey === group.path_key" class="winning-path-details">
              <div>
                <span>离散伤害</span>
                <code v-for="value in group.damage_values" :key="`damage:${value}`">{{ value }}</code>
                <small v-if="group.damage_values.length === 0">无伤害事件</small>
              </div>
              <div>
                <span>攻击方剩余 HP</span>
                <code v-for="value in group.attacker_remaining_hp_values" :key="`attacker:${value}`">{{ value }}</code>
              </div>
              <div>
                <span>防守方剩余 HP</span>
                <code v-for="value in group.defender_remaining_hp_values" :key="`defender:${value}`">{{ value }}</code>
              </div>
              <div v-if="group.key_events.length">
                <span>关键事件</span>
                <code v-for="event in group.key_events" :key="`${event.kind}:${event.actor}:${event.move_id}:${event.source_identifier}`">
                  {{ event.kind }}{{ event.source_identifier ? ` · ${event.source_identifier}` : '' }}
                </code>
              </div>
            </div>
          </div>
        </article>
      </div>

      <div v-if="latestPage.cycle_references.length" class="winning-path-cycles">
        <strong>循环已压缩为 {{ latestPage.cycle_references.length }} 个回边引用</strong>
        <span
          v-for="cycle in latestPage.cycle_references"
          :key="`${cycle.source_node_id}:${cycle.edge_id}:${cycle.target_node_id}:${cycle.prefix_depth}`"
        >
          node #{{ cycle.source_node_id }} — edge #{{ cycle.edge_id }} → node #{{ cycle.target_node_id }}
        </span>
      </div>

      <div v-if="locatedNode" class="winning-path-located" role="status">
        已定位 node #{{ locatedNode.node_id }}：Turn {{ locatedNode.turn_number }} ·
        HP {{ locatedNode.attacker.current_hp }} / {{ locatedNode.defender.current_hp }} ·
        {{ locatedNode.outcome }}
      </div>

      <button
        v-if="latestPage.has_more"
        type="button"
        class="winning-path-panel__more"
        :disabled="loading"
        @click="loadMore"
      >
        {{ loading ? '正在加载…' : '加载更多路径组' }}
      </button>
      <p v-else-if="groups.length === 0" class="winning-path-panel__empty">当前胜者没有可返回的有限终局路径。</p>
    </template>
  </section>
</template>

<style scoped>
.winning-path-panel {
  margin-top: 38px;
  overflow: hidden;
  border: 1px solid #d5dfd9;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 44px rgba(40, 64, 53, 0.07);
}

.winning-path-panel__header,
.winning-path-config,
.winning-path-tree,
.winning-path-list,
.winning-path-cycles,
.winning-path-located,
.winning-path-panel__empty,
.winning-path-panel__error {
  margin: 0 20px;
}

.winning-path-panel__header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 22px 0 18px;
}

.winning-path-panel__header p,
.winning-path-panel__header h2,
.winning-path-panel__header small {
  margin: 0;
}

.winning-path-panel__header p {
  color: #9d3039;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.16em;
}

.winning-path-panel__header h2 {
  margin-top: 5px;
  color: #173d31;
  font-size: 28px;
}

.winning-path-panel__header small {
  color: #748078;
}

.winning-path-panel__coverage {
  display: grid;
  gap: 3px;
  text-align: right;
}

.winning-path-panel__coverage span,
.winning-path-panel__coverage small {
  color: #748078;
  font-size: 10px;
}

.winning-path-panel__coverage strong {
  color: #8e3039;
  font-size: 20px;
}

.winning-path-config {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  border: 1px solid #e0e7e2;
  border-radius: 14px;
  padding: 12px 15px;
  background: #f8fbf9;
}

.winning-path-config div {
  display: grid;
  gap: 3px;
}

.winning-path-config span {
  color: #173d31;
  font-weight: 850;
}

.winning-path-config small,
.winning-path-config code {
  color: #748078;
  font-size: 10px;
}

.winning-path-config i {
  color: #a44952;
  font-style: normal;
  font-weight: 900;
}

.winning-path-tree {
  margin-top: 16px;
  border: 1px solid #e0e7e2;
  border-radius: 15px;
}

.winning-path-tree__title {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid #e0e7e2;
  padding: 12px 14px;
}

.winning-path-tree__title div {
  display: grid;
  gap: 2px;
}

.winning-path-tree__title strong {
  color: #173d31;
}

.winning-path-tree__title small,
.winning-path-tree__title span {
  color: #748078;
  font-size: 10px;
}

.winning-path-tree__scroll {
  overflow-x: auto;
  padding: 14px;
}

.winning-path-list {
  display: grid;
  gap: 9px;
  margin-top: 14px;
}

.winning-path-row {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  gap: 11px;
  border: 1px solid #dfe7e2;
  border-radius: 14px;
  padding: 12px;
}

.winning-path-row__rank {
  display: grid;
  place-items: center;
  align-self: start;
  min-height: 34px;
  border-radius: 10px;
  background: #f2e9ea;
  color: #8c3038;
  font-weight: 900;
}

.winning-path-row__main {
  display: grid;
  gap: 10px;
}

.winning-path-row__summary {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 9px;
}

.winning-path-row__summary strong {
  color: #173d31;
}

.winning-path-row__summary span {
  color: #9d3039;
  font-weight: 900;
}

.winning-path-row__summary small {
  color: #748078;
}

.winning-path-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.winning-path-actions li {
  display: flex;
  align-items: center;
  gap: 5px;
  border-radius: 999px;
  padding: 5px 9px;
  background: #eef5f1;
  font-size: 11px;
}

.winning-path-actions span,
.winning-path-actions i {
  color: #748078;
  font-style: normal;
}

.winning-path-actions strong {
  color: #225b46;
}

.winning-path-actions em {
  color: #9d3039;
  font-size: 9px;
  font-style: normal;
}

.winning-path-row__buttons {
  display: flex;
  gap: 8px;
}

.winning-path-row__buttons button,
.winning-path-panel__more {
  border: 1px solid #aac0b5;
  border-radius: 9px;
  padding: 7px 11px;
  background: #fff;
  color: #286b52;
  font-weight: 800;
}

.winning-path-details {
  display: grid;
  gap: 7px;
  border-radius: 10px;
  padding: 10px;
  background: #faf7f7;
}

.winning-path-details div {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.winning-path-details span {
  min-width: 90px;
  color: #6f7973;
  font-size: 10px;
  font-weight: 800;
}

.winning-path-details code {
  border-radius: 999px;
  padding: 2px 7px;
  background: #fff;
  color: #713840;
  font-size: 10px;
}

.winning-path-cycles,
.winning-path-located {
  display: grid;
  gap: 4px;
  margin-top: 14px;
  border-radius: 12px;
  padding: 11px 13px;
  background: #fff7e8;
  color: #795d25;
  font-size: 11px;
}

.winning-path-located {
  background: #edf6f0;
  color: #286b52;
}

.winning-path-panel__more {
  display: block;
  margin: 15px auto 20px;
}

.winning-path-panel__empty,
.winning-path-panel__error {
  padding: 18px 0;
  color: #748078;
}

.winning-path-panel__error {
  color: #a02f39;
}

@media (max-width: 760px) {
  .winning-path-panel__header {
    flex-direction: column;
  }

  .winning-path-panel__coverage {
    text-align: left;
  }

  .winning-path-config {
    grid-template-columns: 1fr;
  }

  .winning-path-config i {
    display: none;
  }
}
</style>
