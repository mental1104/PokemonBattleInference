<script setup lang="ts">
import type {
  BattleGraphExplorationResult,
  TransitionGroupResult,
  TransitionOutcomeResult,
} from '../../api/inference';

/** BattlePathExplorer 的只读状态输入。 */
interface BattlePathExplorerProps {
  /** 服务端返回的当前节点、cursor 和折叠 groups。 */
  exploration: BattleGraphExplorationResult;
  /** 当前节点已经按需加载的 group outcomes。 */
  expandedGroups: Readonly<Record<string, TransitionGroupResult>>;
  /** 任一探索请求进行中时禁用重复操作。 */
  loading?: boolean;
  /** 当前探索操作失败时的用户可读消息。 */
  error?: string;
  /** 由固定配置摘要构造的 move ID 到名称映射。 */
  moveNames: Readonly<Record<number, string>>;
}

const props = withDefaults(defineProps<BattlePathExplorerProps>(), {
  loading: false,
  error: '',
});

/** 把用户操作上送给持有 cursor 状态的父视图。 */
defineEmits<{
  expandGroup: [groupId: string];
  advance: [edgeId: number];
  backtrack: [];
  truncate: [depth: number];
}>();

const GROUP_NAMES: Readonly<Record<string, string>> = {
  'action-selection': '行动选择',
  'action-order': '行动顺序',
  'hit-check': '命中判定',
  'damage-distribution': '伤害结果',
  'secondary-effect': '追加效果',
  composite: '组合分支',
};

const OUTCOME_NAMES: Readonly<Record<string, string>> = {
  hit: '命中',
  miss: '未命中',
  flinch: '畏缩',
  prevented: '被阻止',
  success: '成功',
  failure: '失败',
  true: '是',
  false: '否',
};

/**
 * 返回当前分支组的中文标题。
 *
 * @param group 服务端按首个真实分叉机制折叠后的 group。
 * @returns 已知 kind 返回短标题；未知 kind 保留 label key 便于排查。
 */
function groupTitle(group: TransitionGroupResult): string {
  return GROUP_NAMES[group.kind] ?? group.label_key ?? group.kind;
}

/**
 * 把后端概率近似值格式化为紧凑百分比。
 *
 * @param percent 仅用于视觉展示的百分比。
 * @returns 最多四位小数的百分比文本。
 */
function formatPercent(percent: number): string {
  return `${percent.toFixed(4)}%`;
}

/**
 * 返回伤害分支组的区间摘要；非伤害组返回原始路径和正式 outcome 数量。
 *
 * @param group 当前折叠分支组。
 * @returns 用户可读的结构化摘要，不解析自由字符串。
 */
function groupSummary(group: TransitionGroupResult): string {
  const minimum = group.summary.minimum_damage;
  const maximum = group.summary.maximum_damage;
  if (minimum !== null && maximum !== null) {
    return minimum === maximum
      ? `伤害 ${minimum}`
      : `伤害 ${minimum}–${maximum}`;
  }
  return `${group.raw_result_count} 条原始路径 · ${group.distinct_outcome_count} 个结果`;
}

/**
 * 解析 outcome 中最后一个已选招式名称。
 *
 * @param outcome 当前正式 edge 的结构化 outcome。
 * @returns 配置摘要名称优先；没有选招事件时返回空字符串。
 */
function selectedMoveName(outcome: TransitionOutcomeResult): string {
  const moveIds = outcome.label_fields.selected_move_ids;
  const moveId = moveIds[moveIds.length - 1];
  return moveId === undefined ? '' : props.moveNames[moveId] ?? `招式 #${moveId}`;
}

/**
 * 生成 outcome 选择按钮的结构化标签。
 *
 * @param outcome 当前正式 edge 的伤害、随机和标签字段。
 * @returns 伤害结果优先，其次显示随机 outcome，最后稳定回退到目标节点 ID。
 */
function outcomeTitle(outcome: TransitionOutcomeResult): string {
  const move = selectedMoveName(outcome);
  const damage = outcome.damage_rolls[outcome.damage_rolls.length - 1];
  if (damage !== undefined) {
    const prefix = move === '' ? '' : `${move} · `;
    return `${prefix}伤害 ${damage.final_damage} · 实际 HP -${damage.actual_hp_loss}`;
  }

  const randomResult = outcome.random_results[outcome.random_results.length - 1];
  if (randomResult !== undefined) {
    const result =
      OUTCOME_NAMES[randomResult.outcome_id] ?? randomResult.outcome_id;
    return move === '' ? result : `${move} · ${result}`;
  }

  return move === '' ? `前往节点 ${outcome.target_node_id}` : move;
}

/**
 * 返回当前节点一侧的简洁 HP 摘要。
 *
 * @param current 当前 HP。
 * @param maximum 最大 HP。
 * @returns `current / maximum HP` 文本。
 */
function hpText(current: number, maximum: number): string {
  return `${current} / ${maximum} HP`;
}
</script>

<template>
  <section class="battle-path-explorer" aria-label="概率路径探索">
    <header class="battle-path-explorer__header">
      <div>
        <p class="eyebrow">PATH EXPLORER</p>
        <h3>概率路径</h3>
      </div>
      <span class="battle-path-depth">深度 {{ exploration.cursor.steps.length }}</span>
    </header>

    <div class="battle-node-card">
      <div>
        <strong>节点 {{ exploration.node.node_id }}</strong>
        <span>回合 {{ exploration.node.turn_number }} · {{ exploration.node.phase }}</span>
      </div>
      <div class="battle-node-hp">
        <span>快龙 {{ hpText(exploration.node.attacker.current_hp, exploration.node.attacker.max_hp) }}</span>
        <span>玛纽拉 {{ hpText(exploration.node.defender.current_hp, exploration.node.defender.max_hp) }}</span>
      </div>
    </div>

    <div v-if="exploration.cursor.steps.length" class="battle-path-controls">
      <button
        type="button"
        :disabled="loading"
        data-backtrack
        @click="$emit('backtrack')"
      >
        返回上一级
      </button>
      <div class="battle-path-breadcrumbs" aria-label="路径深度">
        <button
          type="button"
          :disabled="loading"
          :class="{ 'battle-path-breadcrumb--root': true }"
          @click="$emit('truncate', 0)"
        >
          根
        </button>
        <button
          v-for="(_, index) in exploration.cursor.steps"
          :key="index"
          type="button"
          :disabled="loading || index + 1 === exploration.cursor.steps.length"
          @click="$emit('truncate', index + 1)"
        >
          {{ index + 1 }}
        </button>
      </div>
    </div>

    <p v-if="error" class="battle-path-explorer__error">{{ error }}</p>
    <p v-if="loading" class="battle-path-explorer__notice">正在读取服务端 cursor…</p>

    <div v-if="exploration.terminal" class="battle-path-terminal">
      <strong>当前路径已结束</strong>
      <span>{{ exploration.node.termination_reason ?? exploration.node.outcome }}</span>
    </div>

    <div v-else class="battle-transition-groups">
      <article
        v-for="group in exploration.transition_groups"
        :key="group.group_id"
        class="battle-transition-group"
      >
        <button
          class="battle-transition-group__summary"
          type="button"
          :disabled="loading"
          :data-group-id="group.group_id"
          @click="$emit('expandGroup', group.group_id)"
        >
          <span>
            <strong>{{ groupTitle(group) }}</strong>
            <small>{{ groupSummary(group) }}</small>
          </span>
          <span>
            {{ group.probability.numerator }} / {{ group.probability.denominator }}
            <small>{{ formatPercent(group.probability.percent) }}</small>
          </span>
        </button>

        <div
          v-if="expandedGroups[group.group_id]"
          class="battle-transition-outcomes"
        >
          <button
            v-for="outcome in expandedGroups[group.group_id].outcomes"
            :key="outcome.edge_id"
            class="battle-transition-outcome"
            type="button"
            :disabled="loading"
            :data-edge-id="outcome.edge_id"
            @click="$emit('advance', outcome.edge_id)"
          >
            <span>
              <strong>{{ outcomeTitle(outcome) }}</strong>
              <small>目标节点 {{ outcome.target_node_id }}</small>
            </span>
            <span class="battle-transition-outcome__probability">
              {{ outcome.probability.numerator }} / {{ outcome.probability.denominator }}
              <small>{{ formatPercent(outcome.probability.percent) }}</small>
            </span>
          </button>
        </div>
      </article>

      <p v-if="exploration.transition_groups.length === 0" class="battle-path-explorer__notice">
        当前节点没有可继续展开的分支。
      </p>
    </div>
  </section>
</template>
