<script setup lang="ts">
import { computed } from 'vue';
import type { BattleNodeDetailResult, ProbabilityResult } from '../../api/inference';

interface Props {
  node: BattleNodeDetailResult;
  cumulativeProbability: ProbabilityResult;
}

const props = defineProps<Props>();

const outcomeLabel = computed(() => {
  const labels: Record<string, string> = {
    'non-terminal': '战斗进行中',
    'attacker-win': '快龙获胜',
    'defender-win': '玛纽拉获胜',
    draw: '平局',
  };
  return labels[props.node.outcome] ?? props.node.outcome.replaceAll('_', ' ');
});

/**
 * 把后端概率百分比格式化为紧凑展示文本。
 *
 * @param probability 精确概率 DTO，其中 percent 仅用于界面展示。
 * @returns 最多保留四位小数的百分比文本。
 */
function formatProbability(probability: ProbabilityResult): string {
  const digits = probability.percent > 0 && probability.percent < 0.01 ? 4 : 2;
  return `${probability.percent.toFixed(digits)}%`;
}

/**
 * 把 phase identifier 转为适合节点卡片的短标签。
 *
 * @param phase 当前状态图节点阶段 identifier。
 * @returns 使用空格分隔的可读文本。
 */
function phaseLabel(phase: string): string {
  return phase.replaceAll('-', ' ').replaceAll('_', ' ');
}
</script>

<template>
  <article class="battle-graph-node" data-testid="battle-current-node">
    <header>
      <div>
        <p>当前节点 · #{{ node.node_id }}</p>
        <h3>Turn {{ node.turn_number }} · {{ phaseLabel(node.phase) }}</h3>
      </div>
      <span :class="{ 'battle-graph-node__status--terminal': node.terminal }">
        {{ outcomeLabel }}
      </span>
    </header>

    <div class="battle-graph-node__combatants">
      <section>
        <small>ATTACKER</small>
        <strong>{{ node.attacker.name }}</strong>
        <div class="battle-graph-node__hp-line">
          <span>HP {{ node.attacker.current_hp }} / {{ node.attacker.max_hp }}</span>
          <i :style="{ width: `${(node.attacker.current_hp / node.attacker.max_hp) * 100}%` }" />
        </div>
        <p>{{ node.attacker.ability }} · {{ node.attacker.item }}</p>
      </section>
      <section>
        <small>DEFENDER</small>
        <strong>{{ node.defender.name }}</strong>
        <div class="battle-graph-node__hp-line battle-graph-node__hp-line--defender">
          <span>HP {{ node.defender.current_hp }} / {{ node.defender.max_hp }}</span>
          <i :style="{ width: `${(node.defender.current_hp / node.defender.max_hp) * 100}%` }" />
        </div>
        <p>{{ node.defender.ability }} · {{ node.defender.item }}</p>
      </section>
    </div>

    <footer>
      <span>当前路径概率</span>
      <strong>{{ formatProbability(cumulativeProbability) }}</strong>
      <small>{{ cumulativeProbability.numerator }} / {{ cumulativeProbability.denominator }}</small>
    </footer>

    <p v-if="node.terminal" class="battle-graph-node__terminal-note">
      {{ node.termination_reason ?? '该路径已到达终局，不再提供后续分支。' }}
    </p>
  </article>
</template>

<style scoped>
.battle-graph-node {
  border: 1px solid #cfdbd3;
  border-radius: 16px;
  padding: 18px;
  background: linear-gradient(145deg, #ffffff, #f3f7f4);
  box-shadow: 0 14px 32px rgba(37, 65, 52, 0.07);
}

.battle-graph-node header,
.battle-graph-node footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.battle-graph-node header p,
.battle-graph-node header h3,
.battle-graph-node__combatants p,
.battle-graph-node__terminal-note {
  margin: 0;
}

.battle-graph-node header p,
.battle-graph-node__combatants small,
.battle-graph-node footer span,
.battle-graph-node footer small {
  color: #7a8780;
  font-size: 11px;
}

.battle-graph-node header h3 {
  margin-top: 4px;
  color: #183d31;
  font-size: 18px;
  text-transform: capitalize;
}

.battle-graph-node header > span {
  border-radius: 999px;
  padding: 6px 10px;
  background: #e9f4ee;
  color: #236447;
  font-size: 11px;
  font-weight: 800;
}

.battle-graph-node header > span.battle-graph-node__status--terminal {
  background: #f8e8e9;
  color: #9b3038;
}

.battle-graph-node__combatants {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: 16px;
}

.battle-graph-node__combatants section {
  min-width: 0;
  border-radius: 12px;
  padding: 13px;
  background: rgba(255, 255, 255, 0.86);
}

.battle-graph-node__combatants strong {
  display: block;
  overflow: hidden;
  margin-top: 3px;
  color: #263d32;
  text-overflow: ellipsis;
  text-transform: capitalize;
  white-space: nowrap;
}

.battle-graph-node__combatants p {
  overflow: hidden;
  margin-top: 8px;
  color: #78847d;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.battle-graph-node__hp-line {
  position: relative;
  overflow: hidden;
  height: 22px;
  margin-top: 8px;
  border-radius: 7px;
  background: #e8efea;
}

.battle-graph-node__hp-line span {
  position: relative;
  z-index: 2;
  display: grid;
  height: 100%;
  place-items: center;
  color: #183d31;
  font-size: 10px;
  font-weight: 800;
}

.battle-graph-node__hp-line i {
  position: absolute;
  inset: 0 auto 0 0;
  z-index: 1;
  background: rgba(63, 150, 105, 0.28);
}

.battle-graph-node__hp-line--defender i {
  background: rgba(190, 66, 77, 0.22);
}

.battle-graph-node footer {
  margin-top: 14px;
  border-top: 1px solid #e1e8e3;
  padding-top: 12px;
}

.battle-graph-node footer strong {
  margin-left: auto;
  color: #183d31;
  font-size: 18px;
}

.battle-graph-node__terminal-note {
  margin-top: 12px;
  border-radius: 10px;
  padding: 10px 12px;
  background: #fff1f2;
  color: #8d3a42;
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 600px) {
  .battle-graph-node__combatants {
    grid-template-columns: 1fr;
  }
}
</style>
