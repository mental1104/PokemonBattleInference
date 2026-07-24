<script setup lang="ts">
import type { WinningPathPrefixNodeResult } from '../../api/winningPaths';

/** 行动前缀树递归节点的只读输入。 */
interface Props {
  /** 后端已经按当前页 Top-K 聚合的前缀树节点。 */
  node: WinningPathPrefixNodeResult;
  /** 招式 ID 到用户可读名称的映射。 */
  moveNames: Record<number, string>;
  /** 是否为不对应实际行动的虚拟根节点。 */
  root?: boolean;
}

const props = withDefaults(defineProps<Props>(), { root: false });

/**
 * 把可空招式 ID 转换为稳定短标签。
 *
 * @param moveId 当前行动一侧的招式 ID；缺失表示事件尚未携带明确选招。
 * @returns 优先使用招式名、其次使用 ID、最后返回未记录。
 */
function moveLabel(moveId: number | null): string {
  if (moveId === null) {
    return '未记录';
  }
  return props.moveNames[moveId] ?? `招式 #${moveId}`;
}

/**
 * 格式化前缀节点聚合概率。
 *
 * @param percent 后端返回的近似百分比。
 * @returns 保留四位小数的展示文本。
 */
function formatPercent(percent: number): string {
  return `${percent.toFixed(4)}%`;
}
</script>

<template>
  <div class="winning-prefix-node" :class="{ 'winning-prefix-node--root': root }">
    <div v-if="!root && node.action" class="winning-prefix-node__card">
      <div>
        <span>Turn {{ node.action.turn_number }}</span>
        <strong>
          {{ moveLabel(node.action.attacker_move_id) }}
          <i>×</i>
          {{ moveLabel(node.action.defender_move_id) }}
        </strong>
      </div>
      <small>
        {{ formatPercent(node.probability.percent) }}
        · {{ node.raw_path_count }} 条路径
        <template v-if="node.action.ambiguous">· 含 {{ node.action.alternatives.length }} 个候选联合行动</template>
      </small>
      <em v-if="node.terminal_path_keys.length">终局 × {{ node.terminal_path_keys.length }}</em>
    </div>

    <div v-if="node.children.length" class="winning-prefix-node__children">
      <WinningPathPrefixTree
        v-for="child in node.children"
        :key="child.prefix_key"
        :node="child"
        :move-names="moveNames"
      />
    </div>
  </div>
</template>

<style scoped>
.winning-prefix-node {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: max-content;
}

.winning-prefix-node--root {
  align-items: stretch;
}

.winning-prefix-node__card {
  position: relative;
  display: grid;
  gap: 7px;
  min-width: 190px;
  max-width: 250px;
  border: 1px solid #d8e1dc;
  border-radius: 13px;
  padding: 12px;
  background: #fff;
  box-shadow: 0 8px 20px rgba(39, 65, 53, 0.06);
}

.winning-prefix-node__card::after {
  position: absolute;
  top: 50%;
  right: -15px;
  width: 14px;
  border-top: 1px solid #aabbb2;
  content: '';
}

.winning-prefix-node__card div {
  display: grid;
  gap: 3px;
}

.winning-prefix-node__card span,
.winning-prefix-node__card small,
.winning-prefix-node__card em {
  color: #748078;
  font-size: 10px;
  font-style: normal;
}

.winning-prefix-node__card strong {
  color: #173d31;
  font-size: 13px;
}

.winning-prefix-node__card i {
  color: #9c4d55;
  font-style: normal;
}

.winning-prefix-node__card em {
  justify-self: start;
  border-radius: 999px;
  padding: 2px 7px;
  background: #eef6f1;
  color: #277252;
  font-weight: 800;
}

.winning-prefix-node__children {
  display: grid;
  gap: 10px;
  border-left: 1px solid #aabbb2;
  padding-left: 14px;
}
</style>
