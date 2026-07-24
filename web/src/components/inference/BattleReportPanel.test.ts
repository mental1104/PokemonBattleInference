import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import type {
  BattleEventDetailResult,
  BattleReportResult,
} from '../../api/inference';
import type { BattleReportPresenterContext } from '../../presenters/battleEventPresenter';
import BattleReportPanel from './BattleReportPanel.vue';

const CONTEXT: BattleReportPresenterContext = {
  sides: {
    attacker: { name: '快龙', maxHp: 166 },
    defender: { name: '玛纽拉', maxHp: 145 },
  },
  moveNames: { 8: '冰冻拳', 280: '劈瓦' },
};

/**
 * 构造测试使用的结构化事件。
 *
 * @param turnNumber 事件所属回合。
 * @param kind 招式使用或 HP 变化事件。
 * @param afterValue HP 变化后的值；招式事件传 null。
 * @returns 可供战报 presenter 使用的事件 DTO。
 */
function event(
  turnNumber: number,
  kind: 'move-used' | 'hp-changed',
  afterValue: number | null,
): BattleEventDetailResult {
  return {
    kind,
    turn_number: turnNumber,
    actor: 'defender',
    target: 'attacker',
    move_id: 8,
    source_identifier: null,
    value: afterValue === null ? null : -1,
    before_value: afterValue === null ? null : afterValue + 1,
    after_value: afterValue,
  };
}

/**
 * 构造允许 target node 回到 root 的两步 cursor report。
 *
 * @param depth 当前 cursor 深度；1 模拟回退结果，2 模拟循环回边。
 * @returns 与 depth 同步截断 steps 的结构化 report。
 */
function report(depth: 1 | 2): BattleReportResult {
  const firstProbability = { numerator: '1', denominator: '2', decimal: 0.5, percent: 50 };
  const secondProbability = { numerator: '1', denominator: '6', decimal: 1 / 6, percent: 100 / 6 };
  const steps = [
    {
      depth: 1,
      source_node_id: 0,
      edge_id: 10,
      target_node_id: 1,
      edge_probability: firstProbability,
      cumulative_probability: firstProbability,
      event_paths: [{
        random_results: [],
        damage_rolls: [],
        battle_events: [event(1, 'move-used', null), event(1, 'hp-changed', 109)],
      }],
    },
    {
      depth: 2,
      source_node_id: 1,
      edge_id: 11,
      target_node_id: 0,
      edge_probability: { numerator: '1', denominator: '3', decimal: 1 / 3, percent: 100 / 3 },
      cumulative_probability: secondProbability,
      event_paths: [{
        random_results: [],
        damage_rolls: [],
        battle_events: [
          { ...event(2, 'move-used', null), actor: 'attacker', target: 'defender', move_id: 280 },
          { ...event(2, 'hp-changed', 81), actor: 'attacker', target: 'defender', move_id: 280, before_value: 145, value: -64 },
        ],
      }],
    },
  ];

  return {
    graph_id: 'graph-cycle',
    calculation_revision: 'battle-inference.summary-exploration.v1',
    root_node_id: 0,
    current_node_id: depth === 1 ? 1 : 0,
    depth,
    cumulative_probability: depth === 1 ? firstProbability : secondProbability,
    steps: steps.slice(0, depth),
  };
}

describe('BattleReportPanel', () => {
  it('keeps the current turn expanded, history collapsible and exact probability strings intact', async () => {
    /**
     * 精确概率直接展示分子分母；历史回合默认折叠，当前回合默认展开。
     */
    const wrapper = mount(BattleReportPanel, {
      props: { report: report(2), context: CONTEXT },
    });

    expect(wrapper.text()).toContain('1 / 6');
    expect(wrapper.find('[data-bounded-report-scroll]').exists()).toBe(true);
    const turns = wrapper.findAll('.battle-report-turn');
    expect(turns).toHaveLength(2);
    expect(turns[0]?.get('button').attributes('aria-expanded')).toBe('false');
    expect(turns[1]?.get('button').attributes('aria-expanded')).toBe('true');
    expect(wrapper.text()).toContain('快龙使用了劈瓦！');

    await turns[0]?.get('button').trigger('click');
    expect(turns[0]?.get('button').attributes('aria-expanded')).toBe('true');
  });

  it('removes later report lines after backtrack and preserves repeated-node cycle steps', async () => {
    /**
     * current_node_id 再次为 root 时仍保留两条真实 edge；服务端回退 report 替换后第二回合消失。
     */
    const wrapper = mount(BattleReportPanel, {
      props: { report: report(2), context: CONTEXT },
    });

    expect(wrapper.findAll('.battle-report-turn')).toHaveLength(2);
    expect(wrapper.text()).toContain('回合 2');

    await wrapper.setProps({ report: report(1) });

    expect(wrapper.findAll('.battle-report-turn')).toHaveLength(1);
    expect(wrapper.text()).not.toContain('回合 2');
    expect(wrapper.text()).toContain('1 / 2');
  });
});
