<script setup lang="ts">
import type {
  ActionResolutionDetailResult,
  CompactRandomResultResult,
  TransitionOutcomeResult,
} from '../../api/inference';

const props = defineProps<{
  outcomes: TransitionOutcomeResult[];
}>();

const emit = defineEmits<{
  select: [outcome: TransitionOutcomeResult];
}>();

/** 返回行动侧别的简短中文标签。 */
function sideLabel(side: string): string {
  return side === 'attacker' ? '攻' : side === 'defender' ? '守' : side;
}

/** 将一侧行动执行状态转换为紧凑可读标签。 */
function resolutionLabel(resolution: ActionResolutionDetailResult): string {
  const move = resolution.move_id === null ? resolution.action_type : `#${resolution.move_id}`;
  const order = resolution.order_position === null ? '' : `${resolution.order_position}.`;
  if (resolution.status === 'cancelled') {
    return `${order}${sideLabel(resolution.side)} ${move} 取消：${resolution.reason ?? '未执行'}`;
  }
  if (resolution.status === 'blocked') {
    return `${order}${sideLabel(resolution.side)} ${move} 阻断：${resolution.reason ?? '未知原因'}`;
  }
  if (resolution.status === 'passed') {
    return `${order}${sideLabel(resolution.side)} 跳过`;
  }
  const hit = resolution.hit === null ? '' : resolution.hit ? ' 命中' : ' 未命中';
  return `${order}${sideLabel(resolution.side)} ${move}${hit}`;
}

/** 保留离散值逐项展示，不把 16 档误写成连续范围。 */
function discreteValues(values: number[], suffix = ''): string {
  return [...new Set(values)].sort((left, right) => left - right).map((value) => `${value}${suffix}`).join(' / ');
}

/** 为一项紧凑随机结果生成不依赖自由文本事件解析的状态标签。 */
function statusLabels(result: CompactRandomResultResult): string[] {
  return result.status_effects.map((effect) => {
    const target = effect.target_side === null ? '' : `${sideLabel(effect.target_side)} `;
    const source = effect.source_identifier ?? '状态';
    return `${target}${source}${effect.result === 'applied' ? '生效' : '被阻止'}`;
  });
}

/** 沿正式状态图 edge 前进。 */
function selectOutcome(outcome: TransitionOutcomeResult): void {
  emit('select', outcome);
}
</script>

<template>
  <div class="transition-outcome-list" data-testid="transition-outcome-list">
    <button
      v-for="outcome in props.outcomes"
      :key="outcome.edge_id"
      class="transition-outcome-list__item"
      type="button"
      :data-edge-id="outcome.edge_id"
      @click="selectOutcome(outcome)"
    >
      <span class="transition-outcome-list__topline">
        <strong>进入节点 #{{ outcome.target_node_id }}</strong>
        <span>{{ outcome.probability.percent.toFixed(2) }}% 条件概率</span>
      </span>
      <span class="transition-outcome-list__joint">
        联合概率 {{ outcome.joint_probability.percent.toFixed(2) }}% ·
        路径累计 {{ outcome.cumulative_probability.percent.toFixed(2) }}%
      </span>
      <span
        v-for="(result, resultIndex) in outcome.compact_results"
        :key="`${outcome.edge_id}-${resultIndex}`"
        class="transition-outcome-list__result"
      >
        <span class="transition-outcome-list__chips">
          <span
            v-for="resolution in result.action_resolutions"
            :key="`${resolution.side}-${resolution.order_position}-${resolution.move_id}`"
            class="transition-outcome-list__chip"
            :class="{
              'transition-outcome-list__chip--warning':
                resolution.status === 'cancelled' || resolution.status === 'blocked',
            }"
          >
            {{ resolutionLabel(resolution) }}
          </span>
          <span class="transition-outcome-list__chip">顺序依据 {{ result.order_reason }}</span>
          <span v-if="result.critical_hit !== null" class="transition-outcome-list__chip">
            {{ result.critical_hit ? '暴击' : '未暴击' }}
          </span>
          <span
            v-for="label in statusLabels(result)"
            :key="label"
            class="transition-outcome-list__chip"
          >
            {{ label }}
          </span>
        </span>
        <span v-if="result.raw_roll_values.length > 0" class="transition-outcome-list__values">
          原始 roll：{{ discreteValues(result.raw_roll_values) }}
        </span>
        <span v-if="result.final_damage_values.length > 0" class="transition-outcome-list__values">
          最终伤害：{{ discreteValues(result.final_damage_values) }}
        </span>
        <span v-if="result.actual_hp_losses.length > 0" class="transition-outcome-list__values">
          实际 HP 损失：{{ discreteValues(result.actual_hp_losses) }}
        </span>
      </span>
    </button>
  </div>
</template>

<style scoped>
.transition-outcome-list {
  display: grid;
  gap: 8px;
  max-height: 420px;
  overflow: auto;
  padding: 0 12px 12px;
}

.transition-outcome-list__item {
  display: grid;
  gap: 6px;
  padding: 11px 12px;
  border: 1px solid #e1e7f0;
  border-radius: 10px;
  background: #f8fafc;
  color: #263548;
  text-align: left;
  cursor: pointer;
}

.transition-outcome-list__item:hover {
  border-color: #8da9cf;
  background: #f1f6fc;
}

.transition-outcome-list__topline {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.transition-outcome-list__topline span,
.transition-outcome-list__joint,
.transition-outcome-list__values {
  color: #607086;
  font-size: 12px;
}

.transition-outcome-list__result {
  display: grid;
  gap: 5px;
  padding-top: 5px;
  border-top: 1px dashed #d8e1ed;
}

.transition-outcome-list__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.transition-outcome-list__chip {
  padding: 2px 7px;
  border-radius: 999px;
  background: #e7eff9;
  color: #34577f;
  font-size: 11px;
}

.transition-outcome-list__chip--warning {
  background: #fff0d8;
  color: #8b5813;
}

.transition-outcome-list__values {
  overflow-wrap: anywhere;
}
</style>
