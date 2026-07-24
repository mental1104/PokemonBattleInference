import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  inferDragoniteVsWeavile,
  type BattleJourneyResult,
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
    win_probability: {
      numerator: '3',
      denominator: '4',
      decimal: 0.75,
      percent: 75,
    },
    loss_probability: {
      numerator: '1',
      denominator: '4',
      decimal: 0.25,
      percent: 25,
    },
    draw_probability: {
      numerator: '0',
      denominator: '1',
      decimal: 0,
      percent: 0,
    },
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
 * 挂载页面并用轻量 stub 隔离状态图浏览器的独立交互测试。
 *
 * @returns 可用于选择场景、提交推演和检查 summary 的 Vue wrapper。
 */
function mountView(): VueWrapper {
  return mount(BattleInferenceView, {
    global: {
      stubs: {
        BattleGraphExplorer: true,
      },
    },
  });
}

beforeEach(() => {
  inferMock.mockReset().mockResolvedValue(RESULT);
});

describe('BattleInferenceView', () => {
  it('submits the selected journey and renders exact probability, graph and coverage results', async () => {
    /**
     * 页面必须作为独立用户旅程完成“选择假设—提交推演—阅读结果”的闭环，而不是复用单次伤害计算器的局部状态。测试先选择精神力与击掌奇袭施压方案，再点击完整推演按钮；随后断言请求携带稳定 identifier 和双方预设，并验证返回的胜率、期望回合、状态图规模、代表性路径以及未实现压迫感真实行为都进入页面。
     */
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
  });

  it('clears stale results before rerun and exposes backend errors', async () => {
    /**
     * 请求开始时先卸载旧 explorer，防止旧 graph cache 与新场景并存。测试先完成成功推演，再让下一次请求失败；断言旧胜率和 explorer 均被清除，服务端错误文本进入页面，同时按钮恢复可操作状态。
     */
    const wrapper = mountView();
    await wrapper.get('.inference-run-button').trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('75.00%');

    inferMock.mockRejectedValueOnce(new Error('状态图超过节点上限'));
    await wrapper.get('.inference-run-button').trigger('click');
    await flushPromises();

    expect(wrapper.text()).not.toContain('75.00%');
    expect(wrapper.findComponent({ name: 'BattleGraphExplorer' }).exists()).toBe(false);
    expect(wrapper.text()).toContain('状态图超过节点上限');
    expect(wrapper.get('.inference-run-button').attributes('disabled')).toBeUndefined();
  });
});
