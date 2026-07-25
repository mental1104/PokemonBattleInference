<script setup lang="ts">
import { computed } from 'vue';
import type { JointActionDetailResult, TransitionGroupResult } from '../../api/inference';

const props = defineProps<{
  group: TransitionGroupResult;
  expanded: boolean;
  loading: boolean;
}>();

const emit = defineEmits<{
  toggle: [groupId: string];
}>();

/**
 * 将一侧类型化行动转换为联合行动标题片段。
 *
 * @param action 服务端投影的一侧行动；旧图没有完整选招事件时为 null。
 * @returns 普通招式、挣扎、pass 或兼容分组文案。
 */
function actionLabel(action: JointActionDetailResult | null): string {
  if (action === null) {
    return '未解析行动';
  }
  if (action.action_type === 'move' && action.move_id !== null) {
    return `招式 #${action.move_id}`;
  }
  if (action.action_type === 'struggle') {
    return '挣扎';
  }
  if (action.action_type === 'pass') {
    return '跳过行动';
  }
  return action.move_id === null ? action.action_type : `${action.action_type} #${action.move_id}`;
}

const title = computed(() => {
  if (props.group.attacker_action !== null && props.group.defender_action !== null) {
    return `攻击方 ${actionLabel(props.group.attacker_action)} × 防守方 ${actionLabel(props.group.defender_action)}`;
  }
  const labels: Record<string, string> = {
    'action-selection': '行动选择',
    'action-order': '行动顺序',
    'hit-check': '命中判定',
    'damage-distribution': '伤害随机结果',
    'secondary-effect': '追加效果',
    composite: '组合结果',
  };
  return labels[props.group.kind] ?? props.group.kind;
});

/** 触发父组件按需加载或收起当前联合行动。 */
function toggle(): void {
  emit('toggle', props.group.group_id);
}
</script>

<template>
  <article
    class="transition-group-card"
    :class="{ 'transition-group-card--expanded': expanded }"
    :data-group-id="group.group_id"
  >
    <button class="transition-group-card__toggle" type="button" @click="toggle">
      <span class="transition-group-card__heading">
        <strong>{{ title }}</strong>
        <span>{{ group.selection_probability.percent.toFixed(2) }}% 选择概率</span>
      </span>
      <span class="transition-group-card__counts">
        {{ group.raw_result_count }} 条离散随机路径 ·
        {{ group.distinct_outcome_count }} 个目标状态
      </span>
      <span class="transition-group-card__chevron" aria-hidden="true">
        {{ expanded ? '−' : '+' }}
      </span>
    </button>
    <p v-if="loading" class="transition-group-card__loading">正在加载紧凑随机结果…</p>
    <slot v-else-if="expanded" />
  </article>
</template>

<style scoped>
.transition-group-card {
  border: 1px solid #dce5f2;
  border-radius: 14px;
  background: #fff;
  overflow: hidden;
}

.transition-group-card--expanded {
  border-color: #9eb8dd;
  box-shadow: 0 10px 24px rgb(38 74 124 / 10%);
}

.transition-group-card__toggle {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 12px;
  align-items: center;
  padding: 14px 16px;
  border: 0;
  background: transparent;
  color: #1f2d3d;
  text-align: left;
  cursor: pointer;
}

.transition-group-card__heading {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.transition-group-card__heading strong {
  overflow-wrap: anywhere;
}

.transition-group-card__heading span,
.transition-group-card__counts,
.transition-group-card__loading {
  color: #607086;
  font-size: 13px;
}

.transition-group-card__chevron {
  font-size: 22px;
  color: #496b9b;
}

.transition-group-card__loading {
  margin: 0;
  padding: 0 16px 14px;
}

@media (max-width: 720px) {
  .transition-group-card__toggle {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .transition-group-card__counts {
    grid-column: 1 / -1;
  }
}
</style>
