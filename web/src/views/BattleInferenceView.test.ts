import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { defineComponent, h } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  inferDragoniteVsWeavile,
  type BattleGraphExplorationResult,
  type BattleJourneyResult,
  type ProbabilityResult,
} from '../api/inference';
import BattleInferenceView from './BattleInferenceView.vue';

vi.mock('../api/inference', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/inference')>();
  return {
    ...actual,
    inferDragoniteVsWeavile: vi.fn(),
  };
});

const inferMock = vi.mocked(inferDragoniteVsWeavile);

/**
 * 构造测试使用的精确概率 DTO。
 *
 * @param numerator 约分后的分子。
 * @param denominator 约分后的分母。
 * @param decimal 浮点近似值。
 * @returns 同时保留精确字符串和视觉近似值的概率对象。
 */
function probability(
  numerator: string,
  denominator: string,
  decimal: number,
): ProbabilityResult {
  return { numerator, denominator, decimal, percent: decimal * 100 };
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
      stats: { hp: 166, attack: 204, defense: 115, special_attack: 120, special_defense: 120, speed: 100 },
      dimension_labels: { moves: '劈瓦', ability: 'inner_focus' },
    },
    defender: {
      pokemon_id: 461,
      name: 'weavile',
      level: 50,
      ability_identifier: 'pressure',
      item_identifier: 'none',
      move_ids: [8, 252],
      move_names: ['冰冻拳', '击掌奇袭'],
      stats: { hp: 145, attack: 189, defense: 85, special_attack: 65, special_defense: 105, speed: 145 },
      dimension_labels: { moves: '冰冻拳 / 击掌奇袭', ability: 'pressure' },
    },
    win_probability: probability('3', '4', 0.75),
    loss_probability: probability('1', '4', 0.25),
    draw_probability: probability('0', '1', 0),
    expected_turns: { available: true, numerator: 5, denominator: 2, decimal: 2.5 },
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
          { node_id: 0, turn_number: 1, phase: 'action-selection', attacker_hp: 166, defender_hp: 145, outcome: 'non-terminal', events: [] },
          { node_id: 7, turn_number: 2, phase: 'terminal', attacker_hp: 132, defender_hp: 0, outcome: 'attacker-win', events: ['damage_roll:roll-16:145'] },
        ],
      },
    ],
    included_mechanisms: ['move:brick_break', 'move:fake_out', 'ability:inner_focus', 'ability:pressure'],
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

const REPORT_EXPLORATION: BattleGraphExplorationResult = {
  graph_id: 'stored-graph',
  calculation_revision: 'battle-inference.summary-exploration.v1',
  cursor: { steps: [{ source_node_id: 0, edge_id: 10, target_node_id: 1 }] },
  node: {
    node_id: 1,
    turn_number: 2,
    phase: 'action-selection',
    outcome: 'non-terminal',
    termination_reason: null,
    attacker: {
      pokemon_id: 149,
      name: 'dragonite',
      ability: 'inner_focus',
      item: 'none',
      current_hp: 109,
      max_hp: 166,
      moves: [],
      major_status: null,
      volatile_statuses: [],
      stat_stages: { attack: 0, defense: 0, special_attack: 0, special_defense: 0, speed: 0, accuracy: 0, evasion: 0 },
      last_move_id: null,
      choice_lock_move_id: null,
      item_consumed: false,
      first_turn: false,
    },
    defender: {
      pokemon_id: 461,
      name: 'weavile',
      ability: 'pressure',
      item: 'none',
      current_hp: 145,
      max_hp: 145,
      moves: [],
      major_status: null,
      volatile_statuses: [],
      stat_stages: { attack: 0, defense: 0, special_attack: 0, special_defense: 0, speed: 0, accuracy: 0, evasion: 0 },
      last_move_id: 8,
      choice_lock_move_id: null,
      item_consumed: false,
      first_turn: false,
    },
    field: {
      weather: null,
      terrain: null,
      attacker_side_conditions: { reflect: false, light_screen: false, aurora_veil: false },
      defender_side_conditions: { reflect: false, light_screen: false, aurora_veil: false },
    },
    terminal: false,
    has_outgoing_edges: true,
  },
  transition_groups: [],
  cumulative_probability: probability('1', '2', 0.5),
  breadcrumbs: [{ source_node_id: 0, edge_id: 10, target_node_id: 1 }],
  battle_report: {
    graph_id: 'stored-graph',
    calculation_revision: 'battle-inference.summary-exploration.v1',
    root_node_id: 0,
    current_node_id: 1,
    depth: 1,
    cumulative_probability: probability('1', '2', 0.5),
    steps: [
      {
        depth: 1,
        source_node_id: 0,
        edge_id: 10,
        target_node_id: 1,
        edge_probability: probability('1', '2', 0.5),
        cumulative_probability: probability('1', '2', 0.5),
        event_paths: [{
          random_results: [],
          damage_rolls: [],
          battle_events: [
            { kind: 'move-used', turn_number: 1, actor: 'defender', target: 'attacker', move_id: 8, source_identifier: null, value: null, before_value: null, after_value: null },
            { kind: 'damage', turn_number: 1, actor: 'defender', target: 'attacker', move_id: 8, source_identifier: null, value: 57, before_value: null, after_value: null },
            { kind: 'hp-changed', turn_number: 1, actor: 'defender', target: 'attacker', move_id: 8, source_identifier: null, value: -57, before_value: 166, after_value: 109 },
          ],
        }],
      },
    ],
  },
  terminal: false,
};

/** 使用可主动上报 exploration 的轻量组件替代状态图独立交互。 */
const BattleGraphExplorerStub = defineComponent({
  name: 'BattleGraphExplorer',
  emits: ['explorationChange', 'rerun'],
  setup(_, { emit }) {
    return () => h(
      'button',
      {
        type: 'button',
        'data-emit-exploration': '',
        onClick: () => emit('explorationChange', REPORT_EXPLORATION),
      },
      '同步当前路径',
    );
  },
});

/**
 * 挂载页面并用轻量 stub 隔离状态图浏览器的独立交互测试。
 *
 * @returns 可用于选择场景、提交推演和检查战报生命周期的 Vue wrapper。
 */
function mountView(): VueWrapper {
  return mount(BattleInferenceView, {
    global: { stubs: { BattleGraphExplorer: BattleGraphExplorerStub } },
  });
}

beforeEach(() => {
  inferMock.mockReset().mockResolvedValue(RESULT);
});

describe('BattleInferenceView', () => {
  it('submits the selected journey and renders exact probability, graph and coverage results', async () => {
    /** 页面继续完成选择假设、提交推演和阅读全局结果的既有闭环。 */
    const wrapper = mountView();

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
    expect(wrapper.text()).toContain('75.00%');
    expect(wrapper.text()).toContain('2.50');
    expect(wrapper.text()).toContain('18');
    expect(wrapper.text()).toContain('快龙获胜路径');
    expect(wrapper.text()).toContain('ability:pressure:real_ability_behavior');
    expect(wrapper.findComponent({ name: 'BattleGraphExplorer' }).exists()).toBe(true);
    expect(wrapper.text()).toContain('尚未选择任何路径');
  });

  it('keeps report DTO after GraphExplorer unmount and clears it before rerun', async () => {
    /**
     * 父页面持有 battle_report，因此隐藏左侧 GraphExplorer 后历史战报仍存在；新推演开始时再统一清空。
     */
    const wrapper = mountView();
    await wrapper.get('.inference-run-button').trigger('click');
    await flushPromises();
    await wrapper.get('[data-emit-exploration]').trigger('click');

    expect(wrapper.text()).toContain('玛纽拉使用了冰冻拳！');
    expect(wrapper.text()).toContain('快龙失去了 57 点 HP。');
    expect(wrapper.text()).toContain('快龙剩余 109 / 166 HP。');

    await wrapper.get('[data-toggle-graph-explorer]').trigger('click');
    expect(wrapper.findComponent({ name: 'BattleGraphExplorer' }).exists()).toBe(false);
    expect(wrapper.text()).toContain('快龙剩余 109 / 166 HP。');

    inferMock.mockRejectedValueOnce(new Error('状态图超过节点上限'));
    await wrapper.get('.inference-run-button').trigger('click');
    await flushPromises();

    expect(wrapper.text()).not.toContain('快龙剩余 109 / 166 HP。');
    expect(wrapper.text()).not.toContain('75.00%');
    expect(wrapper.text()).toContain('状态图超过节点上限');
    expect(wrapper.get('.inference-run-button').attributes('disabled')).toBeUndefined();
  });
});
