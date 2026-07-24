import { describe, expect, it, vi } from 'vitest';
import type {
  BattleEventResult,
  BattleInferenceSummaryResult,
  BattleReportResult,
} from '../api/inference';
import {
  createBattleReportPresenterContext,
  presentBattleEvent,
  presentBattleReport,
} from './battleEventPresenter';

const SUMMARY: BattleInferenceSummaryResult = {
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
    dimension_labels: {},
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
    dimension_labels: {},
  },
  win_probability: {
    numerator: '1',
    denominator: '2',
    decimal: 0.5,
    percent: 50,
  },
  loss_probability: {
    numerator: '1',
    denominator: '2',
    decimal: 0.5,
    percent: 50,
  },
  draw_probability: {
    numerator: '0',
    denominator: '1',
    decimal: 0,
    percent: 0,
  },
  expected_turns: {
    available: true,
    numerator: 2,
    denominator: 1,
    decimal: 2,
  },
  attacker_policy: 'first-legal-action',
  defender_policy: 'uniform-random',
  graph: {
    unique_state_count: 4,
    edge_count: 5,
    max_turn_number: 2,
    closed_cycle_count: 0,
    terminal_reachable_cycle_count: 0,
    is_complete: true,
    truncation_reasons: [],
  },
  representative_paths: [],
  included_mechanisms: [],
  excluded_mechanisms: [],
  configuration_coverage_percent: 100,
  completeness: {
    graph_complete: true,
    solver_status: 'solved',
    truncation_reasons: [],
    diagnostics: [],
    warnings: [],
  },
};

const CONTEXT = createBattleReportPresenterContext(SUMMARY);

/**
 * 构造单个结构化战斗事件，允许测试只覆盖与当前语义相关的字段。
 *
 * @param patch 待覆盖的事件字段。
 * @returns 具有合法默认值的新事件 DTO。
 */
function event(patch: Partial<BattleEventResult>): BattleEventResult {
  return {
    kind: 'move-used',
    turn_number: 1,
    actor: 'attacker',
    target: 'defender',
    move_id: 280,
    source_identifier: null,
    value: null,
    before_value: null,
    after_value: null,
    ...patch,
  };
}

/**
 * 构造一条仅包含结构化 BattleEvent 的真实 cursor report。
 *
 * @param events 服务端在同一正式 edge 上按顺序返回的事件。
 * @returns 深度为 1、精确路径概率为 1/2 的 report DTO。
 */
function report(events: BattleEventResult[]): BattleReportResult {
  return {
    graph_id: 'graph-68',
    calculation_revision: 'battle-inference.summary-exploration.v1',
    root_node_id: 0,
    current_node_id: 1,
    depth: 1,
    cumulative_probability: {
      numerator: '1',
      denominator: '2',
      decimal: 0.5,
      percent: 50,
    },
    steps: [
      {
        depth: 1,
        source_node_id: 0,
        edge_id: 7,
        target_node_id: 1,
        edge_probability: {
          numerator: '1',
          denominator: '2',
          decimal: 0.5,
          percent: 50,
        },
        cumulative_probability: {
          numerator: '1',
          denominator: '2',
          decimal: 0.5,
          percent: 50,
        },
        event_paths: [
          {
            random_results: [],
            damage_rolls: [],
            battle_events: events,
          },
        ],
      },
    ],
  };
}

describe('battleEventPresenter', () => {
  it('maps controlled journey moves, damage, HP, PP, multiscale and fainting from structured events', () => {
    /**
     * 首版 presenter 必须直接消费 BattleEvent DTO 覆盖快龙、玛纽拉、劈瓦、冰冻拳、
     * 击掌奇袭、多重鳞片、伤害、HP、PP 和濒死，而不能解析代表路径自由字符串。
     * 测试把这些事实按一个回合的真实事件顺序输入，断言输出名称、数值和顺序全部来自
     * 明确字段，并使用 summary.max HP 显示剩余血量。
     */
    const turns = presentBattleReport(
      report([
        event({
          kind: 'move-used',
          actor: 'defender',
          target: 'attacker',
          move_id: 8,
        }),
        event({
          kind: 'ability-triggered',
          actor: 'attacker',
          target: 'attacker',
          move_id: null,
          source_identifier: 'ability:multiscale',
        }),
        event({
          kind: 'pp-changed',
          actor: 'defender',
          target: null,
          move_id: 8,
          before_value: 15,
          after_value: 14,
          value: -1,
        }),
        event({
          kind: 'damage',
          actor: 'defender',
          target: 'attacker',
          move_id: 8,
          value: 57,
        }),
        event({
          kind: 'hp-changed',
          actor: 'defender',
          target: 'attacker',
          move_id: 8,
          before_value: 166,
          after_value: 109,
          value: -57,
        }),
        event({
          kind: 'move-used',
          actor: 'attacker',
          target: 'defender',
          move_id: 280,
        }),
        event({
          kind: 'damage',
          actor: 'attacker',
          target: 'defender',
          move_id: 280,
          value: 145,
        }),
        event({
          kind: 'hp-changed',
          actor: 'attacker',
          target: 'defender',
          move_id: 280,
          before_value: 145,
          after_value: 0,
          value: -145,
        }),
        event({
          kind: 'fainted',
          actor: 'attacker',
          target: 'defender',
          move_id: 280,
        }),
      ]),
      CONTEXT,
    );

    expect(turns).toHaveLength(1);
    expect(turns[0]?.events.map((item) => item.text)).toEqual([
      '玛纽拉使用了冰冻拳！',
      '快龙的多重鳞片触发了。',
      '玛纽拉的冰冻拳 PP：15 → 14。',
      '快龙失去了 57 点 HP。',
      '快龙剩余 109 / 166 HP。',
      '快龙使用了劈瓦！',
      '玛纽拉失去了 145 点 HP。',
      '玛纽拉剩余 0 / 145 HP。',
      '玛纽拉倒下了。',
    ]);
  });

  it('distinguishes miss, fake-out flinch, inner-focus prevention and action blocking', () => {
    /**
     * 命中失败、击掌奇袭畏缩、精神力阻止畏缩与畏缩导致行动阻断是首版必须明确
     * 区分的四种结构化事实。测试逐项调用 presenter，确认不会把 status prevented
     * 和 action blocked 合并成同一句模糊战报。
     */
    const cases = [
      event({
        kind: 'miss',
        actor: 'defender',
        target: 'attacker',
        move_id: 8,
      }),
      event({
        kind: 'move-used',
        actor: 'defender',
        target: 'attacker',
        move_id: 252,
      }),
      event({
        kind: 'status-applied',
        actor: 'defender',
        target: 'attacker',
        move_id: 252,
        source_identifier: 'flinch',
      }),
      event({
        kind: 'ability-triggered',
        actor: 'attacker',
        target: 'attacker',
        move_id: null,
        source_identifier: 'ability:inner_focus',
      }),
      event({
        kind: 'status-prevented',
        actor: 'attacker',
        target: 'attacker',
        move_id: 252,
        source_identifier: 'flinch',
      }),
      event({
        kind: 'action-blocked',
        actor: 'attacker',
        target: null,
        move_id: 280,
        source_identifier: 'flinch',
      }),
    ];

    const texts = cases
      .map((item, index) => presentBattleEvent(item, CONTEXT, `event-${index}`))
      .map((item) => item?.text);

    expect(texts).toEqual([
      '玛纽拉的冰冻拳没有命中！',
      '玛纽拉使用了击掌奇袭！',
      '快龙畏缩了。',
      '快龙的精神力触发了。',
      '快龙没有陷入畏缩。',
      '快龙因畏缩无法行动！',
    ]);
  });

  it('renders different selected damage outcomes with different HP values', () => {
    /**
     * 两个正式 damage outcomes 必须展示各自结构化 damage/hp-changed 数值，不能因为
     * 到达同一展示组件或共享 Pokémon 名称而复用上一条文本。测试分别投影 57 与 63 点
     * 伤害，断言剩余 HP 也随 after_value 同步变化。
     */
    const first = presentBattleReport(
      report([
        event({
          kind: 'damage',
          actor: 'defender',
          target: 'attacker',
          move_id: 8,
          value: 57,
        }),
        event({
          kind: 'hp-changed',
          actor: 'defender',
          target: 'attacker',
          move_id: 8,
          before_value: 166,
          after_value: 109,
        }),
      ]),
      CONTEXT,
    );
    const second = presentBattleReport(
      report([
        event({
          kind: 'damage',
          actor: 'defender',
          target: 'attacker',
          move_id: 8,
          value: 63,
        }),
        event({
          kind: 'hp-changed',
          actor: 'defender',
          target: 'attacker',
          move_id: 8,
          before_value: 166,
          after_value: 103,
        }),
      ]),
      CONTEXT,
    );

    expect(first[0]?.events.map((item) => item.text)).toContain(
      '快龙剩余 109 / 166 HP。',
    );
    expect(second[0]?.events.map((item) => item.text)).toContain(
      '快龙剩余 103 / 166 HP。',
    );
  });

  it('keeps unknown event kinds visible and observable for developers', () => {
    /**
     * 后端未来新增 event kind 时，前端不能静默丢失事实。测试传入未知类别，断言用户
     * 能看到 kind/source fallback，同时 console warning 包含原始 DTO 供开发排查。
     */
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const unknown = event({
      kind: 'terrain-shifted',
      source_identifier: 'electric-terrain',
    });

    const presented = presentBattleEvent(unknown, CONTEXT, 'unknown-event');

    expect(presented?.text).toBe(
      '未识别事件：terrain-shifted · electric-terrain',
    );
    expect(presented?.debug).toContain('"kind":"terrain-shifted"');
    expect(warning).toHaveBeenCalledWith(
      '[battle-report] 未识别结构化事件',
      unknown,
    );
    warning.mockRestore();
  });
});
