import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  advanceBattleExploration,
  backtrackBattleExploration,
  exploreBattleGraph,
  inferDragoniteVsWeavile,
  loadTransitionGroupOutcomes,
  type BattleEventResult,
  type BattleGraphExplorationResult,
  type BattleJourneyResult,
  type BattleReportStepResult,
  type BattleTransitionGroupOutcomesResult,
  type ProbabilityResult,
  type TransitionGroupResult,
} from '../api/inference';
import BattleInferenceView from './BattleInferenceView.vue';

vi.mock('../api/inference', () => ({
  inferDragoniteVsWeavile: vi.fn(),
  exploreBattleGraph: vi.fn(),
  loadTransitionGroupOutcomes: vi.fn(),
  advanceBattleExploration: vi.fn(),
  backtrackBattleExploration: vi.fn(),
}));

const inferMock = vi.mocked(inferDragoniteVsWeavile);
const exploreMock = vi.mocked(exploreBattleGraph);
const outcomesMock = vi.mocked(loadTransitionGroupOutcomes);
const advanceMock = vi.mocked(advanceBattleExploration);
const backtrackMock = vi.mocked(backtrackBattleExploration);

/**
 * 构造同时保留精确字符串和展示近似值的概率 DTO。
 *
 * @param numerator 约分后的分子字符串。
 * @param denominator 约分后的分母字符串。
 * @param decimal 对应的展示小数。
 * @returns API 概率对象。
 */
function probability(
  numerator: string,
  denominator: string,
  decimal: number,
): ProbabilityResult {
  return {
    numerator,
    denominator,
    decimal,
    percent: decimal * 100,
  };
}

const RESULT: BattleJourneyResult = {
  summary: {
    ruleset_id: 'pokemon-champion',
    version_group_id: 25,
    observer: 'attacker',
    attacker: {
      pokemon_id: 149,
      name: 'dragonite',
      level: 50,
      ability_identifier: 'inner_focus',
      item_identifier: 'none',
      move_ids: [280],
      move_names: ['劈瓦'],
      stats: {
        hp: 166,
        attack: 204,
        defense: 115,
        special_attack: 120,
        special_defense: 120,
        speed: 100,
      },
      dimension_labels: {
        moves: '劈瓦',
        ability: 'inner_focus',
      },
    },
    defender: {
      pokemon_id: 461,
      name: 'weavile',
      level: 50,
      ability_identifier: 'pressure',
      item_identifier: 'none',
      move_ids: [8, 252],
      move_names: ['冰冻拳', '击掌奇袭'],
      stats: {
        hp: 145,
        attack: 189,
        defense: 85,
        special_attack: 65,
        special_defense: 105,
        speed: 145,
      },
      dimension_labels: {
        moves: '冰冻拳 / 击掌奇袭',
        ability: 'pressure',
      },
    },
    win_probability: probability('3', '4', 0.75),
    loss_probability: probability('1', '4', 0.25),
    draw_probability: probability('0', '1', 0),
    expected_turns: {
      available: true,
      numerator: 5,
      denominator: 2,
      decimal: 2.5,
    },
    attacker_policy: 'first-legal-action',
    defender_policy: 'uniform-random',
    graph: {
      unique_state_count: 18,
      edge_count: 36,
      max_turn_number: 4,
      closed_cycle_count: 0,
      terminal_reachable_cycle_count: 1,
      is_complete: true,
      truncation_reasons: [],
    },
    representative_paths: [
      {
        reference: 'path:attacker-win:node-7',
        outcome: 'attacker-win',
        steps: [
          {
            node_id: 0,
            turn_number: 1,
            phase: 'action-selection',
            attacker_hp: 166,
            defender_hp: 145,
            outcome: 'non-terminal',
            events: [],
          },
          {
            node_id: 7,
            turn_number: 2,
            phase: 'terminal',
            attacker_hp: 132,
            defender_hp: 0,
            outcome: 'attacker-win',
            events: ['damage_roll:roll-16:145'],
          },
        ],
      },
    ],
    included_mechanisms: [
      'move:brick_break',
      'move:fake_out',
      'ability:inner_focus',
      'ability:pressure',
    ],
    excluded_mechanisms: ['ability:pressure:real_ability_behavior'],
    configuration_coverage_percent: 100,
    completeness: {
      graph_complete: true,
      solver_status: 'solved',
      truncation_reasons: [],
      diagnostics: [],
      warnings: ['未纳入机制：ability:pressure:real_ability_behavior'],
    },
  },
  exploration: {
    root_node_id: 0,
    graph_id: 'stored-graph',
    calculation_revision: 'battle-inference.summary-exploration.v1',
    expires_at: '2026-07-24T10:30:00Z',
    cursor: { steps: [] },
    expandable: true,
  },
};

/**
 * 构造 cursor 节点一侧的完整动态状态。
 *
 * @param pokemonId Pokémon ID。
 * @param name 稳定英文 identifier。
 * @param currentHp 当前 HP。
 * @param maximumHp 最大 HP。
 * @returns 满足 exploration API 合同的 battler DTO。
 */
function battler(
  pokemonId: number,
  name: string,
  currentHp: number,
  maximumHp: number,
) {
  return {
    pokemon_id: pokemonId,
    name,
    ability: name === 'dragonite' ? 'inner_focus' : 'pressure',
    item: 'none',
    current_hp: currentHp,
    max_hp: maximumHp,
    moves: [],
    major_status: null,
    volatile_statuses: [],
    last_move_id: null,
    choice_lock_move_id: null,
    item_consumed: false,
    first_turn: false,
  };
}

/**
 * 构造一个结构化事件，供 view 断言真实 battle report 文本。
 *
 * @param patch 待覆盖的事件字段。
 * @returns 具有合法默认值的新事件。
 */
function event(patch: Partial<BattleEventResult>): BattleEventResult {
  return {
    kind: 'move-used',
    turn_number: 1,
    actor: 'defender',
    target: 'attacker',
    move_id: 8,
    source_identifier: null,
    value: null,
    before_value: null,
    after_value: null,
    ...patch,
  };
}

/**
 * 构造一条 cursor edge 对应的 report step。
 *
 * @param depth 当前路径深度。
 * @param sourceNodeId edge 起点。
 * @param edgeId 正式 edge ID。
 * @param targetNodeId edge 终点，可重复已有节点形成循环。
 * @param events 当前 edge 的结构化事件序列。
 * @returns 可直接放入 BattleReportResult.steps 的 DTO。
 */
function reportStep(
  depth: number,
  sourceNodeId: number,
  edgeId: number,
  targetNodeId: number,
  events: BattleEventResult[],
): BattleReportStepResult {
  return {
    depth,
    source_node_id: sourceNodeId,
    edge_id: edgeId,
    target_node_id: targetNodeId,
    edge_probability: probability('1', '2', 0.5),
    cumulative_probability:
      depth === 1 ? probability('1', '2', 0.5) : probability('1', '4', 0.25),
    event_paths: [
      {
        random_results: [],
        damage_rolls: [],
        battle_events: events,
      },
    ],
  };
}

const ROOT_GROUP: TransitionGroupResult = {
  group_id: 'damage-group',
  kind: 'damage-distribution',
  label_key: 'damage-distribution',
  probability: probability('1', '1', 1),
  raw_result_count: 16,
  distinct_outcome_count: 2,
  summary: {
    minimum_damage: 57,
    maximum_damage: 63,
    minimum_hp_loss: 57,
    maximum_hp_loss: 63,
  },
  expanded: false,
  outcomes: [],
};

const EXPANDED_GROUP: TransitionGroupResult = {
  ...ROOT_GROUP,
  expanded: true,
  outcomes: [
    {
      edge_id: 10,
      target_node_id: 1,
      probability: probability('1', '2', 0.5),
      cumulative_probability: probability('1', '2', 0.5),
      label_fields: {
        selected_move_ids: [8],
        acting_sides: ['defender'],
        target_sides: ['attacker'],
        result_keys: ['damage:57'],
        source_identifiers: [],
      },
      raw_random_values: [85],
      random_results: [],
      damage_rolls: [
        {
          raw_roll_index: 0,
          raw_roll_value: 85,
          final_damage: 57,
          actual_hp_loss: 57,
        },
      ],
      battle_event_paths: [],
      event_paths: [],
    },
    {
      edge_id: 12,
      target_node_id: 2,
      probability: probability('1', '2', 0.5),
      cumulative_probability: probability('1', '2', 0.5),
      label_fields: {
        selected_move_ids: [8],
        acting_sides: ['defender'],
        target_sides: ['attacker'],
        result_keys: ['damage:63'],
        source_identifiers: [],
      },
      raw_random_values: [100],
      random_results: [],
      damage_rolls: [
        {
          raw_roll_index: 15,
          raw_roll_value: 100,
          final_damage: 63,
          actual_hp_loss: 63,
        },
      ],
      battle_event_paths: [],
      event_paths: [],
    },
  ],
};

const ROOT_EXPLORATION: BattleGraphExplorationResult = {
  graph_id: 'stored-graph',
  calculation_revision: 'battle-inference.summary-exploration.v1',
  cursor: { steps: [] },
  node: {
    node_id: 0,
    turn_number: 1,
    phase: 'action-selection',
    outcome: 'non-terminal',
    termination_reason: null,
    attacker: battler(149, 'dragonite', 166, 166),
    defender: battler(461, 'weavile', 145, 145),
    terminal: false,
    has_outgoing_edges: true,
  },
  transition_groups: [ROOT_GROUP],
  cumulative_probability: probability('1', '1', 1),
  breadcrumbs: [],
  battle_report: {
    graph_id: 'stored-graph',
    calculation_revision: 'battle-inference.summary-exploration.v1',
    root_node_id: 0,
    current_node_id: 0,
    depth: 0,
    cumulative_probability: probability('1', '1', 1),
    steps: [],
  },
  terminal: false,
};

const FIRST_STEP = reportStep(1, 0, 10, 1, [
  event({ kind: 'move-used' }),
  event({
    kind: 'damage',
    value: 57,
  }),
  event({
    kind: 'hp-changed',
    before_value: 166,
    after_value: 109,
    value: -57,
  }),
]);

const ADVANCED_EXPLORATION: BattleGraphExplorationResult = {
  ...ROOT_EXPLORATION,
  cursor: {
    steps: [
      {
        source_node_id: 0,
        edge_id: 10,
        target_node_id: 1,
      },
    ],
  },
  node: {
    ...ROOT_EXPLORATION.node,
    node_id: 1,
    turn_number: 2,
    attacker: battler(149, 'dragonite', 109, 166),
  },
  transition_groups: [],
  cumulative_probability: probability('1', '2', 0.5),
  breadcrumbs: [
    {
      source_node_id: 0,
      edge_id: 10,
      target_node_id: 1,
    },
  ],
  battle_report: {
    graph_id: 'stored-graph',
    calculation_revision: 'battle-inference.summary-exploration.v1',
    root_node_id: 0,
    current_node_id: 1,
    depth: 1,
    cumulative_probability: probability('1', '2', 0.5),
    steps: [FIRST_STEP],
  },
};

const CYCLE_EXPLORATION: BattleGraphExplorationResult = {
  ...ROOT_EXPLORATION,
  cursor: {
    steps: [
      {
        source_node_id: 0,
        edge_id: 10,
        target_node_id: 1,
      },
      {
        source_node_id: 1,
        edge_id: 20,
        target_node_id: 0,
      },
    ],
  },
  node: {
    ...ROOT_EXPLORATION.node,
    node_id: 0,
    turn_number: 3,
  },
  transition_groups: [],
  cumulative_probability: probability('1', '4', 0.25),
  breadcrumbs: [
    {
      source_node_id: 0,
      edge_id: 10,
      target_node_id: 1,
    },
    {
      source_node_id: 1,
      edge_id: 20,
      target_node_id: 0,
    },
  ],
  battle_report: {
    graph_id: 'stored-graph',
    calculation_revision: 'battle-inference.summary-exploration.v1',
    root_node_id: 0,
    current_node_id: 0,
    depth: 2,
    cumulative_probability: probability('1', '4', 0.25),
    steps: [
      FIRST_STEP,
      reportStep(2, 1, 20, 0, [
        event({
          kind: 'move-used',
          turn_number: 2,
          actor: 'attacker',
          target: 'defender',
          move_id: 280,
        }),
        event({
          kind: 'damage',
          turn_number: 2,
          actor: 'attacker',
          target: 'defender',
          move_id: 280,
          value: 64,
        }),
      ]),
    ],
  },
};

const OUTCOMES_RESPONSE: BattleTransitionGroupOutcomesResult = {
  graph_id: 'stored-graph',
  calculation_revision: 'battle-inference.summary-exploration.v1',
  cursor: { steps: [] },
  current_node_id: 0,
  cumulative_probability: probability('1', '1', 1),
  transition_group: EXPANDED_GROUP,
};

beforeEach(() => {
  inferMock.mockReset().mockResolvedValue(RESULT);
  exploreMock.mockReset().mockResolvedValue(ROOT_EXPLORATION);
  outcomesMock.mockReset().mockResolvedValue(OUTCOMES_RESPONSE);
  advanceMock.mockReset().mockResolvedValue(ADVANCED_EXPLORATION);
  backtrackMock.mockReset().mockResolvedValue(ROOT_EXPLORATION);
});

describe('BattleInferenceView', () => {
  it('submits the selected journey and renders exact probability, graph and coverage results', async () => {
    /**
     * 页面必须继续完成“选择假设—提交推演—阅读全局结果”的既有闭环，同时在成功后使用
     * 同一个 graph handle 加载根 cursor。测试选择精神力与击掌奇袭方案，断言首次请求
     * 参数、根探索上下文、精确胜率、期望回合、图规模和机制缺口均未因战报接入而回退。
     */
    const wrapper = mount(BattleInferenceView);

    await wrapper.get('input[value="inner-focus"]').setValue(true);
    await wrapper.get('input[value="fake-out-pressure"]').setValue(true);
    await wrapper.get('.inference-run-button').trigger('click');
    await flushPromises();

    expect(inferMock).toHaveBeenCalledWith({
      dragonite_ability: 'inner-focus',
      weavile_plan: 'fake-out-pressure',
      dragonite_stat_preset: 'max_atk_plus',
      weavile_stat_preset: 'max_atk_plus',
    });
    expect(exploreMock).toHaveBeenCalledWith({
      graphId: 'stored-graph',
      calculationRevision: 'battle-inference.summary-exploration.v1',
      cursor: { steps: [] },
    });
    expect(wrapper.text()).toContain('75.00%');
    expect(wrapper.text()).toContain('2.50');
    expect(wrapper.text()).toContain('18');
    expect(wrapper.text()).toContain('快龙获胜路径');
    expect(wrapper.text()).toContain('ability:pressure:real_ability_behavior');
    expect(wrapper.text()).toContain('尚未选择任何路径');
  });

  it('expands a structured damage outcome, advances the cursor and keeps report state when explorer unmounts', async () => {
    /**
     * 用户从左侧展开 damage group 并选择 57 点正式 edge 后，父视图必须用 advance
     * 响应整体替换 cursor 和 battle report。断言右侧显示冰冻拳、57 点伤害和 109/166
     * HP；随后卸载左侧 explorer，右侧文本仍存在，证明 report 不绑定子组件实例。
     */
    const wrapper = mount(BattleInferenceView);
    await wrapper.get('.inference-run-button').trigger('click');
    await flushPromises();

    await wrapper.get('[data-group-id="damage-group"]').trigger('click');
    await flushPromises();
    expect(outcomesMock).toHaveBeenCalled();
    expect(wrapper.find('[data-edge-id="10"]').exists()).toBe(true);

    await wrapper.get('[data-edge-id="10"]').trigger('click');
    await flushPromises();

    expect(advanceMock).toHaveBeenCalledWith(
      {
        graphId: 'stored-graph',
        calculationRevision: 'battle-inference.summary-exploration.v1',
        cursor: { steps: [] },
      },
      10,
    );
    expect(wrapper.text()).toContain('玛纽拉使用了冰冻拳！');
    expect(wrapper.text()).toContain('快龙失去了 57 点 HP。');
    expect(wrapper.text()).toContain('快龙剩余 109 / 166 HP。');

    await wrapper.get('[data-toggle-explorer]').trigger('click');
    expect(wrapper.find('.battle-path-explorer').exists()).toBe(false);
    expect(wrapper.text()).toContain('快龙剩余 109 / 166 HP。');
  });

  it('removes report lines on backtrack and preserves actual edge order through a cycle', async () => {
    /**
     * 回退必须采用服务端截断后的 report，而不是在前端猜测删除最后一个节点；循环回边
     * 则必须保留 `0 -> 1 -> 0` 的两条真实 edge。测试先前进到循环响应，确认两个回合
     * 同时显示，再调用 backtrack 并断言所有路径事件被根 report 清空。
     */
    advanceMock.mockResolvedValueOnce(CYCLE_EXPLORATION);
    const wrapper = mount(BattleInferenceView);
    await wrapper.get('.inference-run-button').trigger('click');
    await flushPromises();
    await wrapper.get('[data-group-id="damage-group"]').trigger('click');
    await flushPromises();
    await wrapper.get('[data-edge-id="10"]').trigger('click');
    await flushPromises();

    expect(wrapper.text()).toContain('回合 1');
    expect(wrapper.text()).toContain('回合 2');
    expect(wrapper.text()).toContain('快龙使用了劈瓦！');

    await wrapper.get('[data-backtrack]').trigger('click');
    await flushPromises();

    expect(backtrackMock).toHaveBeenCalledWith(
      {
        graphId: 'stored-graph',
        calculationRevision: 'battle-inference.summary-exploration.v1',
        cursor: CYCLE_EXPLORATION.cursor,
      },
      undefined,
    );
    expect(wrapper.text()).not.toContain('快龙使用了劈瓦！');
    expect(wrapper.text()).toContain('尚未选择任何路径');
  });

  it('clears stale report when configuration changes or a new inference fails', async () => {
    /**
     * 切换特性或行动方案后，旧 cursor 战报必须立即清空；再次提交失败时也不能恢复上一条
     * 路径。测试先展示 57 点战报，切换配置后确认 summary/report 消失，再让新请求失败，
     * 断言只保留后端错误且按钮恢复可操作。
     */
    const wrapper = mount(BattleInferenceView);
    await wrapper.get('.inference-run-button').trigger('click');
    await flushPromises();
    await wrapper.get('[data-group-id="damage-group"]').trigger('click');
    await flushPromises();
    await wrapper.get('[data-edge-id="10"]').trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('快龙失去了 57 点 HP。');

    await wrapper.get('input[value="inner-focus"]').setValue(true);
    await flushPromises();
    expect(wrapper.text()).not.toContain('快龙失去了 57 点 HP。');
    expect(wrapper.text()).not.toContain('75.00%');

    inferMock.mockRejectedValueOnce(new Error('状态图超过节点上限'));
    await wrapper.get('.inference-run-button').trigger('click');
    await flushPromises();

    expect(wrapper.text()).toContain('状态图超过节点上限');
    expect(wrapper.text()).not.toContain('快龙失去了 57 点 HP。');
    expect(wrapper.get('.inference-run-button').attributes('disabled')).toBeUndefined();
  });
});
