<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import {
  advanceBattleExploration,
  exploreBattleGraph,
  loadBattleTransitionGroupOutcomes,
  type BattleExplorationResult,
  type BattleGraphExplorationResult,
  type JointActionDetailResult,
  type TransitionOutcomeResult,
} from '../../api/inference';
import { expandFixedBattleSnapshot } from '../../api/fixedBattle';
import type { BattleReportPresenterContext } from '../../presenters/battleEventPresenter';
import type { FixedBattleSummaryRequest } from '../../types/fixedBattle';
import BattleGraphNode from './BattleGraphNode.vue';
import BattleReportPanel from './BattleReportPanel.vue';

/** 大屏树状探索器的只读输入。 */
interface Props {
  /** 首次固定推演返回的完整图句柄；snapshot mode 下为 null。 */
  handle?: BattleExplorationResult | null;
  /** 固定配置快照展开请求；提供时不要求完整图句柄。 */
  snapshotRequest?: FixedBattleSummaryRequest | null;
  /** 战报 presenter 需要的双方名称、HP 与招式名称上下文。 */
  context: BattleReportPresenterContext;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  close: [];
  rerun: [];
}>();

const columns = ref<BattleGraphExplorationResult[]>([]);
const outcomes = ref<TransitionOutcomeResult[]>([]);
const expandedGroupId = ref<string | null>(null);
const expandedPrimaryBucketKey = ref<string | null>(null);
const expandedSecondaryBucketKey = ref<string | null>(null);
const outcomeViewMode = ref<'grouped' | 'raw'>('grouped');
const visibleBucketLimit = ref(12);
const selectedAttackerMoveId = ref<number | null>(null);
const selectedDefenderMoveId = ref<number | null>(null);
const loading = ref(false);
const outcomesLoading = ref(false);
const error = ref<string | null>(null);
const canvasViewport = ref<HTMLElement | null>(null);
const canvasContent = ref<HTMLElement | null>(null);
let lifecycleVersion = 0;

const current = computed(() => columns.value[columns.value.length - 1] ?? null);
const currentDepth = computed(() => Math.max(0, columns.value.length - 1));
const currentReport = computed(() => current.value?.battle_report ?? null);
const currentTransitionGroups = computed(() => current.value?.transition_groups ?? []);
const snapshotMode = computed(() => props.snapshotRequest !== null && props.snapshotRequest !== undefined);
const attackerMoveOptions = computed(() => moveOptions(currentTransitionGroups.value, 'attacker'));
const defenderMoveOptions = computed(() => moveOptions(currentTransitionGroups.value, 'defender'));
const filteredTransitionGroups = computed(() =>
  currentTransitionGroups.value.filter((group) => {
    const attackerMoveId = groupMoveId(group, 'attacker');
    const defenderMoveId = groupMoveId(group, 'defender');
    return (
      (selectedAttackerMoveId.value === null || selectedAttackerMoveId.value === attackerMoveId)
      && (selectedDefenderMoveId.value === null || selectedDefenderMoveId.value === defenderMoveId)
    );
  }),
);
const outcomeBuckets = computed(() => activeOutcomeGroupingStrategy.build(outcomes.value));
const visibleOutcomeBuckets = computed(() => outcomeBuckets.value.slice(0, visibleBucketLimit.value));

/** 左侧树画布的视角状态。 */
interface CanvasViewportTransform {
  /** 内容层相对 viewport 左上角的横向偏移，单位 px。 */
  x: number;
  /** 内容层相对 viewport 左上角的纵向偏移，单位 px。 */
  y: number;
  /** 内容层缩放倍率。 */
  scale: number;
}

/** 拖拽平移时保留的指针起点和原始视角。 */
interface CanvasPanSession {
  /** 正在拖拽的 pointerId。 */
  pointerId: number;
  /** pointerdown 时的 clientX。 */
  startClientX: number;
  /** pointerdown 时的 clientY。 */
  startClientY: number;
  /** pointerdown 时的原始 x 偏移。 */
  originX: number;
  /** pointerdown 时的原始 y 偏移。 */
  originY: number;
}

const MIN_CANVAS_SCALE = 0.55;
const MAX_CANVAS_SCALE = 1.4;
const canvasTransform = ref<CanvasViewportTransform>({ x: 0, y: 0, scale: 1 });
const canvasPanSession = ref<CanvasPanSession | null>(null);
const canvasTransformStyle = computed(() => ({
  transform: `translate(${canvasTransform.value.x}px, ${canvasTransform.value.y}px) scale(${canvasTransform.value.scale})`,
}));

/** 大屏中用于降低分支噪音的 outcome 聚合桶。 */
interface OutcomeBucket {
  /** 桶的稳定 key，由结果语义与伤害区间组合而成。 */
  key: string;
  /** 用户可读的聚合标题。 */
  title: string;
  /** 聚合条件的补充描述，例如概率、伤害范围和终点数量。 */
  description: string;
  /** 桶内保留的真实 edge；用户最终仍从这里选择唯一通路。 */
  outcomes: TransitionOutcomeResult[];
  /** 桶内条件概率百分比的展示用近似合计。 */
  probabilityPercent: number;
  /** 桶内所有目标节点的数量，用于提示聚合压缩效果。 */
  targetCount: number;
  /** 下一级聚合桶；为空表示已经可以展示真实 edge。 */
  children: OutcomeBucket[];
}

/** 结果簇策略的统一接口，后续可替换为规则驱动或服务端下发策略。 */
interface OutcomeGroupingStrategy {
  /** 策略稳定 ID，用于未来接入策略选择器或持久化用户偏好。 */
  id: string;
  /** 策略展示名称。 */
  label: string;
  /**
   * 把正式 outcomes 组织成前端可导航的层级桶。
   *
   * @param sourceOutcomes 后端返回的真实 edge 列表。
   * @returns 可分层展开的结果簇。
   */
  build(sourceOutcomes: TransitionOutcomeResult[]): OutcomeBucket[];
}

type BattleSideKey = 'attacker' | 'defender';

const activeOutcomeGroupingStrategy: OutcomeGroupingStrategy = {
  id: 'side-damage-bisect-v1',
  label: '按双方低/高伤害',
  build: buildSideDamageOutcomeBuckets,
};

/**
 * 把后端概率对象格式化为百分比文本。
 *
 * @param percent 后端返回的百分比近似值。
 * @returns 保留两位小数的百分比字符串。
 */
function percentLabel(percent: number): string {
  return `${percent.toFixed(2)}%`;
}

/**
 * 把联合行动一侧转换为紧凑树节点标题。
 *
 * @param action 后端投影的一侧行动；旧图或聚合组可能为 null。
 * @returns 优先展示招式 ID，否则展示行动类型。
 */
function actionLabel(action: JointActionDetailResult | null): string {
  if (action === null) {
    return '未解析';
  }
  if (action.action_type === 'move' && action.move_id !== null) {
    return `${moveDisplayName(action.move_id)} #${action.move_id}`;
  }
  return action.move_id === null ? action.action_type : `${action.action_type} #${action.move_id}`;
}

/** 当前节点技能筛选器的一项。 */
interface MoveFilterOption {
  /** 技能 ID。 */
  moveId: number;
  /** 用户可读技能名称。 */
  label: string;
  /** 该技能参与的 transition group 数量。 */
  count: number;
}

/**
 * 根据当前节点 transition group 汇总某一侧可筛选技能。
 *
 * @param groups 当前节点的联合行动分支组。
 * @param side 需要汇总的行动侧。
 * @returns 按技能 ID 升序排列的筛选项；非 move 行动排在最后。
 */
function moveOptions(
  groups: BattleGraphExplorationResult['transition_groups'],
  side: BattleSideKey,
): MoveFilterOption[] {
  const counts = new Map<number, number>();
  for (const group of groups) {
    const moveId = groupMoveId(group, side);
    if (moveId === null) {
      continue;
    }
    counts.set(moveId, (counts.get(moveId) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort(([left], [right]) => left - right)
    .map(([moveId, count]) => ({
      moveId,
      count,
      label: moveDisplayName(moveId),
    }));
}

/**
 * 读取 transition group 中某一侧的 move ID。
 *
 * @param group 当前节点的一组联合行动分支。
 * @param side 需要读取的行动侧。
 * @returns move 行动返回 move ID；非 move 或未解析行动返回 null。
 */
function groupMoveId(
  group: BattleGraphExplorationResult['transition_groups'][number],
  side: BattleSideKey,
): number | null {
  const action = side === 'attacker' ? group.attacker_action : group.defender_action;
  return action?.action_type === 'move' ? action.move_id : null;
}

/**
 * 返回技能 ID 的展示名称。
 *
 * @param moveId PokeAPI move ID。
 * @returns 当前任务上下文中的技能名；缺失时返回稳定 ID 文本。
 */
function moveDisplayName(moveId: number): string {
  return props.context.moveNames[moveId] ?? `招式 #${moveId}`;
}

/**
 * 返回分支组在大屏里的短标题。
 *
 * @param group 当前节点的一组可展开 transition group。
 * @returns 可直接显示在横向树中的行动或随机类型摘要。
 */
function groupTitle(group: BattleGraphExplorationResult['transition_groups'][number]): string {
  if (group.attacker_action !== null || group.defender_action !== null) {
    return `攻 ${actionLabel(group.attacker_action)} × 守 ${actionLabel(group.defender_action)}`;
  }
  return group.kind.replaceAll('-', ' ');
}

/**
 * 返回行动侧别的中文短标签，供聚合 key 和按钮文案复用。
 *
 * @param side 服务端返回的行动侧别。
 * @returns 攻、防或原始 side 字符串。
 */
function sideLabel(side: string): string {
  return side === 'attacker' ? '攻' : side === 'defender' ? '守' : side;
}

/**
 * 把数值数组去重并升序排列。
 *
 * @param values 可能包含重复 roll、伤害或 HP 损失的数值集合。
 * @returns 新的升序去重数组。
 */
function uniqueSortedNumbers(values: number[]): number[] {
  return [...new Set(values)].sort((left, right) => left - right);
}

/**
 * 把离散数值压成适合桶标题的范围文本。
 *
 * @param values 已采集到的伤害或 HP 损失值。
 * @param emptyLabel 没有数值时显示的兜底文本。
 * @returns 单值、闭区间或兜底文本。
 */
function numberRangeLabel(values: number[], emptyLabel: string): string {
  const uniqueValues = uniqueSortedNumbers(values);
  if (uniqueValues.length === 0) {
    return emptyLabel;
  }
  const first = uniqueValues[0];
  const last = uniqueValues[uniqueValues.length - 1];
  return first === last ? `${first}` : `${first}-${last}`;
}

/**
 * 收集一个 outcome 中指定侧承受的 HP 损失。
 *
 * @param outcome 服务端返回的正式 edge。
 * @param side 需要统计承伤的战斗侧。
 * @returns 结构化事件里该侧被扣除的 HP 数值；事件缺失时返回空数组。
 */
function outcomeSideHpLosses(outcome: TransitionOutcomeResult, side: BattleSideKey): number[] {
  const reportPaths = [
    ...outcome.battle_event_paths,
    ...outcome.event_paths.map((path) => path.battle_events),
  ];
  const losses = reportPaths.flatMap((path) =>
    path
      .filter((event) => event.kind === 'hp-changed' && event.target === side)
      .map((event) => {
        if (typeof event.value === 'number') {
          return Math.abs(event.value);
        }
        if (typeof event.before_value === 'number' && typeof event.after_value === 'number') {
          return Math.max(0, event.before_value - event.after_value);
        }
        return 0;
      })
      .filter((value) => value > 0),
  );
  return uniqueSortedNumbers(losses);
}

/**
 * 读取 outcome 的兜底 HP 损失，用于旧图或事件投影不完整时避免空桶。
 *
 * @param outcome 服务端返回的正式 edge。
 * @returns 所有 compact result 中混合侧别的去重 HP 损失值。
 */
function fallbackOutcomeHpLosses(outcome: TransitionOutcomeResult): number[] {
  return uniqueSortedNumbers(
    outcome.compact_results.flatMap((result) => result.actual_hp_losses),
  );
}

/**
 * 从行动执行结果中提取不依赖 node id 的语义标签。
 *
 * @param outcome 服务端返回的正式 edge。
 * @returns 命中、失败、取消、状态效果等聚合标签。
 */
function outcomeSemanticLabels(outcome: TransitionOutcomeResult): string[] {
  const labels = outcome.compact_results.flatMap((result) => {
    const resolutions = result.action_resolutions.map((resolution) => {
      const move = resolution.move_id === null ? resolution.action_type : `#${resolution.move_id}`;
      if (resolution.status !== 'executed') {
        return `${sideLabel(resolution.side)} ${move} ${resolution.status}`;
      }
      if (resolution.hit !== null) {
        return `${sideLabel(resolution.side)} ${move} ${resolution.hit ? 'hit' : 'miss'}`;
      }
      return `${sideLabel(resolution.side)} ${move}`;
    });
    const effects = result.status_effects.map((effect) => {
      const target = effect.target_side === null ? '' : sideLabel(effect.target_side);
      const source = effect.source_identifier ?? 'status';
      return `${target}${source}:${effect.result}`;
    });
    const critical = result.critical_hit === null ? [] : [result.critical_hit ? 'critical' : 'normal'];
    return [...resolutions, ...effects, ...critical];
  });
  const fallback = outcome.label_fields.result_keys.length > 0
    ? outcome.label_fields.result_keys
    : ['state-change'];
  return [...new Set(labels.length > 0 ? labels : fallback)].sort();
}

/**
 * 返回面向用户的侧别名称。
 *
 * @param side 需要展示的战斗侧。
 * @returns 贴近当前一对一 UI 的“己方/对方”侧别标签。
 */
function playerSideLabel(side: BattleSideKey): string {
  return side === 'attacker' ? '己方(攻方)' : '对方(防方)';
}

/**
 * 读取指定侧的承伤区间；缺少侧别事件时只在攻击方层使用旧 compact fallback。
 *
 * @param outcome 服务端返回的正式 edge。
 * @param side 需要统计承伤的战斗侧。
 * @returns 用于分桶的 HP 损失值。
 */
function sideBucketValues(outcome: TransitionOutcomeResult, side: BattleSideKey): number[] {
  const sideValues = outcomeSideHpLosses(outcome, side);
  if (sideValues.length > 0) {
    return sideValues;
  }
  return side === 'attacker' ? fallbackOutcomeHpLosses(outcome) : [];
}

/**
 * 汇总当前候选集中某一侧所有离散承伤结果，作为二分桶的全集。
 *
 * @param sourceOutcomes 当前 transition group 或父桶内的候选 edge。
 * @param side 需要统计承伤的战斗侧。
 * @returns 升序去重后的承伤全集。
 */
function sideUniverseValues(
  sourceOutcomes: TransitionOutcomeResult[],
  side: BattleSideKey,
): number[] {
  return uniqueSortedNumbers(sourceOutcomes.flatMap((outcome) => sideBucketValues(outcome, side)));
}

/**
 * 把某一侧的离散承伤全集切成低半与高半。
 *
 * @param universe 当前候选集中该侧的全部离散承伤值。
 * @returns 低半和高半两个集合；空全集表示该侧无承伤。
 */
function bisectSideUniverse(universe: number[]): { low: Set<number>; high: Set<number> } {
  const pivot = Math.ceil(universe.length / 2);
  return {
    low: new Set(universe.slice(0, pivot)),
    high: new Set(universe.slice(pivot)),
  };
}

/**
 * 判断 outcome 在当前侧别二分中的归属。
 *
 * @param outcome 服务端返回的正式 edge。
 * @param side 需要统计承伤的战斗侧。
 * @param universe 当前候选集中该侧的全部离散承伤值。
 * @returns no-damage、low、high 或 mixed。
 */
function sideBisectBucketKind(
  outcome: TransitionOutcomeResult,
  side: BattleSideKey,
  universe: number[],
): 'no-damage' | 'low' | 'high' | 'mixed' {
  const values = sideBucketValues(outcome, side);
  if (values.length === 0 || universe.length === 0) {
    return 'no-damage';
  }
  const halves = bisectSideUniverse(universe);
  const hasLow = values.some((value) => halves.low.has(value));
  const hasHigh = values.some((value) => halves.high.has(value));
  if (hasLow && hasHigh) {
    return 'mixed';
  }
  return hasHigh ? 'high' : 'low';
}

/**
 * 返回二分桶的中文标题前缀。
 *
 * @param kind 二分桶类型。
 * @returns 用户可读的低半/高半/跨区间标签。
 */
function bisectKindLabel(kind: 'no-damage' | 'low' | 'high' | 'mixed'): string {
  if (kind === 'low') {
    return '低半伤害';
  }
  if (kind === 'high') {
    return '高半伤害';
  }
  if (kind === 'mixed') {
    return '跨低高区间';
  }
  return '无伤害';
}

/**
 * 为单侧二分结果簇生成稳定 key，排除 target_node_id 以避免回到 node 枚举。
 *
 * @param outcome 服务端返回的正式 edge。
 * @param side 需要统计承伤的战斗侧。
 * @param universe 当前候选集中该侧的全部离散承伤值。
 * @returns 由终局、行动语义和低/高半区间组成的 key。
 */
function sideOutcomeBucketKey(
  outcome: TransitionOutcomeResult,
  side: BattleSideKey,
  universe: number[],
): string {
  const semanticKey = outcomeSemanticLabels(outcome).join('|');
  const bucketKind = sideBisectBucketKind(outcome, side, universe);
  const terminalKey = outcome.label_fields.result_keys.includes('terminal') ? 'terminal' : 'live';
  return `${side}:${terminalKey}:${semanticKey}:${bucketKind}`;
}

/**
 * 为单侧二分结果簇生成标题。
 *
 * @param side 该桶代表的战斗侧。
 * @param bucketOutcomes 同一个桶内的正式 edge。
 * @param universe 当前候选集中该侧的全部离散承伤值。
 * @returns 面向用户的低半/高半承伤摘要。
 */
function sideBucketTitle(
  side: BattleSideKey,
  bucketOutcomes: TransitionOutcomeResult[],
  universe: number[],
): string {
  const firstOutcome = bucketOutcomes[0];
  const kind = firstOutcome === undefined
    ? 'no-damage'
    : sideBisectBucketKind(firstOutcome, side, universe);
  const values = uniqueSortedNumbers(
    bucketOutcomes.flatMap((outcome) => sideBucketValues(outcome, side)),
  );
  return `${playerSideLabel(side)} ${bisectKindLabel(kind)} · HP -${numberRangeLabel(values, '0')}`;
}

/**
 * 为结果簇生成辅助说明。
 *
 * @param bucketOutcomes 同一个桶内的正式 edge。
 * @param side 当前桶索引的战斗侧。
 * @param universe 当前候选集中该侧的全部离散承伤值。
 * @returns 包含目标节点数、精确 edge 数、候选档位数量和结果标签的紧凑描述。
 */
function bucketDescription(
  bucketOutcomes: TransitionOutcomeResult[],
  side: BattleSideKey,
  universe: number[],
): string {
  const targetCount = new Set(bucketOutcomes.map((outcome) => outcome.target_node_id)).size;
  const values = uniqueSortedNumbers(
    bucketOutcomes.flatMap((outcome) => sideBucketValues(outcome, side)),
  );
  const totalSlots = universe.length > 0 ? universe.length : 1;
  const firstOutcome = bucketOutcomes[0];
  const labels = firstOutcome === undefined ? [] : outcomeSemanticLabels(firstOutcome).slice(0, 2);
  const labelText = labels.length > 0 ? ` · ${labels.join(' / ')}` : '';
  return `${targetCount} 个目标 · ${bucketOutcomes.length} 边 · ${values.length}/${totalSlots} 档${labelText}`;
}

/**
 * 把 outcomes 按指定侧别的低半/高半承伤构造成同级桶。
 *
 * @param sourceOutcomes 后端按真实 edge 返回的 outcome 列表。
 * @param side 需要作为本层索引的战斗侧。
 * @param keyPrefix 父级 key 前缀，保证多层桶 key 全局唯一。
 * @returns 按条件概率从高到低排序的同级聚合桶。
 */
function buildSideBuckets(
  sourceOutcomes: TransitionOutcomeResult[],
  side: BattleSideKey,
  keyPrefix: string,
): OutcomeBucket[] {
  const grouped = new Map<string, TransitionOutcomeResult[]>();
  const universe = sideUniverseValues(sourceOutcomes, side);
  for (const outcome of sourceOutcomes) {
    const key = sideOutcomeBucketKey(outcome, side, universe);
    grouped.set(key, [...(grouped.get(key) ?? []), outcome]);
  }

  return [...grouped.entries()]
    .map(([rawKey, bucketOutcomes]) => ({
      key: `${keyPrefix}:${rawKey}`,
      title: sideBucketTitle(side, bucketOutcomes, universe),
      description: bucketDescription(bucketOutcomes, side, universe),
      outcomes: bucketOutcomes,
      probabilityPercent: bucketOutcomes.reduce(
        (sum, outcome) => sum + outcome.probability.percent,
        0,
      ),
      targetCount: new Set(bucketOutcomes.map((outcome) => outcome.target_node_id)).size,
      children: [],
    }))
    .sort((left, right) => right.probabilityPercent - left.probabilityPercent);
}

/**
 * 构造“己方结果 -> 对方结果 -> 精确 edge”的默认层级策略。
 *
 * @param sourceOutcomes 后端按真实 edge 返回的 outcome 列表。
 * @returns 两级侧别聚合桶，第二级展开后才显示真实 node edge。
 */
function buildSideDamageOutcomeBuckets(sourceOutcomes: TransitionOutcomeResult[]): OutcomeBucket[] {
  return buildSideBuckets(sourceOutcomes, 'attacker', 'primary').map((primaryBucket) => ({
    ...primaryBucket,
    children: buildSideBuckets(primaryBucket.outcomes, 'defender', primaryBucket.key),
  }));
}

/**
 * 切换一级结果簇展开状态，展开后显示对方结果簇。
 *
 * @param bucketKey 聚合桶的稳定 key。
 */
function togglePrimaryBucket(bucketKey: string): void {
  const nextBucketKey = expandedPrimaryBucketKey.value === bucketKey ? null : bucketKey;
  expandedPrimaryBucketKey.value = nextBucketKey;
  expandedSecondaryBucketKey.value = null;
}

/**
 * 切换二级结果簇展开状态，展开后显示真实 node edge。
 *
 * @param bucketKey 聚合桶的稳定 key。
 */
function toggleSecondaryBucket(bucketKey: string): void {
  expandedSecondaryBucketKey.value =
    expandedSecondaryBucketKey.value === bucketKey ? null : bucketKey;
}

/** 显示更多聚合桶，避免一次渲染过长 outcome 列表。 */
function showMoreBuckets(): void {
  visibleBucketLimit.value += 12;
}

/**
 * 切换 outcome 展示模式。
 *
 * @param mode grouped 为默认聚合视图，raw 为原始 edge 列表。
 */
function setOutcomeViewMode(mode: 'grouped' | 'raw'): void {
  outcomeViewMode.value = mode;
}

/**
 * 为精确 edge 行生成双方承伤摘要，帮助用户在最内层快速定位 node。
 *
 * @param outcome 服务端返回的正式 edge。
 * @returns 同时包含己方与对方 HP 损失的紧凑文本。
 */
function exactOutcomeDamageLabel(outcome: TransitionOutcomeResult): string {
  const attackerLoss = numberRangeLabel(sideBucketValues(outcome, 'attacker'), '0');
  const defenderLoss = numberRangeLabel(sideBucketValues(outcome, 'defender'), '0');
  return `己 -${attackerLoss} / 对 -${defenderLoss}`;
}

/**
 * 把缩放倍率限制在画布可用范围内。
 *
 * @param scale 用户滚轮或按钮请求的新缩放倍率。
 * @returns 不小于最小倍率且不大于最大倍率的安全值。
 */
function clampCanvasScale(scale: number): number {
  return Math.max(MIN_CANVAS_SCALE, Math.min(MAX_CANVAS_SCALE, scale));
}

/**
 * 重置左侧树画布视角到默认位置。
 *
 * @returns 无返回值；会直接更新响应式视角状态。
 */
function resetCanvasViewport(): void {
  canvasTransform.value = { x: 0, y: 0, scale: 1 };
}

/**
 * 围绕指定屏幕坐标缩放树画布。
 *
 * @param nextScale 目标缩放倍率。
 * @param clientX 缩放中心的视口横坐标；缺省时使用画布中心。
 * @param clientY 缩放中心的视口纵坐标；缺省时使用画布中心。
 */
function zoomCanvasTo(nextScale: number, clientX?: number, clientY?: number): void {
  const viewport = canvasViewport.value;
  if (viewport === null) {
    canvasTransform.value = {
      ...canvasTransform.value,
      scale: clampCanvasScale(nextScale),
    };
    return;
  }
  const rect = viewport.getBoundingClientRect();
  const originClientX = clientX ?? rect.left + rect.width / 2;
  const originClientY = clientY ?? rect.top + rect.height / 2;
  const localX = originClientX - rect.left;
  const localY = originClientY - rect.top;
  const previous = canvasTransform.value;
  const scale = clampCanvasScale(nextScale);
  const worldX = (localX - previous.x) / previous.scale;
  const worldY = (localY - previous.y) / previous.scale;
  canvasTransform.value = {
    x: localX - worldX * scale,
    y: localY - worldY * scale,
    scale,
  };
}

/**
 * 处理鼠标滚轮缩放；缩放中心固定在鼠标所在位置，方便追踪远端节点。
 *
 * @param event 浏览器 wheel 事件。
 */
function zoomCanvas(event: WheelEvent): void {
  const factor = Math.exp(-event.deltaY * 0.001);
  zoomCanvasTo(canvasTransform.value.scale * factor, event.clientX, event.clientY);
}

/** 放大左侧树画布。 */
function zoomInCanvas(): void {
  zoomCanvasTo(canvasTransform.value.scale * 1.16);
}

/** 缩小左侧树画布。 */
function zoomOutCanvas(): void {
  zoomCanvasTo(canvasTransform.value.scale / 1.16);
}

/** 重置视角并把当前节点列对齐回可操作区域。 */
function resetAndFocusCanvas(): void {
  resetCanvasViewport();
  void nextTick(focusCurrentColumn);
}

/**
 * 判断一次 pointerdown 是否应该开始拖拽画布。
 *
 * @param target 事件目标节点。
 * @returns 在按钮、输入和具体交互卡片上按下时返回 false，其余空白区域返回 true。
 */
function canStartCanvasPan(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return target.closest('button, a, input, select, textarea, [role="button"]') === null;
}

/**
 * 开始拖拽平移左侧画布。
 *
 * @param event pointerdown 事件；只响应鼠标左键或触控主指针。
 */
function startCanvasPan(event: PointerEvent): void {
  if (event.button !== 0 || !canStartCanvasPan(event.target)) {
    return;
  }
  const viewport = canvasViewport.value;
  if (viewport === null) {
    return;
  }
  viewport.setPointerCapture(event.pointerId);
  canvasPanSession.value = {
    pointerId: event.pointerId,
    startClientX: event.clientX,
    startClientY: event.clientY,
    originX: canvasTransform.value.x,
    originY: canvasTransform.value.y,
  };
}

/**
 * 拖拽过程中更新画布偏移。
 *
 * @param event pointermove 事件。
 */
function moveCanvasPan(event: PointerEvent): void {
  const session = canvasPanSession.value;
  if (session === null || session.pointerId !== event.pointerId) {
    return;
  }
  canvasTransform.value = {
    ...canvasTransform.value,
    x: session.originX + event.clientX - session.startClientX,
    y: session.originY + event.clientY - session.startClientY,
  };
}

/**
 * 结束拖拽平移并释放 pointer capture。
 *
 * @param event pointerup 或 pointercancel 事件。
 */
function endCanvasPan(event: PointerEvent): void {
  const session = canvasPanSession.value;
  if (session === null || session.pointerId !== event.pointerId) {
    return;
  }
  canvasViewport.value?.releasePointerCapture(event.pointerId);
  canvasPanSession.value = null;
}

/**
 * 当路径推进或回退后，把当前列自动拉回左侧画布可见区域。
 *
 * @returns 无返回值；仅在当前列超出 viewport 时调整 x 偏移。
 */
function focusCurrentColumn(): void {
  const viewport = canvasViewport.value;
  const content = canvasContent.value;
  if (viewport === null || content === null) {
    return;
  }
  const currentColumn = content.querySelectorAll<HTMLElement>('.battle-tree-column')[currentDepth.value];
  if (currentColumn === undefined) {
    return;
  }
  const padding = 24;
  const viewportWidth = viewport.clientWidth;
  const scale = canvasTransform.value.scale;
  const columnLeft = currentColumn.offsetLeft * scale + canvasTransform.value.x;
  const columnRight =
    (currentColumn.offsetLeft + currentColumn.offsetWidth) * scale + canvasTransform.value.x;
  let nextX = canvasTransform.value.x;
  if (columnRight > viewportWidth - padding) {
    nextX -= columnRight - (viewportWidth - padding);
  }
  if (columnLeft < padding) {
    nextX += padding - columnLeft;
  }
  canvasTransform.value = {
    ...canvasTransform.value,
    x: nextX,
    y: Math.min(padding, canvasTransform.value.y),
  };
}

/** 清空当前节点的技能筛选和 outcome 展开状态。 */
function resetBranchSelection(): void {
  outcomes.value = [];
  expandedGroupId.value = null;
  expandedPrimaryBucketKey.value = null;
  expandedSecondaryBucketKey.value = null;
  selectedAttackerMoveId.value = null;
  selectedDefenderMoveId.value = null;
  visibleBucketLimit.value = 12;
}

/**
 * 切换当前节点某一侧的技能筛选。
 *
 * @param side 攻击方或防守方。
 * @param moveId 目标技能 ID；null 表示清空该侧筛选。
 */
function selectMoveFilter(side: BattleSideKey, moveId: number | null): void {
  if (side === 'attacker') {
    selectedAttackerMoveId.value = moveId;
  } else {
    selectedDefenderMoveId.value = moveId;
  }
  outcomes.value = [];
  expandedGroupId.value = null;
  expandedPrimaryBucketKey.value = null;
  expandedSecondaryBucketKey.value = null;
  visibleBucketLimit.value = 12;
}

/**
 * 根据 handle 读取根节点，并清空旧树路径。
 *
 * @param handle 固定推演返回的图句柄。
 */
async function start(handle: BattleExplorationResult | null | undefined): Promise<void> {
  lifecycleVersion += 1;
  const requestVersion = lifecycleVersion;
  loading.value = true;
  error.value = null;
  columns.value = [];
  resetCanvasViewport();
  resetBranchSelection();
  try {
    const root = snapshotMode.value
      ? await expandSnapshot({ steps: [] })
      : await exploreStoredGraph(handle, { steps: [] });
    if (requestVersion !== lifecycleVersion) return;
    columns.value = [root];
    void nextTick(focusCurrentColumn);
  } catch (caught) {
    if (requestVersion === lifecycleVersion) {
      error.value = caught instanceof Error ? caught.message : '大屏状态图加载失败';
    }
  } finally {
    if (requestVersion === lifecycleVersion) {
      loading.value = false;
    }
  }
}

/** 使用完整图句柄读取一个 cursor 对应的探索视图。 */
async function exploreStoredGraph(
  handle: BattleExplorationResult | null | undefined,
  cursor: BattleGraphExplorationResult['cursor'],
): Promise<BattleGraphExplorationResult> {
  if (handle === null || handle === undefined) {
    throw new Error('完整图句柄不可用。');
  }
  return exploreBattleGraph(
    handle.graph_id,
    handle.calculation_revision,
    cursor,
  );
}

/** 使用固定配置快照请求展开一个 cursor 对应的探索视图。 */
async function expandSnapshot(
  cursor: BattleGraphExplorationResult['cursor'],
): Promise<BattleGraphExplorationResult> {
  if (props.snapshotRequest === null || props.snapshotRequest === undefined) {
    throw new Error('固定配置快照请求不可用。');
  }
  return expandFixedBattleSnapshot(props.snapshotRequest, cursor);
}

/**
 * 截断到用户选择的祖先节点，使后续分支可以重新选择。
 *
 * @param depth 目标路径深度，0 表示 ROOT。
 */
function selectDepth(depth: number): void {
  columns.value = columns.value.slice(0, depth + 1);
  resetBranchSelection();
  void nextTick(focusCurrentColumn);
}

/**
 * 展开当前节点的一组 outcomes；再次点击同组时收起。
 *
 * @param groupId 当前节点 transition group 的稳定 ID。
 */
async function toggleGroup(groupId: string): Promise<void> {
  const source = current.value;
  if (source === null || source.terminal) return;
  if (expandedGroupId.value === groupId) {
    expandedGroupId.value = null;
    outcomes.value = [];
    expandedPrimaryBucketKey.value = null;
    expandedSecondaryBucketKey.value = null;
    visibleBucketLimit.value = 12;
    return;
  }
  outcomesLoading.value = true;
  expandedGroupId.value = groupId;
  outcomes.value = [];
  expandedPrimaryBucketKey.value = null;
  expandedSecondaryBucketKey.value = null;
  visibleBucketLimit.value = 12;
  error.value = null;
  try {
    if (snapshotMode.value) {
      outcomes.value =
        source.transition_groups.find((group) => group.group_id === groupId)?.outcomes ?? [];
    } else {
      if (props.handle === null || props.handle === undefined) {
        throw new Error('完整图句柄不可用。');
      }
      const result = await loadBattleTransitionGroupOutcomes(
        props.handle.graph_id,
        props.handle.calculation_revision,
        source.cursor,
        groupId,
      );
      outcomes.value = result.transition_group.outcomes;
    }
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '分支展开失败';
  } finally {
    outcomesLoading.value = false;
  }
}

/**
 * 沿当前 outcome 进入下一层节点，并把它追加到横向树末尾。
 *
 * @param outcome 用户在当前节点选择的正式 edge。
 */
async function chooseOutcome(outcome: TransitionOutcomeResult): Promise<void> {
  const source = current.value;
  if (source === null) return;
  loading.value = true;
  error.value = null;
  try {
    const next = snapshotMode.value
      ? await expandSnapshot({
          steps: [
            ...source.cursor.steps,
            {
              source_node_id: source.node.node_id,
              edge_id: outcome.edge_id,
              target_node_id: outcome.target_node_id,
            },
          ],
        })
      : await advanceStoredGraph(source, outcome);
    columns.value = [...columns.value, next];
    resetBranchSelection();
    void nextTick(focusCurrentColumn);
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '进入目标节点失败';
  } finally {
    loading.value = false;
  }
}

/** 沿完整图中的正式 edge 前进一层。 */
async function advanceStoredGraph(
  source: BattleGraphExplorationResult,
  outcome: TransitionOutcomeResult,
): Promise<BattleGraphExplorationResult> {
  if (props.handle === null || props.handle === undefined) {
    throw new Error('完整图句柄不可用。');
  }
  return advanceBattleExploration(
    props.handle.graph_id,
    props.handle.calculation_revision,
    source.cursor,
    outcome.edge_id,
  );
}

/** 通知父组件关闭大屏。 */
function close(): void {
  emit('close');
}

/** 通知父组件重新求解当前固定配置以刷新 graph handle。 */
function rerun(): void {
  emit('rerun');
}

watch(
  () => [props.handle, props.snapshotRequest] as const,
  ([handle]) => {
    void start(handle);
  },
  { immediate: true },
);

watch(
  () => currentDepth.value,
  () => {
    void nextTick(focusCurrentColumn);
  },
);
</script>

<template>
  <section class="battle-tree-screen" aria-label="大屏树状状态图探索">
    <header class="battle-tree-screen__header">
      <div>
        <p>FULLSCREEN TREE</p>
        <h2>从起点向右追踪战斗路径</h2>
        <small>点击分支进入下一节点；点击任意祖先列即可切回那条路径。</small>
      </div>
      <div class="battle-tree-screen__actions">
        <button type="button" @click="rerun">重新推演</button>
        <button type="button" class="battle-tree-screen__close" @click="close">关闭</button>
      </div>
    </header>

    <p v-if="error" class="battle-tree-screen__error" role="alert">{{ error }}</p>
    <p v-if="loading && columns.length === 0" class="battle-tree-screen__loading">正在加载 ROOT…</p>

    <div class="battle-tree-screen__body">
      <div
        ref="canvasViewport"
        class="battle-tree-screen__canvas"
        :class="{ 'battle-tree-screen__canvas--panning': canvasPanSession !== null }"
        data-testid="battle-tree-canvas"
        @wheel.prevent="zoomCanvas"
        @pointerdown="startCanvasPan"
        @pointermove="moveCanvasPan"
        @pointerup="endCanvasPan"
        @pointercancel="endCanvasPan"
      >
        <div class="battle-tree-canvas-controls" aria-label="树状图视角控制" @pointerdown.stop @wheel.stop>
          <button type="button" title="缩小" @click="zoomOutCanvas">−</button>
          <span>{{ Math.round(canvasTransform.scale * 100) }}%</span>
          <button type="button" title="放大" @click="zoomInCanvas">+</button>
          <button type="button" title="重置并定位当前节点" @click="resetAndFocusCanvas">重置</button>
        </div>
        <div
          ref="canvasContent"
          class="battle-tree-screen__columns"
          :style="canvasTransformStyle"
        >
          <article
            v-for="(column, index) in columns"
            :key="`${column.graph_id}:${index}:${column.node.node_id}`"
            class="battle-tree-column"
            :class="{ 'battle-tree-column--active': index === currentDepth }"
          >
            <button
              type="button"
              class="battle-tree-column__node"
              :disabled="index === currentDepth"
              @click="selectDepth(index)"
            >
              <span>{{ index === 0 ? 'ROOT' : `STEP ${index}` }}</span>
              <strong>node #{{ column.node.node_id }}</strong>
              <small>
                Turn {{ column.node.turn_number }} ·
                {{ percentLabel(column.cumulative_probability.percent) }}
              </small>
            </button>

            <div v-if="index === currentDepth" class="battle-tree-column__detail">
              <BattleGraphNode
                :node="column.node"
                :cumulative-probability="column.cumulative_probability"
              />

              <section v-if="!column.terminal" class="battle-tree-branches">
                <header>
                  <strong>选择下一条边</strong>
                  <small>
                    {{ filteredTransitionGroups.length }} / {{ column.transition_groups.length }} 个分支组
                  </small>
                </header>
                <div
                  v-if="column.transition_groups.length > 1"
                  class="battle-tree-action-filters"
                  aria-label="按双方技能筛选分支组"
                >
                  <div class="battle-tree-action-filter-row">
                    <span>己方技能</span>
                    <button
                      type="button"
                      :class="{ 'battle-tree-action-filter--active': selectedAttackerMoveId === null }"
                      @click="selectMoveFilter('attacker', null)"
                    >
                      全部
                    </button>
                    <button
                      v-for="option in attackerMoveOptions"
                      :key="`attacker:${option.moveId ?? 'other'}`"
                      type="button"
                      :class="{ 'battle-tree-action-filter--active': selectedAttackerMoveId === option.moveId }"
                      @click="selectMoveFilter('attacker', option.moveId)"
                    >
                      {{ option.label }}
                      <small>{{ option.count }}</small>
                    </button>
                  </div>
                  <div class="battle-tree-action-filter-row">
                    <span>对方技能</span>
                    <button
                      type="button"
                      :class="{ 'battle-tree-action-filter--active': selectedDefenderMoveId === null }"
                      @click="selectMoveFilter('defender', null)"
                    >
                      全部
                    </button>
                    <button
                      v-for="option in defenderMoveOptions"
                      :key="`defender:${option.moveId ?? 'other'}`"
                      type="button"
                      :class="{ 'battle-tree-action-filter--active': selectedDefenderMoveId === option.moveId }"
                      @click="selectMoveFilter('defender', option.moveId)"
                    >
                      {{ option.label }}
                      <small>{{ option.count }}</small>
                    </button>
                  </div>
                </div>
                <article
                  v-for="group in filteredTransitionGroups"
                  :key="group.group_id"
                  class="battle-tree-group"
                >
                  <button type="button" @click="toggleGroup(group.group_id)">
                    <span>{{ groupTitle(group) }}</span>
                    <small>
                      {{ percentLabel(group.selection_probability.percent) }} ·
                      {{ group.distinct_outcome_count }} 个目标
                    </small>
                  </button>
                  <p
                    v-if="outcomesLoading && expandedGroupId === group.group_id"
                    class="battle-tree-group__loading"
                  >
                    正在展开 outcomes…
                  </p>
                  <div
                    v-else-if="expandedGroupId === group.group_id"
                    class="battle-tree-outcomes"
                  >
                    <header class="battle-tree-outcomes__toolbar">
                      <span>
                        {{ activeOutcomeGroupingStrategy.label }} ·
                        {{ outcomes.length }} 条精确边 · {{ outcomeBuckets.length }} 个结果簇
                      </span>
                      <span class="battle-tree-outcomes__modes" aria-label="outcome 展示模式">
                        <button
                          type="button"
                          :class="{ 'battle-tree-outcomes__mode--active': outcomeViewMode === 'grouped' }"
                          @click="setOutcomeViewMode('grouped')"
                        >
                          聚合
                        </button>
                        <button
                          type="button"
                          :class="{ 'battle-tree-outcomes__mode--active': outcomeViewMode === 'raw' }"
                          @click="setOutcomeViewMode('raw')"
                        >
                          原始
                        </button>
                      </span>
                    </header>

                    <template v-if="outcomeViewMode === 'grouped'">
                      <article
                        v-for="bucket in visibleOutcomeBuckets"
                        :key="bucket.key"
                        class="battle-tree-outcome-bucket"
                      >
                        <button type="button" @click="togglePrimaryBucket(bucket.key)">
                          <span>
                            <strong>{{ bucket.title }}</strong>
                            <small>{{ bucket.description }}</small>
                          </span>
                          <span>
                            {{ percentLabel(bucket.probabilityPercent) }}
                            <small>{{ bucket.targetCount }} nodes</small>
                          </span>
                        </button>
                        <div
                          v-if="expandedPrimaryBucketKey === bucket.key"
                          class="battle-tree-outcome-bucket__children"
                        >
                          <article
                            v-for="childBucket in bucket.children"
                            :key="childBucket.key"
                            class="battle-tree-outcome-bucket battle-tree-outcome-bucket--secondary"
                          >
                            <button type="button" @click="toggleSecondaryBucket(childBucket.key)">
                              <span>
                                <strong>{{ childBucket.title }}</strong>
                                <small>{{ childBucket.description }}</small>
                              </span>
                              <span>
                                {{ percentLabel(childBucket.probabilityPercent) }}
                                <small>{{ childBucket.targetCount }} nodes</small>
                              </span>
                            </button>
                            <div
                              v-if="expandedSecondaryBucketKey === childBucket.key"
                              class="battle-tree-outcome-bucket__edges"
                            >
                              <button
                                v-for="outcome in childBucket.outcomes"
                                :key="outcome.edge_id"
                                class="battle-tree-exact-edge"
                                type="button"
                                @click="chooseOutcome(outcome)"
                              >
                                <span>
                                  <strong>#{{ outcome.target_node_id }}</strong>
                                  <small>{{ exactOutcomeDamageLabel(outcome) }}</small>
                                </span>
                                <span>
                                  {{ percentLabel(outcome.probability.percent) }}
                                  <small>累计 {{ percentLabel(outcome.cumulative_probability.percent) }}</small>
                                </span>
                              </button>
                            </div>
                          </article>
                        </div>
                      </article>
                      <button
                        v-if="visibleBucketLimit < outcomeBuckets.length"
                        type="button"
                        class="battle-tree-outcomes__more"
                        @click="showMoreBuckets"
                      >
                        显示更多结果簇
                      </button>
                    </template>

                    <template v-else>
                      <button
                        v-for="outcome in outcomes"
                        :key="outcome.edge_id"
                        class="battle-tree-exact-edge"
                        type="button"
                        @click="chooseOutcome(outcome)"
                      >
                        <span>
                          <strong>#{{ outcome.target_node_id }}</strong>
                          <small>{{ exactOutcomeDamageLabel(outcome) }}</small>
                        </span>
                        <span>
                          {{ percentLabel(outcome.probability.percent) }}
                          <small>累计 {{ percentLabel(outcome.cumulative_probability.percent) }}</small>
                        </span>
                      </button>
                    </template>
                  </div>
                </article>
              </section>

              <p v-else class="battle-tree-terminal">
                已到达终局，可点击左侧任意节点切换路径。
              </p>
            </div>
          </article>
        </div>
      </div>

      <BattleReportPanel :report="currentReport" :context="context" :node="current?.node ?? null" />
    </div>
  </section>
</template>

<style scoped>
.battle-tree-screen {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  background: #f5f7f6;
  color: #14251d;
}

.battle-tree-screen__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  border-bottom: 1px solid #d6dfd9;
  padding: 18px 24px;
  background: #ffffff;
}

.battle-tree-screen__header p,
.battle-tree-screen__header h2,
.battle-tree-screen__header small,
.battle-tree-screen__error,
.battle-tree-screen__loading,
.battle-tree-terminal,
.battle-tree-group__loading {
  margin: 0;
}

.battle-tree-screen__header p {
  color: #9d3039;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.16em;
}

.battle-tree-screen__header h2 {
  margin-top: 4px;
  font-size: 26px;
}

.battle-tree-screen__header small {
  color: #68766e;
}

.battle-tree-screen__actions {
  display: flex;
  gap: 10px;
}

.battle-tree-screen__actions button {
  border: 1px solid #cfd9d2;
  border-radius: 10px;
  background: #fff;
  color: #183d31;
  cursor: pointer;
  font-weight: 800;
  padding: 10px 14px;
}

.battle-tree-screen__close {
  border-color: #a52f3a !important;
  background: #b72b38 !important;
  color: #fff !important;
}

.battle-tree-screen__error,
.battle-tree-screen__loading {
  padding: 10px 24px;
}

.battle-tree-screen__error {
  color: #9b3038;
}

.battle-tree-screen__body {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.34fr);
  min-height: 0;
  overflow: hidden;
  padding: 16px;
}

.battle-tree-screen__body :deep(.battle-report-panel) {
  min-height: 0;
  max-height: 100%;
}

.battle-tree-screen__canvas {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid #d3ddd6;
  border-radius: 18px;
  background: #ffffff;
  cursor: grab;
  touch-action: none;
}

.battle-tree-screen__canvas--panning {
  cursor: grabbing;
}

.battle-tree-canvas-controls {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #d8e3dc;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.94);
  box-shadow: 0 10px 24px rgba(35, 54, 45, 0.08);
  padding: 6px;
}

.battle-tree-canvas-controls button {
  min-width: 32px;
  min-height: 30px;
  border: 1px solid #cad8d0;
  border-radius: 8px;
  background: #fff;
  color: #183d31;
  cursor: pointer;
  font-size: 13px;
  font-weight: 900;
  padding: 4px 8px;
}

.battle-tree-canvas-controls span {
  min-width: 44px;
  color: #526259;
  font-size: 12px;
  font-weight: 900;
  text-align: center;
}

.battle-tree-screen__columns {
  position: absolute;
  top: 0;
  left: 0;
  display: flex;
  gap: 18px;
  min-width: max-content;
  min-height: max-content;
  padding: 18px;
  transform-origin: 0 0;
  will-change: transform;
}

.battle-tree-column {
  display: grid;
  align-content: start;
  gap: 12px;
  flex: 0 0 280px;
  min-width: 0;
}

.battle-tree-column--active {
  flex-basis: min(520px, 72vw);
}

.battle-tree-column__node {
  display: grid;
  gap: 4px;
  width: 100%;
  border: 1px solid #d7e1da;
  border-radius: 14px;
  background: #f8fbf9;
  color: #203b31;
  cursor: pointer;
  padding: 12px;
  text-align: left;
}

.battle-tree-column__node,
.battle-tree-column__detail {
  cursor: auto;
}

.battle-tree-column__node:disabled {
  border-color: #8fb3a0;
  background: #eaf4ef;
  cursor: default;
}

.battle-tree-column__node span,
.battle-tree-column__node small,
.battle-tree-branches small,
.battle-tree-group button small,
.battle-tree-outcomes button span {
  color: #6a7870;
  font-size: 11px;
}

.battle-tree-column__node strong {
  font-size: 18px;
}

.battle-tree-column__detail {
  display: grid;
  gap: 14px;
}

.battle-tree-branches {
  display: grid;
  gap: 10px;
  border: 1px solid #dde7e1;
  border-radius: 16px;
  padding: 12px;
  background: #fbfcfb;
}

.battle-tree-branches header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.battle-tree-action-filters {
  display: grid;
  gap: 8px;
  border: 1px solid #dfe8e3;
  border-radius: 12px;
  background: #ffffff;
  padding: 8px;
}

.battle-tree-action-filter-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.battle-tree-action-filter-row > span {
  flex: 0 0 64px;
  color: #526259;
  font-size: 11px;
  font-weight: 900;
}

.battle-tree-action-filter-row button {
  border: 1px solid #d4dfd8;
  border-radius: 999px;
  background: #fff;
  color: #203b31;
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
  min-height: 30px;
  padding: 5px 10px;
}

.battle-tree-action-filter-row button small {
  color: #6a7870;
  margin-left: 4px;
}

.battle-tree-action-filter--active {
  border-color: #7fa58f !important;
  background: #e9f3ee !important;
  color: #143c30 !important;
}

.battle-tree-group {
  display: grid;
  gap: 8px;
}

.battle-tree-group > button,
.battle-tree-outcomes button,
.battle-tree-outcome-bucket > button,
.battle-tree-exact-edge {
  display: grid;
  gap: 4px;
  width: 100%;
  border: 1px solid #dce5f2;
  border-radius: 12px;
  background: #fff;
  color: #1d3329;
  cursor: pointer;
  padding: 10px;
  text-align: left;
}

.battle-tree-group > button:hover,
.battle-tree-outcomes button:hover,
.battle-tree-outcome-bucket > button:hover,
.battle-tree-exact-edge:hover {
  border-color: #7fa58f;
  background: #f2f8f5;
}

.battle-tree-outcomes {
  display: grid;
  gap: 7px;
  max-height: 540px;
  overflow: auto;
  padding-left: 14px;
}

.battle-tree-outcomes__toolbar {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  border: 1px solid #dfe8e3;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.96);
  padding: 8px;
}

.battle-tree-outcomes__toolbar span {
  color: #62746a;
  font-size: 11px;
}

.battle-tree-outcomes__modes {
  display: grid;
  grid-template-columns: repeat(2, minmax(54px, 1fr));
  gap: 4px;
}

.battle-tree-outcomes__modes button {
  min-height: 28px;
  border-radius: 8px;
  padding: 4px 8px;
  text-align: center;
}

.battle-tree-outcomes__mode--active {
  border-color: #8fb3a0 !important;
  background: #e7f2ec !important;
  color: #173d31 !important;
}

.battle-tree-outcome-bucket {
  display: grid;
  gap: 6px;
}

.battle-tree-outcome-bucket > button {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  border-color: #cddfd5;
  background: #f8fbf9;
}

.battle-tree-outcome-bucket > button > span {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.battle-tree-outcome-bucket > button > span:last-child {
  justify-items: end;
  color: #173d31;
  font-weight: 900;
}

.battle-tree-outcome-bucket small {
  color: #68766e;
  font-size: 11px;
  line-height: 1.35;
}

.battle-tree-outcome-bucket__children {
  display: grid;
  gap: 7px;
  padding-left: 14px;
}

.battle-tree-outcome-bucket--secondary > button {
  border-color: #d7e1ed;
  background: #ffffff;
}

.battle-tree-outcome-bucket__edges {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(168px, 1fr));
  gap: 6px;
  padding-left: 14px;
}

.battle-tree-exact-edge {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  min-height: 42px;
  padding: 7px 9px;
  background: #ffffff;
}

.battle-tree-exact-edge > span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.battle-tree-exact-edge > span:last-child {
  justify-items: end;
  color: #173d31;
  font-size: 12px;
  font-weight: 900;
}

.battle-tree-exact-edge strong,
.battle-tree-exact-edge small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.battle-tree-exact-edge small {
  color: #6a7870;
  font-size: 10px;
  font-weight: 600;
}

.battle-tree-outcomes__more {
  border-style: dashed !important;
  color: #385448 !important;
  text-align: center !important;
}

.battle-tree-terminal {
  border-radius: 12px;
  background: #f8e8e9;
  color: #8f2d36;
  padding: 12px;
}

@media (max-width: 900px) {
  .battle-tree-screen__body {
    grid-template-columns: 1fr;
  }

  .battle-tree-screen__header {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
