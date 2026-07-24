<script setup lang="ts">
import type { TransitionOutcomeResult } from '../../api/inference';

interface Props {
  groupId: string;
  outcomes: TransitionOutcomeResult[];
  disabled: boolean;
}

defineProps<Props>();

const emit = defineEmits<{
  select: [outcome: TransitionOutcomeResult];
}>();

/**
 * 汇总 outcome 保留的原始伤害档和实际 HP 损失。
 *
 * @param outcome 已按目标状态归并的正式 edge。
 * @returns 主标签展示实际 HP 损失；无伤害数据时回退到结构化结果 key。
 */
function outcomeTitle(outcome: TransitionOutcomeResult): string {
  if (outcome.damage_rolls.length > 0) {
    const losses = outcome.damage_rolls.map((roll) => roll.actual_hp_loss);
    const minimum = Math.min(...losses);
    const maximum = Math.max(...losses);
    return minimum === maximum ? `造成 ${minimum} HP 损失` : `造成 ${minimum}～${maximum} HP 损失`;
  }
  const resultKey = outcome.label_fields.result_keys[0];
  return resultKey
    ? resultKey.replaceAll('-', ' ').replaceAll('_', ' ')
    : `进入节点 #${outcome.target_node_id}`;
}

/**
 * 生成原始随机档次级说明，避免把 16 个 raw roll 平铺成 16 个组件。
 *
 * @param outcome 已归并 outcome。
 * @returns 去重排序后的原始随机值，过多时压缩为数量说明。
 */
function rawValuesLabel(outcome: TransitionOutcomeResult): string {
  const values = [...new Set(outcome.raw_random_values)].sort((left, right) => left - right);
  if (values.length === 0) {
    return `${outcome.event_paths.length} 条原始事件路径`;
  }
  if (values.length > 8) {
    return `原始随机值 ${values[0]}～${values[values.length - 1]} · ${values.length} 档`;
  }
  return `原始随机值 ${values.join(' / ')}`;
}

/**
 * 把正式 outcome 交给父组件执行 advance。
 *
 * @param outcome 用户选择的目标状态 edge。
 */
function selectOutcome(outcome: TransitionOutcomeResult): void {
  emit('select', outcome);
}
</script>

<template>
  <div :id="`outcomes-${groupId}`" class="transition-outcome-list" data-testid="transition-outcome-list">
    <p v-if="outcomes.length === 0" class="transition-outcome-list__empty">该分支没有可选择的目标状态。</p>
    <button
      v-for="outcome in outcomes"
      :key="outcome.edge_id"
      type="button"
      class="transition-outcome-list__item"
      :disabled="disabled"
      :data-edge-id="outcome.edge_id"
      @click="selectOutcome(outcome)"
    >
      <span>
        <strong>{{ outcomeTitle(outcome) }}</strong>
        <small>{{ rawValuesLabel(outcome) }}</small>
      </span>
      <span class="transition-outcome-list__probability">
        <strong>{{ outcome.probability.percent.toFixed(2) }}%</strong>
        <small>累计 {{ outcome.cumulative_probability.percent.toFixed(2) }}%</small>
      </span>
      <i aria-hidden="true">→</i>
    </button>
  </div>
</template>

<style scoped>
.transition-outcome-list {
  display: grid;
  gap: 8px;
  max-height: 360px;
  overflow-y: auto;
  border-left: 2px solid #99b7a8;
  padding: 8px 0 8px 14px;
}

.transition-outcome-list__item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 12px;
  width: 100%;
  border: 1px solid #dde5df;
  border-radius: 11px;
  padding: 12px;
  background: #fff;
  color: inherit;
  text-align: left;
}

.transition-outcome-list__item:hover:not(:disabled) {
  border-color: #8aaf9c;
  transform: translateX(2px);
}

.transition-outcome-list__item:disabled {
  opacity: 0.58;
}

.transition-outcome-list__item > span {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.transition-outcome-list__item strong {
  color: #263e33;
  font-size: 12px;
}

.transition-outcome-list__item small,
.transition-outcome-list__empty {
  color: #7a867f;
  font-size: 10px;
}

.transition-outcome-list__probability {
  justify-items: end;
}

.transition-outcome-list__item i {
  color: #327357;
  font-style: normal;
  font-weight: 900;
}

.transition-outcome-list__empty {
  margin: 0;
  padding: 12px;
}
</style>
