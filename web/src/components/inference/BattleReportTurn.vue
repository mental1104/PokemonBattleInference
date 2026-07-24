<script setup lang="ts">
import type { PresentedBattleReportTurn } from '../../presenters/battleEventPresenter';

/** BattleReportTurn 的只读展示输入。 */
interface BattleReportTurnProps {
  /** 当前回合的 presenter DTO。 */
  turn: PresentedBattleReportTurn;
  /** 当前回合内容是否展开。 */
  expanded: boolean;
  /** 当前回合是否为 cursor 路径中的最后一个回合。 */
  current: boolean;
}

defineProps<BattleReportTurnProps>();

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
        <small v-if="current">当前路径</small>
        <small v-else>历史回合</small>
      </span>
      <span class="battle-report-turn__summary">
        {{ turn.events.length }} 条事件
        <i aria-hidden="true">{{ expanded ? '−' : '+' }}</i>
      </span>
    </button>

    <div v-if="expanded" class="battle-report-turn__body">
      <p
        v-if="turn.alternativePathCount > 1"
        class="battle-report-turn__alternatives"
      >
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
