import { computed, onScopeDispose, ref, shallowRef } from 'vue';
import {
  advanceBattleExploration,
  backtrackBattleExploration,
  exploreBattleGraph,
  InferenceApiError,
  loadBattleTransitionGroupOutcomes,
  type BattleExplorationResult,
  type BattleGraphExplorationResult,
  type ExplorationCursorResult,
  type TransitionOutcomeResult,
} from '../api/inference';

export interface ExplorationPathEntry {
  depth: number;
  nodeId: number;
  label: string;
}

export interface BattleExplorationOptions {
  nodeCacheCapacity?: number;
  groupCacheCapacity?: number;
}

/**
 * 提供明确容量上限的内存 LRU cache，避免路径探索把完整历史窗口长期保留。
 *
 * @typeParam T 每个 cache entry 保存的只读响应类型。
 */
export class BoundedLruCache<T> {
  private readonly capacity: number;
  private readonly entries = new Map<string, T>();

  /**
   * 创建固定容量的 LRU cache。
   *
   * @param capacity 最大 entry 数，必须为正整数。
   */
  constructor(capacity: number) {
    if (!Number.isInteger(capacity) || capacity <= 0) {
      throw new Error('cache capacity must be a positive integer');
    }
    this.capacity = capacity;
  }

  /**
   * 读取并提升一个 entry 的最近使用顺序。
   *
   * @param key 稳定 cache key。
   * @returns 命中时返回缓存值；不存在时返回 undefined。
   */
  get(key: string): T | undefined {
    const value = this.entries.get(key);
    if (value === undefined) {
      return undefined;
    }
    this.entries.delete(key);
    this.entries.set(key, value);
    return value;
  }

  /**
   * 写入或替换一个 entry，并淘汰最久未使用项直到满足容量上限。
   *
   * @param key 稳定 cache key。
   * @param value 由服务端返回、允许短期复用的响应快照。
   */
  set(key: string, value: T): void {
    this.entries.delete(key);
    this.entries.set(key, value);
    while (this.entries.size > this.capacity) {
      const oldestKey = this.entries.keys().next().value as string | undefined;
      if (oldestKey === undefined) {
        break;
      }
      this.entries.delete(oldestKey);
    }
  }

  /** 清除全部强引用，使切换 graph 或组件卸载后旧窗口可被回收。 */
  clear(): void {
    this.entries.clear();
  }

  /** 返回当前 entry 数，仅用于测试容量与析构语义。 */
  get size(): number {
    return this.entries.size;
  }
}

/**
 * 把 cursor 转为同时保留顺序、source、edge 与 target 的稳定 cache key。
 *
 * @param cursor 服务端返回的真实 edge 序列。
 * @returns 可区分合流路径与循环回边的字符串 key。
 */
function cursorKey(cursor: ExplorationCursorResult): string {
  if (cursor.steps.length === 0) {
    return 'root';
  }
  return cursor.steps
    .map((step) => `${step.source_node_id}:${step.edge_id}:${step.target_node_id}`)
    .join('|');
}

/**
 * 创建不共享可变 steps 数组的 cursor 副本。
 *
 * @param cursor 服务端返回的 cursor。
 * @returns 可安全截断或缓存的独立 cursor。
 */
function cloneCursor(cursor: ExplorationCursorResult): ExplorationCursorResult {
  return {
    steps: cursor.steps.map((step) => ({ ...step })),
  };
}

/**
 * 为 breadcrumb 生成不依赖中文战报 presenter 的窄结果摘要。
 *
 * @param outcome 用户实际选择的归并后正式 edge。
 * @returns 优先展示实际 HP 损失区间，其次展示结果 key 的短标签。
 */
function outcomeLabel(outcome: TransitionOutcomeResult): string {
  if (outcome.damage_rolls.length > 0) {
    const hpLosses = outcome.damage_rolls.map((roll) => roll.actual_hp_loss);
    const minimum = Math.min(...hpLosses);
    const maximum = Math.max(...hpLosses);
    return minimum === maximum ? `伤害 -${minimum}` : `伤害 -${minimum}～-${maximum}`;
  }
  const resultKey = outcome.label_fields.result_keys[0];
  if (resultKey) {
    return resultKey.replaceAll('-', ' ').replaceAll('_', ' ');
  }
  return `分支 ${outcome.edge_id}`;
}

/**
 * 管理路径聚焦式状态图窗口、按需 outcomes、轻量 breadcrumb 与有界 cache。
 *
 * @param options node/group cache 的可选容量；默认分别为 12 和 8。
 * @returns Vue refs、computed 状态及启动、展开、推进、回溯和清理操作。
 */
export function useBattleExploration(options: BattleExplorationOptions = {}) {
  const nodeCache = new BoundedLruCache<BattleGraphExplorationResult>(
    options.nodeCacheCapacity ?? 12,
  );
  const groupCache = new BoundedLruCache<TransitionOutcomeResult[]>(
    options.groupCacheCapacity ?? 8,
  );

  const graphId = ref('');
  const calculationRevision = ref('');
  const expiresAt = ref<Date | null>(null);
  const current = shallowRef<BattleGraphExplorationResult | null>(null);
  const pathEntries = ref<ExplorationPathEntry[]>([]);
  const expandedGroupId = ref<string | null>(null);
  const outcomes = ref<TransitionOutcomeResult[]>([]);
  const loading = ref(false);
  const outcomesLoading = ref(false);
  const error = ref<string | null>(null);
  const expired = ref(false);
  let lifecycleVersion = 0;

  const canBacktrack = computed(() => (current.value?.cursor.steps.length ?? 0) > 0);

  /**
   * 将响应切换为唯一当前窗口，并主动卸载旧 outcomes 与兄弟分支状态。
   *
   * @param response 服务端校验后的当前探索响应。
   */
  function applyCurrent(response: BattleGraphExplorationResult): void {
    current.value = response;
    nodeCache.set(cursorKey(response.cursor), response);
    // 进入任何新窗口后都清空展开状态，模板中的 outcome 组件会被真正卸载。
    expandedGroupId.value = null;
    outcomes.value = [];
    outcomesLoading.value = false;
  }

  /**
   * 将未知异常收敛为页面错误，并稳定识别 graph TTL 过期。
   *
   * @param caught API 或本地生命周期检查抛出的错误。
   */
  function captureError(caught: unknown): void {
    if (
      caught instanceof InferenceApiError &&
      (caught.status === 410 || caught.code === 'battle_graph_expired')
    ) {
      expired.value = true;
      error.value = '状态图已过期，请重新推演。';
      return;
    }
    error.value = caught instanceof Error ? caught.message : '状态图探索失败';
  }

  /**
   * 在网络请求前检查首次响应中的本地过期时间，避免继续操作已知失效 graph。
   *
   * @returns 未过期时返回 true；已过期时写入稳定错误并返回 false。
   */
  function ensureActive(): boolean {
    if (expiresAt.value !== null && Date.now() >= expiresAt.value.getTime()) {
      expired.value = true;
      error.value = '状态图已过期，请重新推演。';
      return false;
    }
    return true;
  }

  /**
   * 清理当前 graph 的全部窗口、breadcrumb、请求状态和 cache 强引用。
   */
  function reset(): void {
    lifecycleVersion += 1;
    graphId.value = '';
    calculationRevision.value = '';
    expiresAt.value = null;
    current.value = null;
    pathEntries.value = [];
    expandedGroupId.value = null;
    outcomes.value = [];
    loading.value = false;
    outcomesLoading.value = false;
    error.value = null;
    expired.value = false;
    nodeCache.clear();
    groupCache.clear();
  }

  /**
   * 使用首次推演 handle 初始化根节点窗口；切换 graph 时先析构旧浏览状态。
   *
   * @param handle 初始推演返回的 graph ID、revision、TTL 和根 cursor。
   */
  async function start(handle: BattleExplorationResult): Promise<void> {
    reset();
    graphId.value = handle.graph_id;
    calculationRevision.value = handle.calculation_revision;
    expiresAt.value = new Date(handle.expires_at);
    const requestVersion = lifecycleVersion;
    loading.value = true;
    try {
      if (!ensureActive()) {
        return;
      }
      const response = await exploreBattleGraph(
        handle.graph_id,
        handle.calculation_revision,
        cloneCursor(handle.cursor),
      );
      if (requestVersion !== lifecycleVersion || graphId.value !== handle.graph_id) {
        return;
      }
      applyCurrent(response);
      pathEntries.value = [
        {
          depth: response.cursor.steps.length,
          nodeId: response.node.node_id,
          label: response.cursor.steps.length === 0 ? '开局' : `回合 ${response.node.turn_number}`,
        },
      ];
    } catch (caught) {
      if (requestVersion === lifecycleVersion) {
        captureError(caught);
      }
    } finally {
      if (requestVersion === lifecycleVersion) {
        loading.value = false;
      }
    }
  }

  /**
   * 展开或收起当前节点的一个 group；只有首次展开或 cache 淘汰后才请求 outcomes。
   *
   * @param groupId 当前节点 TransitionGroup 的稳定 ID。
   */
  async function toggleGroup(groupId: string): Promise<void> {
    if (current.value === null || current.value.terminal || !ensureActive()) {
      return;
    }
    if (expandedGroupId.value === groupId) {
      expandedGroupId.value = null;
      outcomes.value = [];
      outcomesLoading.value = false;
      return;
    }

    const cacheKey = `${cursorKey(current.value.cursor)}::${groupId}`;
    const cached = groupCache.get(cacheKey);
    expandedGroupId.value = groupId;
    error.value = null;
    if (cached !== undefined) {
      outcomesLoading.value = false;
      outcomes.value = cached;
      return;
    }

    const requestVersion = lifecycleVersion;
    outcomesLoading.value = true;
    outcomes.value = [];
    try {
      const response = await loadBattleTransitionGroupOutcomes(
        graphId.value,
        calculationRevision.value,
        cloneCursor(current.value.cursor),
        groupId,
      );
      // 响应若不再对应当前 cursor，说明用户已切换窗口，旧异步结果直接丢弃。
      if (
        requestVersion !== lifecycleVersion ||
        response.graph_id !== graphId.value ||
        expandedGroupId.value !== groupId ||
        current.value === null ||
        cursorKey(response.cursor) !== cursorKey(current.value.cursor)
      ) {
        return;
      }
      const nextOutcomes = response.transition_group.outcomes;
      groupCache.set(cacheKey, nextOutcomes);
      outcomes.value = nextOutcomes;
    } catch (caught) {
      if (requestVersion === lifecycleVersion && expandedGroupId.value === groupId) {
        expandedGroupId.value = null;
        outcomes.value = [];
        outcomesLoading.value = false;
        captureError(caught);
      }
    } finally {
      if (requestVersion === lifecycleVersion && expandedGroupId.value === groupId) {
        outcomesLoading.value = false;
      }
    }
  }

  /**
   * 选择一个归并 outcome，沿正式 edge 前进并压缩旧节点为轻量 breadcrumb。
   *
   * @param outcome 当前展开 group 中由服务端返回的正式 outcome。
   */
  async function advance(outcome: TransitionOutcomeResult): Promise<void> {
    if (current.value === null || current.value.terminal || !ensureActive()) {
      return;
    }
    loading.value = true;
    error.value = null;
    expandedGroupId.value = null;
    outcomes.value = [];
    outcomesLoading.value = false;
    const sourceCursor = cloneCursor(current.value.cursor);
    const requestVersion = lifecycleVersion;
    try {
      const response = await advanceBattleExploration(
        graphId.value,
        calculationRevision.value,
        sourceCursor,
        outcome.edge_id,
      );
      if (requestVersion !== lifecycleVersion || response.graph_id !== graphId.value) {
        return;
      }
      applyCurrent(response);
      pathEntries.value = [
        ...pathEntries.value,
        {
          depth: response.cursor.steps.length,
          nodeId: response.node.node_id,
          label: `回合 ${response.node.turn_number} · ${outcomeLabel(outcome)}`,
        },
      ];
    } catch (caught) {
      if (requestVersion === lifecycleVersion) {
        captureError(caught);
      }
    } finally {
      if (requestVersion === lifecycleVersion) {
        loading.value = false;
      }
    }
  }

  /**
   * 返回指定祖先深度；优先复用有界 node cache，淘汰后再调用 backtrack API。
   *
   * @param depth 目标 cursor edge 深度，0 表示根节点。
   */
  async function goToDepth(depth: number): Promise<void> {
    if (current.value === null || depth < 0 || depth >= current.value.cursor.steps.length + 1) {
      return;
    }
    if (depth === current.value.cursor.steps.length) {
      return;
    }
    if (!ensureActive()) {
      return;
    }
    expandedGroupId.value = null;
    outcomes.value = [];
    outcomesLoading.value = false;

    const targetCursor: ExplorationCursorResult = {
      steps: current.value.cursor.steps.slice(0, depth).map((step) => ({ ...step })),
    };
    const cached = nodeCache.get(cursorKey(targetCursor));
    const requestVersion = lifecycleVersion;
    loading.value = true;
    error.value = null;
    try {
      const response =
        cached ??
        (await backtrackBattleExploration(
          graphId.value,
          calculationRevision.value,
          cloneCursor(current.value.cursor),
          depth,
        ));
      if (requestVersion !== lifecycleVersion || response.graph_id !== graphId.value) {
        return;
      }
      applyCurrent(response);
      pathEntries.value = pathEntries.value.slice(0, depth + 1);
      const lastEntry = pathEntries.value[depth];
      if (lastEntry === undefined || lastEntry.nodeId !== response.node.node_id) {
        pathEntries.value[depth] = {
          depth,
          nodeId: response.node.node_id,
          label: depth === 0 ? '开局' : `回合 ${response.node.turn_number}`,
        };
      }
    } catch (caught) {
      if (requestVersion === lifecycleVersion) {
        captureError(caught);
      }
    } finally {
      if (requestVersion === lifecycleVersion) {
        loading.value = false;
      }
    }
  }

  /** 返回当前 cursor 的上一级；根节点调用不会发起请求。 */
  async function back(): Promise<void> {
    const depth = current.value?.cursor.steps.length ?? 0;
    if (depth === 0) {
      return;
    }
    await goToDepth(depth - 1);
  }

  onScopeDispose(reset);

  return {
    graphId,
    calculationRevision,
    current,
    pathEntries,
    expandedGroupId,
    outcomes,
    loading,
    outcomesLoading,
    error,
    expired,
    canBacktrack,
    start,
    toggleGroup,
    advance,
    goToDepth,
    back,
    reset,
  };
}
