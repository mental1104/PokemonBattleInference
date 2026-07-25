<script setup lang="ts">
import { computed, ref } from 'vue';
import { normalizeCandidateMoveIds } from '../../domain/configurationBudget';
import type {
  CandidateMoveOption,
  MechanismSupportStatus,
} from '../../types/battleConfigurationSpace';
import './CandidateMovePoolSelector.css';

const props = defineProps<{
  side: 'attacker' | 'defender';
  title: string;
  moves: readonly CandidateMoveOption[];
  modelValue: readonly number[];
  loading: boolean;
  disabled: boolean;
  remainingGlobalSlots: number;
}>();

const emit = defineEmits<{
  'update:modelValue': [moveIds: number[]];
}>();

const query = ref('');

const normalizedQuery = computed(() => query.value.trim().toLocaleLowerCase());
const selectedMoveIds = computed(() => new Set(props.modelValue));
const selectedMoves = computed(() =>
  props.modelValue
    .map((moveId) => props.moves.find((move) => move.move_id === moveId))
    .filter((move): move is CandidateMoveOption => move !== undefined),
);
const visibleMoves = computed(() => {
  if (normalizedQuery.value === '') return props.moves;
  return props.moves.filter((move) =>
    move.identifier.toLocaleLowerCase().includes(normalizedQuery.value) ||
    move.display_name.toLocaleLowerCase().includes(normalizedQuery.value) ||
    move.type_name.toLocaleLowerCase().includes(normalizedQuery.value),
  );
});

/**
 * 将机制支持状态转换为不依赖颜色的可读标签。
 *
 * @param status 服务端或 mock adapter 返回的稳定支持枚举。
 * @returns 直接显示在候选卡片上的大写状态标签。
 */
function supportStatusLabel(status: MechanismSupportStatus): string {
  return status.toUpperCase();
}

/**
 * 判断候选卡片是否应阻止新增选择。
 *
 * 已选项始终允许取消；未支持项、未选择 Pokémon、全局 20 招预算耗尽时禁止新增。
 *
 * @param move 当前候选招式。
 * @returns 当前点击是否只能作为禁用展示。
 */
function isSelectionDisabled(move: CandidateMoveOption): boolean {
  if (selectedMoveIds.value.has(move.move_id)) return false;
  return (
    props.disabled ||
    !move.admission.selectable ||
    props.remainingGlobalSlots <= 0
  );
}

/**
 * 切换一条可执行候选，并在向父层发送前规范化 move_id 顺序。
 *
 * @param move 用户点击的候选招式。
 */
function toggleMove(move: CandidateMoveOption): void {
  const selected = selectedMoveIds.value.has(move.move_id);
  if (!selected && isSelectionDisabled(move)) return;

  const next = selected
    ? props.modelValue.filter((moveId) => moveId !== move.move_id)
    : [...props.modelValue, move.move_id];
  emit('update:modelValue', normalizeCandidateMoveIds(next));
}

/**
 * 从已选摘要中移除一条候选。
 *
 * @param moveId 需要移除的正整数招式 ID。
 */
function removeMove(moveId: number): void {
  emit(
    'update:modelValue',
    normalizeCandidateMoveIds(
      props.modelValue.filter((selectedId) => selectedId !== moveId),
    ),
  );
}
</script>

<template>
  <section class="candidate-pool panel-block" :data-side="side">
    <div class="candidate-pool__heading">
      <div>
        <div class="field-title">{{ title }}</div>
        <p>仅 SUPPORTED / NO_EFFECT 候选可以进入精确推演；选择顺序不会进入配置身份。</p>
      </div>
      <strong :data-testid="`${side}-selected-count`">{{ modelValue.length }} 已选</strong>
    </div>

    <div v-if="selectedMoves.length" class="candidate-pool__selected" aria-label="已选候选招式">
      <button
        v-for="move in selectedMoves"
        :key="move.move_id"
        type="button"
        :data-testid="`${side}-selected-move`"
        @click="removeMove(move.move_id)"
      >
        <span>{{ move.display_name }}</span>
        <small>移除</small>
      </button>
    </div>

    <input
      v-model="query"
      class="search-input"
      type="search"
      :data-testid="`${side}-move-search`"
      :disabled="disabled"
      placeholder="筛选名称、identifier 或属性"
    />

    <div v-if="loading" class="candidate-pool__message muted">候选池加载中</div>
    <div v-else-if="disabled" class="candidate-pool__message muted">请先选择 Pokémon</div>
    <div v-else-if="visibleMoves.length === 0" class="candidate-pool__message muted">没有匹配的候选招式</div>
    <div v-else class="candidate-pool__list" role="list">
      <button
        v-for="move in visibleMoves"
        :key="move.move_id"
        type="button"
        class="candidate-move"
        :class="{
          'candidate-move--selected': selectedMoveIds.has(move.move_id),
          'candidate-move--blocked': isSelectionDisabled(move),
        }"
        :data-testid="`${side}-move-option`"
        :data-move-id="move.move_id"
        :data-support="move.admission.status"
        :aria-pressed="selectedMoveIds.has(move.move_id)"
        :aria-disabled="isSelectionDisabled(move)"
        @click="toggleMove(move)"
      >
        <span class="candidate-move__main">
          <strong>{{ move.display_name }}</strong>
          <small>{{ move.identifier }} · {{ move.type_name }}</small>
        </span>
        <span
          class="candidate-move__status"
          :data-status="move.admission.status"
        >
          {{ supportStatusLabel(move.admission.status) }}
        </span>
        <span v-if="move.admission.disabled_reason" class="candidate-move__reason">
          {{ move.admission.disabled_reason }}
          <template v-if="move.admission.missing_mechanism_identifiers.length">
            缺失：{{ move.admission.missing_mechanism_identifiers.join('、') }}
          </template>
        </span>
      </button>
    </div>

    <p v-if="remainingGlobalSlots <= 0" class="candidate-pool__limit" role="status">
      双方候选总数已达到 20；可先移除另一侧候选再继续选择。
    </p>
  </section>
</template>
