import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  InferenceApiError,
  advanceBattleExploration,
  backtrackBattleExploration,
  exploreBattleGraph,
  loadBattleTransitionGroupOutcomes,
  type BattleExplorationResult,
  type BattleGraphExplorationResult,
  type BattleNodeDetailResult,
  type BattleTransitionGroupOutcomesResult,
  type ExplorationCursorResult,
  type ProbabilityResult,
  type TransitionGroupResult,
  type TransitionOutcomeResult,
} from '../../api/inference';
import { BoundedLruCache } from '../../composables/useBattleExploration';
import BattleGraphExplorer from './BattleGraphExplorer.vue';

vi.mock('../../api/inference', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/inference')>();
  return {
    ...actual,
    exploreBattleGraph: vi.fn(),
    loadBattleTransitionGroupOutcomes: vi.fn(),
    advanceBattleExploration: vi.fn(),
    backtrackBattleExploration: vi.fn(),
  };
});

const exploreMock = vi.mocked(exploreBattleGraph);
const outcomesMock = vi.mocked(loadBattleTransitionGroupOutcomes);
const advanceMock = vi.mocked(advanceBattleExploration);
const backtrackMock = vi.mocked(backtrackBattleExploration);

/**
 * 构造测试使用的精确概率 DTO。
 *
 * @param numerator 分子。
 * @param denominator 分母。
 * @returns 同时包含精确字符串和展示百分比的概率。
 */
function probability(numerator = 1, denominator = 1): ProbabilityResult {
  const decimal = numerator / denominator;
  return {
    numerator: String(numerator),
    denominator: String(denominator),
    decimal,
    percent: decimal * 100,
  };
}

/**
 * 根据路径深度生成真实 edge sequence cursor。
 *
 * @param depth 已选择 edge 数量。
 * @param repeatRoot 是否让所有 target 都回到 root，用于循环回边测试。
 * @returns 保留步骤顺序的 cursor。
 */
function cursor(depth: number, repeatRoot = false): ExplorationCursorResult {
  return {
    steps: Array.from({ length: depth }, (_, index) => ({
      source_node_id: repeatRoot ? 0 : index,
      edge_id: index + 1,
      target_node_id: repeatRoot ? 0 : index + 1,
    })),
  };
}

/**
 * 构造当前节点 DTO，字段覆盖浏览器卡片需要的完整 HTTP 合同。
 *
 * @param nodeId 节点 ID。
 * @param turnNumber 当前回合号。
 * @param terminal 是否终局。
 * @returns 可用于渐进响应的节点快照。
 */
function node(nodeId: number, turnNumber: number, terminal = false): BattleNodeDetailResult {
  const battler = (name: string, hp: number) => ({
    pokemon_id: name === 'dragonite' ? 149 : 461,
    name,
    ability: name === 'dragonite' ? 'multiscale' : 'pressure',
    item: 'none',
    current_hp: hp,
    max_hp: name === 'dragonite' ? 166 : 145,
    moves: [],
    major_status: null,
    volatile_statuses: [],
    stat_stages: {
      attack: 0,
      defense: 0,
      special_attack: 0,
      special_defense: 0,
      speed: 0,
      accuracy: 0,
      evasion: 0,
    },
    last_move_id: null,
    choice_lock_move_id: null,
    item_consumed: false,
    first_turn: turnNumber === 1,
  });
  return {
    node_id: nodeId,
    turn_number: turnNumber,
    phase: terminal ? 'terminal' : 'action-selection',
    outcome: terminal ? 'attacker-win' : 'non-terminal',
    termination_reason: terminal ? 'defender fainted' : null,
    attacker: battler('dragonite', 166 - Math.min(turnNumber - 1, 5) * 10),
    defender: battler('weavile', terminal ? 0 : 145 - Math.min(turnNumber - 1, 5) * 12),
    field: {
      weather: null,
      terrain: null,
      attacker_side_conditions: { reflect: false, light_screen: false, aurora_veil: false },
      defender_side_conditions: { reflect: false, light_screen: false, aurora_veil: false },
    },
    terminal,
    has_outgoing_edges: !terminal,
  };
}

/**
 * 构造默认收起的伤害随机分支组。
 *
 * @param depth 当前路径深度，用于生成稳定 group ID。
 * @returns 16 条原始档归并为两个目标状态的 group 摘要。
 */
function group(depth: number): TransitionGroupResult {
  return {
    group_id: `damage-${depth}`,
    kind: 'damage_roll',
    label_key: 'damage-roll',
    probability: probability(),
    raw_result_count: 16,
    distinct_outcome_count: 2,
    summary: {
      minimum_damage: 70,
      maximum_damage: 85,
      minimum_hp_loss: 70,
      maximum_hp_loss: 85,
    },
    expanded: false,
    outcomes: [],
  };
}

/**
 * 构造一个已经按目标状态归并的正式 outcome。
 *
 * @param edgeId 正式 edge ID。
 * @param targetNodeId 目标节点 ID。
 * @param rawValues 归入该目标状态的原始随机值。
 * @returns 包含次级 raw roll 说明的 outcome。
 */
function outcome(
  edgeId: number,
  targetNodeId: number,
  rawValues: number[] = [85, 86, 87, 88, 89, 90, 91, 92],
): TransitionOutcomeResult {
  return {
    edge_id: edgeId,
    target_node_id: targetNodeId,
    probability: probability(1, 2),
    cumulative_probability: probability(1, 2),
    label_fields: {
      selected_move_ids: [8],
      acting_sides: ['defender'],
      target_sides: ['attacker'],
      result_keys: ['damage'],
      source_identifiers: ['ice_punch'],
    },
    raw_random_values: rawValues,
    random_results: [],
    damage_rolls: rawValues.map((rawValue, index) => ({
      raw_roll_index: index,
      raw_roll_value: rawValue,
      final_damage: 70 + index,
      actual_hp_loss: 70 + index,
    })),
    battle_event_paths: [],
    event_paths: [],
  };
}

/**
 * 构造服务端校验后的当前探索窗口。
 *
 * @param depth 当前 cursor 深度。
 * @param options 可覆盖节点 ID、终局状态和循环 cursor。
 * @returns 默认只包含一个收起 group 的响应。
 */
function exploration(
  depth: number,
  options: { nodeId?: number; terminal?: boolean; repeatRoot?: boolean; graphId?: string } = {},
): BattleGraphExplorationResult {
  const currentCursor = cursor(depth, options.repeatRoot ?? false);
  const nodeId = options.nodeId ?? depth;
  const terminal = options.terminal ?? false;
  return {
    graph_id: options.graphId ?? 'graph-1',
    calculation_revision: 'battle-inference.summary-exploration.v1',
    cursor: currentCursor,
    node: node(nodeId, depth + 1, terminal),
    transition_groups: terminal ? [] : [group(depth)],
    cumulative_probability: probability(1, Math.max(1, 2 ** depth)),
    breadcrumbs: currentCursor.steps,
    battle_report: {
      graph_id: options.graphId ?? 'graph-1',
      calculation_revision: 'battle-inference.summary-exploration.v1',
      root_node_id: 0,
      current_node_id: nodeId,
      depth,
      cumulative_probability: probability(1, Math.max(1, 2 ** depth)),
      steps: [],
    },
    terminal,
  };
}

/**
 * 构造首次推演返回的可探索 graph handle。
 *
 * @param graphId graph 生命周期标识。
 * @returns 未来一小时过期的根 cursor handle。
 */
function handle(graphId = 'graph-1'): BattleExplorationResult {
  return {
    root_node_id: 0,
    graph_id: graphId,
    calculation_revision: 'battle-inference.summary-exploration.v1',
    expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    cursor: { steps: [] },
    expandable: true,
  };
}

/**
 * 构造单个 group outcomes 窄响应。
 *
 * @param current 当前探索窗口。
 * @param items 已按目标状态归并的 outcomes。
 * @returns 与当前 cursor 同步的 group 响应。
 */
function outcomesResponse(
  current: BattleGraphExplorationResult,
  items: TransitionOutcomeResult[],
): BattleTransitionGroupOutcomesResult {
  return {
    graph_id: current.graph_id,
    calculation_revision: current.calculation_revision,
    cursor: current.cursor,
    current_node_id: current.node.node_id,
    cumulative_probability: current.cumulative_probability,
    transition_group: {
      ...current.transition_groups[0],
      expanded: true,
      outcomes: items,
    },
  };
}

beforeEach(() => {
  exploreMock.mockReset();
  outcomesMock.mockReset();
  advanceMock.mockReset();
  backtrackMock.mockReset();
});

describe('BattleGraphExplorer', () => {
  it('keeps groups collapsed and loads only grouped outcomes after explicit expansion', async () => {
    const root = exploration(0);
    exploreMock.mockResolvedValue(root);
    outcomesMock.mockResolvedValue(
      outcomesResponse(root, [outcome(1, 1), outcome(2, 2, [93, 94, 95, 96, 97, 98, 99, 100])]),
    );

    const wrapper = mount(BattleGraphExplorer, { props: { handle: handle() } });
    await flushPromises();

    expect(outcomesMock).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('16 条原始路径');
    expect(wrapper.text()).toContain('2 个目标状态');
    expect(wrapper.find('[data-testid="transition-outcome-list"]').exists()).toBe(false);

    await wrapper.get('[data-group-id="damage-0"]').trigger('click');
    await flushPromises();

    expect(outcomesMock).toHaveBeenCalledTimes(1);
    expect(wrapper.findAll('[data-edge-id]')).toHaveLength(2);
    expect(wrapper.text()).toContain('原始随机值 85 / 86 / 87 / 88 / 89 / 90 / 91 / 92');
  });

  it('advances through one outcome, unmounts old sibling outcomes, and restores a cached ancestor', async () => {
    const root = exploration(0);
    const next = exploration(1);
    exploreMock.mockResolvedValue(root);
    outcomesMock.mockResolvedValue(outcomesResponse(root, [outcome(1, 1), outcome(2, 2)]));
    advanceMock.mockResolvedValue(next);

    const wrapper = mount(BattleGraphExplorer, { props: { handle: handle() } });
    await flushPromises();
    await wrapper.get('[data-group-id="damage-0"]').trigger('click');
    await flushPromises();
    await wrapper.get('[data-edge-id="1"]').trigger('click');
    await flushPromises();

    expect(advanceMock).toHaveBeenCalledWith('graph-1', expect.any(String), { steps: [] }, 1);
    expect(wrapper.findAll('[data-testid="battle-current-node"]')).toHaveLength(1);
    expect(wrapper.find('[data-testid="transition-outcome-list"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('当前节点 · #1');
    expect(wrapper.findAll('.battle-graph-explorer__breadcrumb')).toHaveLength(2);

    await wrapper.get('[data-depth="0"]').trigger('click');
    await flushPromises();

    expect(backtrackMock).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain('当前节点 · #0');
    expect(wrapper.findAll('.battle-graph-explorer__breadcrumb')).toHaveLength(1);
  });

  it('keeps repeated node IDs as distinct path steps for cycle back-edges', async () => {
    const root = exploration(0, { nodeId: 0, repeatRoot: true });
    const cycleOne = exploration(1, { nodeId: 0, repeatRoot: true });
    const cycleTwo = exploration(2, { nodeId: 0, repeatRoot: true });
    exploreMock.mockResolvedValue(root);
    outcomesMock.mockImplementation(async (_graphId, _revision, currentCursor) => {
      const depth = currentCursor.steps.length;
      const current = depth === 0 ? root : cycleOne;
      return outcomesResponse(current, [outcome(depth + 1, 0)]);
    });
    advanceMock.mockResolvedValueOnce(cycleOne).mockResolvedValueOnce(cycleTwo);

    const wrapper = mount(BattleGraphExplorer, { props: { handle: handle() } });
    await flushPromises();
    for (const depth of [0, 1]) {
      await wrapper.get(`[data-group-id="damage-${depth}"]`).trigger('click');
      await flushPromises();
      await wrapper.get(`[data-edge-id="${depth + 1}"]`).trigger('click');
      await flushPromises();
    }

    const breadcrumbs = wrapper.findAll('.battle-graph-explorer__breadcrumb');
    expect(breadcrumbs).toHaveLength(3);
    expect(breadcrumbs.map((item) => item.text()).filter((text) => text.includes('node #0'))).toHaveLength(3);
    expect(wrapper.text()).toContain('STEP 2');
  });

  it('bounds rendered DOM after many advances while retaining pageable ancestor navigation', async () => {
    exploreMock.mockResolvedValue(exploration(0));
    outcomesMock.mockImplementation(async (_graphId, _revision, currentCursor) => {
      const depth = currentCursor.steps.length;
      return outcomesResponse(exploration(depth), [outcome(depth + 1, depth + 1)]);
    });
    advanceMock.mockImplementation(async (_graphId, _revision, currentCursor) =>
      exploration(currentCursor.steps.length + 1),
    );

    const wrapper = mount(BattleGraphExplorer, { props: { handle: handle() } });
    await flushPromises();
    for (let depth = 0; depth < 12; depth += 1) {
      await wrapper.get(`[data-group-id="damage-${depth}"]`).trigger('click');
      await flushPromises();
      await wrapper.get(`[data-edge-id="${depth + 1}"]`).trigger('click');
      await flushPromises();
    }

    expect(wrapper.findAll('[data-testid="exploration-window"]')).toHaveLength(1);
    expect(wrapper.findAll('[data-testid="battle-current-node"]')).toHaveLength(1);
    expect(wrapper.findAll('.transition-group-card')).toHaveLength(1);
    expect(wrapper.findAll('[data-edge-id]')).toHaveLength(0);
    expect(wrapper.findAll('.battle-graph-explorer__breadcrumb').length).toBeLessThanOrEqual(7);
    expect(wrapper.find('[aria-label="查看更早祖先"]').exists()).toBe(true);
  });

  it('clears the old graph window when a new inference handle is supplied', async () => {
    const rootOne = exploration(0, { graphId: 'graph-1' });
    const rootTwo = exploration(0, { graphId: 'graph-2', nodeId: 20 });
    exploreMock.mockResolvedValueOnce(rootOne).mockResolvedValueOnce(rootTwo);
    outcomesMock.mockResolvedValue(outcomesResponse(rootOne, [outcome(1, 1)]));

    const wrapper = mount(BattleGraphExplorer, { props: { handle: handle('graph-1') } });
    await flushPromises();
    await wrapper.get('[data-group-id="damage-0"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="transition-outcome-list"]').exists()).toBe(true);

    await wrapper.setProps({ handle: handle('graph-2') });
    await flushPromises();

    expect(wrapper.find('[data-testid="transition-outcome-list"]').exists()).toBe(false);
    expect(wrapper.text()).toContain('当前节点 · #20');
    expect(wrapper.findAll('.battle-graph-explorer__breadcrumb')).toHaveLength(1);
  });

  it('shows a rerun action when the graph store reports expiration', async () => {
    exploreMock.mockRejectedValue(
      new InferenceApiError(410, 'battle_graph_expired', 'battle graph has expired'),
    );

    const wrapper = mount(BattleGraphExplorer, { props: { handle: handle() } });
    await flushPromises();

    expect(wrapper.text()).toContain('状态图已过期');
    await wrapper.get('.battle-graph-explorer__expired button').trigger('click');
    expect(wrapper.emitted('rerun')).toHaveLength(1);
  });
});

describe('BoundedLruCache', () => {
  it('evicts the least recently used entry and never exceeds its fixed capacity', () => {
    const cache = new BoundedLruCache<number>(2);
    cache.set('root', 0);
    cache.set('step-1', 1);
    expect(cache.get('root')).toBe(0);
    cache.set('step-2', 2);

    expect(cache.size).toBe(2);
    expect(cache.get('step-1')).toBeUndefined();
    expect(cache.get('root')).toBe(0);
    expect(cache.get('step-2')).toBe(2);
  });
});
