<script setup lang="ts">
import type { PresentedBattleReportTurn } from '../../presenters/battleEventPresenter';

/** BattleReportTurn 的只读展示输入。 */
interface Props {
  /** 当前回合的 presenter DTO。 */
  turn: PresentedBattleReportTurn;
  /** 当前回合内容是否展开。 */
  expanded: boolean;
  /** 当前回合是否为 cursor 路径中的最后一个回合。 */
  current: boolean;
}

defineProps<Props>();

/** 请求父组件切换当前回合的折叠状态。 */
defineEmits<{
  toggle: [];
}>();
</script>

<template>
  <article
    class="battle-report-turn"
    :class="{ 'battle-report-turn--current': current }"
    :data-turn-number="turn.turnNumber"
  >
    <button
      class="battle-report-turn__header"
      type="button"
      :aria-expanded="expanded"
      @click="$emit('toggle')"
    >
      <span>
        <strong>回合 {{ turn.turnNumber }}</strong>
        <small>{{ current ? '当前路径' : '历史回合' }}</small>
      </span>
      <span class="battle-report-turn__summary">
        {{ turn.events.length }} 条事件
        <i aria-hidden="true">{{ expanded ? '−' : '+' }}</i>
      </span>
    </button>

    <div v-if="expanded" class="battle-report-turn__body">
      <p v-if="turn.alternativePathCount > 1" class="battle-report-turn__alternatives">
        此 edge 保留 {{ turn.alternativePathCount }} 条等价事件解释，当前按稳定首条展示。
      </p>
      <ol v-if="turn.events.length" class="battle-report-event-list">
        <li
          v-for="event in turn.events"
          :key="event.id"
          class="battle-report-event"
          :class="`battle-report-event--${event.tone}`"
          :data-event-kind="event.kind"
          :title="event.debug ?? undefined"
        >
          {{ event.text }}
        </li>
      </ol>
      <p v-else class="battle-report-turn__empty">该回合没有需要展示的业务事件。</p>
    </div>
  </article>
</template>

<style scoped>
.battle-report-turn {
  overflow: hidden;
  border: 1px solid #dce4df;
  border-radius: 12px;
  background: #fff;
}

.battle-report-turn--current {
  border-color: #86ad9a;
  box-shadow: 0 8px 18px rgba(38, 91, 67, 0.08);
}

.battle-report-turn__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-height: 58px;
  border: 0;
  padding: 11px 14px;
  background: #f8faf8;
  color: #28483b;
  text-align: left;
}

.battle-report-turn--current .battle-report-turn__header {
  background: #edf5f1;
}

.battle-report-turn__header > span {
  display: flex;
  align-items: center;
  gap: 8px;
}

.battle-report-turn__header strong {
  font-size: 13px;
}

.battle-report-turn__header small,
.battle-report-turn__summary {
  color: #7a8780;
  font-size: 10px;
}

.battle-report-turn__summary {
  flex: 0 0 auto;
}

.battle-report-turn__summary i {
  display: inline-grid;
  width: 22px;
  height: 22px;
  place-items: center;
  margin-left: 5px;
  border-radius: 50%;
  background: #fff;
  color: #315849;
  font-style: normal;
  font-size: 15px;
}

.battle-report-turn__body {
  border-top: 1px solid #e3e9e5;
  padding: 12px 14px 14px;
}

.battle-report-turn__alternatives {
  margin: 0 0 10px;
  border-radius: 8px;
  padding: 8px 10px;
  background: #fff7e6;
  color: #82652a;
  font-size: 10px;
  line-height: 1.5;
}

.battle-report-event-list {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.battle-report-event {
  border-left: 3px solid #b5c4bc;
  border-radius: 0 8px 8px 0;
  padding: 8px 10px;
  background: #f7f9f7;
  color: #465950;
  font-size: 12px;
  line-height: 1.5;
}

.battle-report-event--move {
  border-left-color: #4d7f69;
  color: #274c3b;
  font-weight: 800;
}

.battle-report-event--success {
  border-left-color: #4d9470;
  background: #f0f8f3;
  color: #2f6a4c;
}

.battle-report-event--danger {
  border-left-color: #ba4650;
  background: #fff4f5;
  color: #8d3139;
}

.battle-report-event--mechanism {
  border-left-color: #8466ad;
  background: #f8f4fc;
  color: #624b82;
}

.battle-report-event--status {
  border-left-color: #ca8a31;
  background: #fff8ec;
  color: #805b23;
}

.battle-report-event--unknown {
  border-left-color: #7b7f7d;
  background: #f2f3f2;
  color: #5d6460;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.battle-report-turn__empty {
  margin: 0;
  color: #7b8780;
  font-size: 11px;
}
</style>
