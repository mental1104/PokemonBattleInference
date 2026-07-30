import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getPokemonDetail,
  listStatPresets,
  searchPokemon,
  type PokemonDetail,
} from '../api/calculator';
import {
  enumerateMoveSetCombinations,
  inferFixedBattleJourney,
} from '../api/fixedBattle';
import {
  DRAGONITE_EXAMPLE,
  WEAVILE_EXAMPLE,
} from '../api/configurationSpace';
import type {
  MoveSetCombinationsRequest,
  MoveSetCombinationsResult,
} from '../types/fixedBattle';
import BattleInferenceView from './BattleInferenceView.vue';

vi.mock('../api/calculator', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/calculator')>();
  return {
    ...actual,
    searchPokemon: vi.fn(),
    getPokemonDetail: vi.fn(),
    listStatPresets: vi.fn(),
  };
});

vi.mock('../api/fixedBattle', () => ({
  enumerateMoveSetCombinations: vi.fn(),
  inferFixedBattleJourney: vi.fn(),
}));

const searchPokemonMock = vi.mocked(searchPokemon);
const getPokemonDetailMock = vi.mocked(getPokemonDetail);
const listStatPresetsMock = vi.mocked(listStatPresets);
const enumerateMock = vi.mocked(enumerateMoveSetCombinations);
const inferMock = vi.mocked(inferFixedBattleJourney);

/** 挂载真实双侧配置组件；网络边界通过模块 mock 隔离。 */
function mountView(): VueWrapper {
  return mount(BattleInferenceView, {
    global: {
      stubs: {
        BattleGraphExplorer: {
          template: '<section data-test="graph-explorer">路径聚焦式状态图</section>',
        },
        BattleReportPanel: {
          template: '<aside data-test="battle-report">逐回合战报</aside>',
        },
        BattleGraphTreeScreen: {
          template: '<section data-test="tree-screen">从起点向右追踪战斗路径</section>',
        },
      },
    },
  });
}

/** 返回文本完全匹配的按钮。 */
function buttonByText(wrapper: VueWrapper, text: string) {
  const button = wrapper.findAll('button').find((item) => item.text().includes(text));
  if (button === undefined) throw new Error(`button not found: ${text}`);
  return button;
}

/** 读取一侧候选池当前已选数量。 */
function selectedCount(
  wrapper: VueWrapper,
  side: 'attacker' | 'defender',
): number {
  return Number.parseInt(
    wrapper.get(`[data-testid="${side}-selected-count"]`).text(),
    10,
  );
}

/** 从当前可执行候选中补选到指定数量。 */
async function selectSupportedUntil(
  wrapper: VueWrapper,
  side: 'attacker' | 'defender',
  targetCount: number,
): Promise<void> {
  while (selectedCount(wrapper, side) < targetCount) {
    const option = wrapper
      .findAll(`[data-testid="${side}-move-option"]`)
      .find((candidate) => {
        const support = candidate.attributes('data-support');
        return (
          (support === 'supported' || support === 'no_effect') &&
          candidate.attributes('aria-pressed') === 'false' &&
          candidate.attributes('aria-disabled') === 'false'
        );
      });
    if (option === undefined) throw new Error(`no selectable ${side} move remains`);
    await option.trigger('click');
  }
}

/** 为测试请求生成真实的无序四技能组合。 */
function moveSets(moveIds: number[]) {
  const values = [...moveIds].sort((left, right) => left - right);
  if (values.length < 4) {
    return [
      {
        move_set_id: `move-set:${values.join(',')}`,
        move_ids: values,
        move_names: values.map((value) => `move-${value}`),
      },
    ];
  }
  const result = [];
  for (let first = 0; first < values.length - 3; first += 1) {
    for (let second = first + 1; second < values.length - 2; second += 1) {
      for (let third = second + 1; third < values.length - 1; third += 1) {
        for (let fourth = third + 1; fourth < values.length; fourth += 1) {
          const selected = [
            values[first],
            values[second],
            values[third],
            values[fourth],
          ];
          result.push({
            move_set_id: `move-set:${selected.join(',')}`,
            move_ids: selected,
            move_names: selected.map((value) => `move-${value}`),
          });
        }
      }
    }
  }
  return result;
}

beforeEach(() => {
  searchPokemonMock.mockReset().mockResolvedValue([]);
  getPokemonDetailMock.mockReset().mockImplementation(
    async (pokemonId: number): Promise<PokemonDetail> =>
      pokemonId === DRAGONITE_EXAMPLE.pokemon_id
        ? DRAGONITE_EXAMPLE
        : WEAVILE_EXAMPLE,
  );
  listStatPresetsMock.mockReset().mockResolvedValue({
    attacker: [
      { key: 'max_atk_neutral', label: '满攻', assumption: '攻击 EV 拉满。' },
      { key: 'max_atk_plus', label: '极攻', assumption: '攻击 EV 与性格均强化。' },
    ],
    defender: [{ key: 'max_hp', label: '满 HP', assumption: 'HP EV 拉满。' }],
  });
  enumerateMock.mockReset().mockImplementation(
    async (request: MoveSetCombinationsRequest): Promise<MoveSetCombinationsResult> => {
      const attackerMoveSets = moveSets(request.attacker.candidate_move_ids);
      const defenderMoveSets = moveSets(request.defender.candidate_move_ids);
      return {
        ruleset_id: request.ruleset_id,
        version_group_id: request.version_group_id,
        calculation_revision: request.calculation_revision,
        attacker: {
          pokemon_id: request.attacker.pokemon_id,
          pokemon_name: 'attacker',
          candidate_count: request.attacker.candidate_move_ids.length,
          move_set_count: attackerMoveSets.length,
          move_sets: attackerMoveSets,
        },
        defender: {
          pokemon_id: request.defender.pokemon_id,
          pokemon_name: 'defender',
          candidate_count: request.defender.candidate_move_ids.length,
          move_set_count: defenderMoveSets.length,
          move_sets: defenderMoveSets,
        },
        configuration_pair_count: attackerMoveSets.length * defenderMoveSets.length,
      };
    },
  );
  inferMock.mockReset().mockResolvedValue({
    summary: {
      ruleset_id: 'pokemon-champion',
      version_group_id: 25,
      observer: 'attacker',
      attacker: {
        pokemon_id: 149,
        name: 'attacker',
        level: 50,
        ability_identifier: 'multiscale',
        item_identifier: 'none',
        move_ids: [1, 2, 3, 4],
        move_names: ['move-1', 'move-2', 'move-3', 'move-4'],
        stats: { hp: 166 },
        dimension_labels: {},
      },
      defender: {
        pokemon_id: 461,
        name: 'defender',
        level: 50,
        ability_identifier: 'pressure',
        item_identifier: 'none',
        move_ids: [11, 12, 13, 14],
        move_names: ['move-11', 'move-12', 'move-13', 'move-14'],
        stats: { hp: 155 },
        dimension_labels: {},
      },
      win_probability: { numerator: '5', denominator: '8', decimal: 0.625, percent: 62.5 },
      loss_probability: { numerator: '3', denominator: '8', decimal: 0.375, percent: 37.5 },
      draw_probability: { numerator: '0', denominator: '1', decimal: 0, percent: 0 },
      expected_turns: { available: true, numerator: 5, denominator: 2, decimal: 2.5 },
      attacker_policy: 'uniform-random',
      defender_policy: 'uniform-random',
      graph: {
        unique_state_count: 120,
        edge_count: 840,
        max_turn_number: 4,
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
    },
    exploration: {
      graph_id: 'graph-fixed-test',
      root_node_id: 0,
      calculation_revision: 'battle-inference.summary-exploration.v2',
      expires_at: '2026-07-30T00:00:00Z',
      cursor: { steps: [] },
      expandable: true,
    },
  });
});

describe('BattleInferenceView', () => {
  it('loads the Dragonite mirror Dragon Claw example as one fixed move-set pair', async () => {
    const wrapper = mountView();
    await buttonByText(wrapper, '载入双快龙').trigger('click');
    await flushPromises();

    await buttonByText(wrapper, '生成技能组合').trigger('click');
    await flushPromises();

    expect(enumerateMock).toHaveBeenCalledTimes(1);
    const request = enumerateMock.mock.calls[0][0];
    expect(request.attacker.pokemon_id).toBe(149);
    expect(request.defender.pokemon_id).toBe(149);
    expect(request.attacker.ability_identifier).toBe('multiscale');
    expect(request.defender.ability_identifier).toBe('multiscale');
    expect(request.attacker.candidate_move_ids).toEqual([337]);
    expect(request.defender.candidate_move_ids).toEqual([337]);
    expect(wrapper.text()).toContain('1 × 1 = 1');
    expect(wrapper.findAll('input[name="attacker-move-set"]')).toHaveLength(1);
    expect(wrapper.findAll('input[name="defender-move-set"]')).toHaveLength(1);
    expect(wrapper.text()).toContain('不会创建同等数量的 worker case');
  });

  it('submits only the selected fixed move-set pair to exact inference', async () => {
    const wrapper = mountView();
    await buttonByText(wrapper, '载入双快龙').trigger('click');
    await flushPromises();
    await buttonByText(wrapper, '生成技能组合').trigger('click');
    await flushPromises();

    await buttonByText(wrapper, '运行这个固定配置').trigger('click');
    await flushPromises();

    expect(inferMock).toHaveBeenCalledTimes(1);
    const request = inferMock.mock.calls[0][0];
    expect(request.attacker.pokemon_id).toBe(149);
    expect(request.defender.pokemon_id).toBe(149);
    expect(request.attacker.ability_identifier).toBe('multiscale');
    expect(request.defender.ability_identifier).toBe('multiscale');
    expect(request.attacker.move_ids).toEqual([337]);
    expect(request.defender.move_ids).toEqual([337]);
    expect(request.attacker_policy).toBe('uniform-random');
    expect(wrapper.text()).toContain('62.50%');
    expect(wrapper.text()).toContain('120 nodes · 840 edges');
    expect(wrapper.text()).toContain('路径聚焦式状态图');
    expect(wrapper.text()).toContain('逐回合战报');

    await buttonByText(wrapper, '打开大屏树状图').trigger('click');

    expect(wrapper.text()).toContain('从起点向右追踪战斗路径');
  });

  it('invalidates generated combinations when the candidate selection changes', async () => {
    const wrapper = mountView();
    await buttonByText(wrapper, '载入双快龙').trigger('click');
    await flushPromises();
    await selectSupportedUntil(wrapper, 'attacker', 5);
    await buttonByText(wrapper, '生成技能组合').trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('双方各选择一个固定技能组');

    const selectedMove = wrapper.get('[data-testid="attacker-selected-move"]');
    await selectedMove.trigger('click');
    await flushPromises();

    expect(wrapper.text()).not.toContain('双方各选择一个固定技能组');
  });
});
