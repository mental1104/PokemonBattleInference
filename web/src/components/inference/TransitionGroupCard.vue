<script setup lang="ts">
import type { TransitionGroupResult } from '../../api/inference';

interface Props {
  group: TransitionGroupResult;
  expanded: boolean;
  loading: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  toggle: [groupId: string];
}>();

/**
 * 把 group kind identifier 转成界面标题。
 *
 * @param kind 服务端投影的显式分支机制类型。
 * @returns 中文优先的分支组名称。
 */
function groupKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    action_selection: '行动选择',
    hit_check: '命中判定',
    speed_tie: '同速判定',
    damage_roll: '伤害乱数',
    additional_effect: '追加效果',
    composite: '组合结果',
  };
  return labels[kind] ?? kind.replaceAll('_', ' ');
}

/**
 * 生成收起状态下的伤害或 HP 损失范围说明。
 *
 * @param group 当前 TransitionGroup 摘要。
 * @returns 有范围时返回紧凑文本；无伤害数据时返回概率分支说明。
 */
function summaryLabel(group: TransitionGroupResult): string {
  const minimum = group.summary.minimum_hp_loss ?? group.summary.minimum_damage;
  const maximum = group.summary.maximum_hp_loss ?? group.summary.maximum_damage;
  if (minimum === null || maximum === null) {
    return `${group.raw_result_count} 条原始路径`;
  }
  return minimum === maximum ? `HP -${minimum}` : `HP -${minimum}～-${maximum}`;
}

/**
 * 通知父组件展开或收起当前分支组。
 */
function toggle(): void {
  emit('toggle', props.group.group_id);
}
</script>

<template>
  <article class="transition-group-card" :class="{ 'transition-group-card--expanded': expanded }">
    <button
      type="button"
      :aria-expanded="expanded"
      :aria-controls="`outcomes-${group.group_id}`"
      :data-group-id="group.group_id"
      @click="toggle"
    >
      <span class="transition-group-card__icon">{{ expanded ? '−' : '+' }}</span>
      <span class="transition-group-card__copy">
        <strong>{{ groupKindLabel(group.kind) }}</strong>
        <small>{{ summaryLabel(group) }}</small>
      </span>
      <span class="transition-group-card__metrics">
        <strong>{{ group.probability.percent.toFixed(2) }}%</strong>
        <small>{{ group.distinct_outcome_count }} 个目标状态</small>
      </span>
    </button>
    <p v-if="loading && expanded" class="transition-group-card__loading">正在归并并加载该分支结果…</p>
  </article>
</template>

<style scoped>
.transition-group-card {
  overflow: hidden;
  border: 1px solid #d7e0da;
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.94);
}

.transition-group-card--expanded {
  border-color: #8eb3a1;
  box-shadow: 0 9px 22px rgba(42, 91, 69, 0.08);
}

.transition-group-card button {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  width: 100%;
  border: 0;
  padding: 13px 14px;
  background: transparent;
  color: inherit;
  text-align: left;
}

.transition-group-card button:hover {
  background: #f5f8f6;
}

.transition-group-card__icon {
  display: grid;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  place-items: center;
  background: #e7f0eb;
  color: #286b52;
  font-weight: 900;
}

.transition-group-card__copy,
.transition-group-card__metrics {
  display: grid;
  gap: 4px;
}

.transition-group-card__copy strong,
.transition-group-card__metrics strong {
  color: #253d32;
  font-size: 13px;
}

.transition-group-card__copy small,
.transition-group-card__metrics small,
.transition-group-card__loading {
  color: #78847d;
  font-size: 10px;
}

.transition-group-card__metrics {
  justify-items: end;
}

.transition-group-card__loading {
  margin: 0;
  border-top: 1px solid #e4ebe6;
  padding: 9px 14px;
}
</style>
