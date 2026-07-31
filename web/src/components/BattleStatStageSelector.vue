<script setup lang="ts">
import type { BattleStatStageField, BattleStatStages } from '../api/calculator';

interface StatStageFieldOption {
  /** 提交给后端的稳定能力等级字段。 */
  field: BattleStatStageField;
  /** 面向用户展示的中文短标签。 */
  label: string;
}

const props = defineProps<{
  /** 当前七项能力等级快照，每一项必须位于 -6 到 +6。 */
  modelValue: BattleStatStages;
  /** 是否禁止修改；未选择 Pokémon 时由上层控制。 */
  disabled?: boolean;
}>();

const emit = defineEmits<{
  /** 用户修改任一字段后，返回保留其他字段的新能力等级快照。 */
  'update:modelValue': [value: BattleStatStages];
}>();

const STAGE_FIELDS: readonly StatStageFieldOption[] = [
  { field: 'attack', label: '攻击' },
  { field: 'defense', label: '防御' },
  { field: 'special_attack', label: '特攻' },
  { field: 'special_defense', label: '特防' },
  { field: 'speed', label: '速度' },
  { field: 'evasion', label: '回避' },
  { field: 'accuracy', label: '命中' },
];

const STAGE_VALUES: readonly number[] = [-6, -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6];

/**
 * 把数值格式化为界面中的能力等级文本。
 *
 * @param value -6 到 +6 的能力等级；正数显式带加号，零保持为 0。
 * @returns 可直接展示在 option 中的短文本。
 */
function formatStageValue(value: number): string {
  return value > 0 ? `+${value}` : String(value);
}

/**
 * 更新一个能力等级，同时保留同侧 Pokémon 的其他六项选择。
 *
 * @param field 被用户修改的稳定字段名。
 * @param event 原生 select change 事件，其 value 必须来自固定的 -6 到 +6 选项。
 */
function updateStage(field: BattleStatStageField, event: Event): void {
  const select = event.target as HTMLSelectElement;
  emit('update:modelValue', {
    ...props.modelValue,
    [field]: Number(select.value),
  });
}
</script>

<template>
  <fieldset class="battle-stat-stage-selector" data-testid="battle-stat-stage-selector" :disabled="disabled">
    <legend>战斗能力</legend>
    <div class="battle-stat-stage-selector__grid">
      <label
        v-for="option in STAGE_FIELDS"
        :key="option.field"
        class="battle-stat-stage-selector__field"
      >
        <span>{{ option.label }}</span>
        <select
          :aria-label="`${option.label}能力等级`"
          :data-stat-stage="option.field"
          :value="modelValue[option.field]"
          @change="updateStage(option.field, $event)"
        >
          <option v-for="value in STAGE_VALUES" :key="value" :value="value">
            {{ formatStageValue(value) }}
          </option>
        </select>
      </label>
    </div>
  </fieldset>
</template>

<style scoped>
.battle-stat-stage-selector {
  min-width: 0;
  margin: 0;
  border: 1px solid #dce4d8;
  border-radius: 7px;
  padding: 8px 10px 10px;
  background: #fbfcfa;
}

.battle-stat-stage-selector legend {
  padding: 0 5px;
  color: #325545;
  font-size: 12px;
  font-weight: 800;
}

.battle-stat-stage-selector__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 10px;
}

.battle-stat-stage-selector__field {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 50px;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: #435249;
  font-size: 12px;
}

.battle-stat-stage-selector__field select {
  width: 100%;
  height: 28px;
  border: 1px solid #bdc9c0;
  border-radius: 5px;
  padding: 0 4px;
  background: #fff;
  color: #17201b;
  font: inherit;
}

@media (max-width: 420px) {
  .battle-stat-stage-selector__grid {
    grid-template-columns: 1fr;
  }
}
</style>
