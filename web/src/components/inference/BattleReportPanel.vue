<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { BattleReportResult } from '../../api/inference';
import {
  presentBattleReport,
  type BattleReportPresenterContext,
} from '../../presenters/battleEventPresenter';
import BattleReportTurn from './BattleReportTurn.vue';

/** BattleReportPanel 的只读数据输入。 */
interface BattleReportPanelProps {
  /** 当前 exploration cursor 对应的完整结构化战报。 */
  report: BattleReportResult | null;
  /** Pokémon、最大 HP 和招式名称的纯展示上下文。 */
  context: BattleReportPresenterContext;
  /** 前进、回退或重新加载战报时的操作状态。 */
  loading?: boolean;
  /** 当前探索操作失败时的用户可读消息。 */
  error?: string;
}

const props = withDefaults(defineProps<BattleReportPanelProps>(), {
  loading: false,
  error: '',
});

const turns = computed(() =>
  props.report === null ? [] : presentBattleReport(props.report, props.context),
);
const expandedTurns = ref<Set<number>>(new Set());

/**
 * 当 cursor 深度变化时只默认展开最新回合，并清理已被 backtrack 删除的历史状态。
 *
 * @param depth 当前 report 深度；根节点或无 report 时为 0。
 */
watch(
  () => props.report?.depth ?? 0,
  () => {
    const currentTurn = turns.value[turns.value.length - 1]?.turnNumber;
    expandedTurns.value =
      currentTurn === undefined ? new Set<number>() : new Set([currentTurn]);
  },
  { immediate: true },
);

/**
 * 切换一个仍存在于当前 report 中的回合折叠状态。
 *
 * @param turnNumber 用户点击的正整数回合号。
 */
function toggleTurn(turnNumber: number): void {
  const next = new Set(expandedTurns.value);
  if (next.has(turnNumber)) {
    next.delete(turnNumber);
  } else {
    next.add(turnNumber);
  }
  expandedTurns.value = next;
}

/**
 * 格式化仅供视觉展示的概率百分比。
 *
 * @param percent 后端返回的近似百分比。
 * @returns 保留四位小数的百分比文本。
 */
function formatPercent(percent: number): string {
  return `${percent.toFixed(4)}%`;
}
</script>

<template>
  <aside class="battle-report-panel" aria-label="当前探索路径战报">
    <header class="battle-report-panel__header">
      <div>
        <p class="eyebrow">BATTLE REPORT</p>
        <h3>逐回合战报</h3>
      </div>
      <div v-if="report" class="battle-report-probability">
        <span>当前路径概率</span>
        <strong>
          {{ report.cumulative_probability.numerator }}
          /
          {{ report.cumulative_probability.denominator }}
        </strong>
        <small>{{ formatPercent(report.cumulative_probability.percent) }}</small>
      </div>
    </header>

    <p v-if="loading" class="battle-report-panel__notice">正在同步当前 cursor…</p>
    <p v-if="error" class="battle-report-panel__error">{{ error }}</p>

    <div class="battle-report-panel__scroll" data-bounded-report-scroll>
      <div v-if="turns.length" class="battle-report-panel__turns">
        <BattleReportTurn
          v-for="(turn, index) in turns"
          :key="turn.turnNumber"
          :turn="turn"
          :expanded="expandedTurns.has(turn.turnNumber)"
          :current="index === turns.length - 1"
          @toggle="toggleTurn(turn.turnNumber)"
        />
      </div>
      <div v-else class="battle-report-panel__empty">
        <strong>尚未选择任何路径</strong>
        <span>在左侧展开概率分支并选择 outcome 后，这里会按真实 edge 序列追加战报。</span>
      </div>
    </div>
  </aside>
</template>
