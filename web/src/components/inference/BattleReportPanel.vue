<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { BattleReportResult } from '../../api/inference';
import {
  presentBattleReport,
  type BattleReportPresenterContext,
} from '../../presenters/battleEventPresenter';
import BattleReportTurn from './BattleReportTurn.vue';

/** BattleReportPanel 的只读数据输入。 */
interface Props {
  /** 当前 exploration cursor 对应的完整结构化战报。 */
  report: BattleReportResult | null;
  /** Pokémon、最大 HP 和招式名称的纯展示上下文。 */
  context: BattleReportPresenterContext;
}

const props = defineProps<Props>();
const turns = computed(() =>
  props.report === null ? [] : presentBattleReport(props.report, props.context),
);
const expandedTurns = ref<Set<number>>(new Set());

/**
 * cursor 深度变化时只默认展开最新回合，并清理已被 backtrack 删除的展开状态。
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
        <p>BATTLE REPORT</p>
        <h2>逐回合战报</h2>
        <small>严格按服务端 cursor 的真实 edge 顺序生成。</small>
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
        <span>在左侧展开概率分支并选择 outcome 后，这里会追加对应结构化战报。</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.battle-report-panel {
  min-width: 0;
  overflow: hidden;
  border: 1px solid #d6dfd9;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 42px rgba(40, 64, 53, 0.06);
}

.battle-report-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid #e0e7e2;
  padding: 22px;
  background:
    radial-gradient(circle at 90% 0, rgba(180, 43, 54, 0.1), transparent 36%),
    #fff;
}

.battle-report-panel__header p,
.battle-report-panel__header h2,
.battle-report-panel__header small {
  margin: 0;
}

.battle-report-panel__header p {
  color: #9d3039;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.16em;
}

.battle-report-panel__header h2 {
  margin-top: 5px;
  color: #173d31;
  font-size: 27px;
}

.battle-report-panel__header > div:first-child small {
  display: block;
  margin-top: 6px;
  color: #748078;
}

.battle-report-probability {
  display: grid;
  gap: 3px;
  text-align: right;
}

.battle-report-probability span,
.battle-report-probability small {
  color: #7c8781;
  font-size: 10px;
}

.battle-report-probability strong {
  color: #85313a;
  font-size: 13px;
}

.battle-report-panel__scroll {
  max-height: min(68vh, 720px);
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  padding: 14px;
}

.battle-report-panel__turns {
  display: grid;
  gap: 9px;
}

.battle-report-panel__empty {
  display: grid;
  gap: 7px;
  min-height: 220px;
  place-content: center;
  padding: 24px;
  color: #718078;
  text-align: center;
}

.battle-report-panel__empty strong {
  color: #385448;
  font-size: 14px;
}

.battle-report-panel__empty span {
  max-width: 430px;
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 700px) {
  .battle-report-panel__header {
    align-items: flex-start;
    flex-direction: column;
    padding: 16px;
  }

  .battle-report-probability {
    text-align: left;
  }

  .battle-report-panel__scroll {
    max-height: 560px;
    padding: 10px;
  }
}
</style>
