import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { exploreBattleGraph, type BattleExplorationResult } from '../../api/inference';
import {
  listWinningPathGroups,
  type WinningPathGroupsResult,
} from '../../api/winningPaths';
import WinningPathGroupsPanel from './WinningPathGroupsPanel.vue';

vi.mock('../../api/inference', () => ({
  exploreBattleGraph: vi.fn(),
}));

vi.mock('../../api/winningPaths', () => ({
  listWinningPathGroups: vi.fn(),
}));

const HANDLE: BattleExplorationResult = {
  root_node_id: 0,
  graph_id: 'graph-91',
  calculation_revision: 'revision-91',
  expires_at: '2026-07-25T12:00:00+00:00',
  cursor: { steps: [] },
  expandable: true,
};

const PROBABILITY = {
  numerator: '1',
  denominator: '2',
  decimal: 0.5,
  percent: 50,
};

/**
 * 构造组件测试使用的单页胜利路径响应。
 *
 * @returns 包含配置、路径组、前缀树和下一页游标的稳定 API DTO。
 */
function page(): WinningPathGroupsResult {
  const action = {
    turn_number: 1,
    attacker_move_id: 280,
    defender_move_id: 8,
    attacker_source_identifier: 'policy',
    defender_source_identifier: 'policy',
    ambiguous: false,
    alternatives: [
      {
        attacker_move_id: 280,
        defender_move_id: 8,
        attacker_source_identifier: 'policy',
        defender_source_identifier: 'policy',
      },
    ],
  };
  return {
    graph_id: HANDLE.graph_id,
    calculation_revision: HANDLE.calculation_revision,
    winner: 'attacker',
    sort: 'shortest-high-probability',
    configuration: {
      configuration_key: 'cfg-test',
      attacker: {
        pokemon_id: 149,
        name: '快龙',
        level: 50,
        ability_identifier: 'multiscale',
        item_identifier: 'none',
        move_ids: [280],
      },
      defender: {
        pokemon_id: 461,
        name: '玛纽拉',
        level: 50,
        ability_identifier: 'pressure',
        item_identifier: 'none',
        move_ids: [8],
      },
    },
    winner_probability: PROBABILITY,
    returned_probability: PROBABILITY,
    returned_coverage: {
      numerator: '1',
      denominator: '1',
      decimal: 1,
      percent: 100,
    },
    path_groups: [
      {
        path_key: 'wp-test',
        terminal_turn: 2,
        probability: PROBABILITY,
        raw_path_count: 2,
        raw_history_count_estimate: 4,
        terminal_reasons: ['knockout'],
        terminal_node_ids: [4],
        actions: [action],
        representative_path: [
          { source_node_id: 0, edge_id: 3, target_node_id: 4 },
        ],
        damage_values: [84, 85],
        attacker_remaining_hp_values: [40],
        defender_remaining_hp_values: [0],
        key_events: [
          {
            kind: 'fainted',
            actor: 'defender',
            target: null,
            move_id: null,
            source_identifier: 'damage',
          },
        ],
      },
    ],
    prefix_tree: {
      prefix_key: 'root',
      depth: 0,
      action: null,
      probability: PROBABILITY,
      raw_path_count: 2,
      terminal_path_keys: [],
      children: [
        {
          prefix_key: 'prefix-1',
          depth: 1,
          action,
          probability: PROBABILITY,
          raw_path_count: 2,
          terminal_path_keys: ['wp-test'],
          children: [],
        },
      ],
    },
    cycle_references: [],
    next_cursor: null,
    has_more: false,
    query_complete: true,
    traversal_truncated: false,
  };
}

describe('WinningPathGroupsPanel', () => {
  beforeEach(() => {
    vi.mocked(listWinningPathGroups).mockReset();
    vi.mocked(exploreBattleGraph).mockReset();
    vi.mocked(listWinningPathGroups).mockResolvedValue(page());
    vi.mocked(exploreBattleGraph).mockResolvedValue({
      graph_id: HANDLE.graph_id,
      calculation_revision: HANDLE.calculation_revision,
      cursor: { steps: [{ source_node_id: 0, edge_id: 3, target_node_id: 4 }] },
      node: {
        node_id: 4,
        turn_number: 2,
        phase: 'terminal',
        outcome: 'attacker-win',
        termination_reason: 'knockout',
        attacker: {
          pokemon_id: 149,
          name: '快龙',
          ability: 'multiscale',
          item: 'none',
          current_hp: 40,
          max_hp: 166,
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
          last_move_id: 280,
          choice_lock_move_id: null,
          item_consumed: false,
          first_turn: false,
        },
        defender: {
          pokemon_id: 461,
          name: '玛纽拉',
          ability: 'pressure',
          item: 'none',
          current_hp: 0,
          max_hp: 145,
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
          last_move_id: 8,
          choice_lock_move_id: null,
          item_consumed: false,
          first_turn: false,
        },
        field: {
          weather: null,
          terrain: null,
          attacker_side_conditions: {
            reflect: false,
            light_screen: false,
            aurora_veil: false,
          },
          defender_side_conditions: {
            reflect: false,
            light_screen: false,
            aurora_veil: false,
          },
        },
        terminal: true,
        has_outgoing_edges: false,
      },
      transition_groups: [],
      cumulative_probability: PROBABILITY,
      breadcrumbs: [{ source_node_id: 0, edge_id: 3, target_node_id: 4 }],
      battle_report: {
        graph_id: HANDLE.graph_id,
        calculation_revision: HANDLE.calculation_revision,
        root_node_id: 0,
        current_node_id: 4,
        depth: 1,
        cumulative_probability: PROBABILITY,
        steps: [],
      },
      terminal: true,
    });
  });

  it('loads configuration, compact prefix tree and expandable random details', async () => {
    /** 默认首页使用 10 条上限；伤害与 HP 只在用户展开后出现。 */
    const wrapper = mount(WinningPathGroupsPanel, {
      props: {
        handle: HANDLE,
        winner: 'attacker',
        moveNames: { 280: '劈瓦', 8: '冰冻拳' },
      },
    });
    await flushPromises();

    expect(listWinningPathGroups).toHaveBeenCalledWith(
      HANDLE.graph_id,
      HANDLE.calculation_revision,
      'attacker',
    );
    expect(wrapper.text()).toContain('快龙');
    expect(wrapper.text()).toContain('劈瓦');
    expect(wrapper.text()).toContain('第 2 回合终局');
    expect(wrapper.text()).not.toContain('84');

    await wrapper.get('.winning-path-row__buttons button').trigger('click');
    expect(wrapper.text()).toContain('84');
    expect(wrapper.text()).toContain('85');
    expect(wrapper.text()).toContain('fainted');
  });

  it('locates the representative cursor back to a real graph node', async () => {
    /** 定位按钮把后端代表 edge 序列提交给既有 explore API。 */
    const wrapper = mount(WinningPathGroupsPanel, {
      props: {
        handle: HANDLE,
        winner: 'attacker',
        moveNames: { 280: '劈瓦', 8: '冰冻拳' },
      },
    });
    await flushPromises();

    await wrapper.findAll('.winning-path-row__buttons button')[1]?.trigger('click');
    await flushPromises();

    expect(exploreBattleGraph).toHaveBeenCalledWith(
      HANDLE.graph_id,
      HANDLE.calculation_revision,
      { steps: [{ source_node_id: 0, edge_id: 3, target_node_id: 4 }] },
    );
    expect(wrapper.text()).toContain('已定位 node #4');
    expect(wrapper.text()).toContain('attacker-win');
  });
});
