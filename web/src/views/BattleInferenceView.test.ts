import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getPokemonDetail,
  listStatPresets,
  searchPokemon,
  type PokemonDetail,
} from '../api/calculator';
import { calculateConfigurationBudget } from '../domain/configurationBudget';
import {
  battleConfigurationSpaceAdapter,
  DRAGONITE_EXAMPLE,
  WEAVILE_EXAMPLE,
} from '../api/configurationSpace';
import type { CreateBattleConfigurationJobRequest } from '../types/battleConfigurationSpace';
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

const searchPokemonMock = vi.mocked(searchPokemon);
const getPokemonDetailMock = vi.mocked(getPokemonDetail);
const listStatPresetsMock = vi.mocked(listStatPresets);
const createJobMock = vi.spyOn(battleConfigurationSpaceAdapter, 'createJob');

/** 挂载真实双侧配置组件，候选池和后台任务继续使用共享 mock adapter。 */
function mountView(): VueWrapper {
  return mount(BattleInferenceView);
}

/**
 * 读取一侧候选池当前已选数量。
 *
 * @param wrapper 页面 wrapper。
 * @param side 攻击方或防守方。
 * @returns 候选池徽章中的非负整数。
 */
function selectedCount(
  wrapper: VueWrapper,
  side: 'attacker' | 'defender',
): number {
  return Number.parseInt(
    wrapper.get(`[data-testid="${side}-selected-count"]`).text(),
    10,
  );
}

/**
 * 逐个移除一侧所有已选候选。
 *
 * @param wrapper 页面 wrapper。
 * @param side 攻击方或防守方。
 */
async function clearSelection(
  wrapper: VueWrapper,
  side: 'attacker' | 'defender',
): Promise<void> {
  const selector = `[data-testid="${side}-selected-move"]`;
  while (wrapper.find(selector).exists()) {
    await wrapper.get(selector).trigger('click');
  }
}

/**
 * 从当前可见可执行项中补选到指定数量。
 *
 * @param wrapper 页面 wrapper。
 * @param side 攻击方或防守方。
 * @param targetCount 期望最终已选数量，必须不超过 fixture 的 20 条可执行候选。
 */
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
    if (option === undefined) {
      throw new Error(`no selectable ${side} move remains before ${targetCount}`);
    }
    await option.trigger('click');
  }
}

beforeEach(() => {
  searchPokemonMock.mockReset().mockResolvedValue([]);
  getPokemonDetailMock.mockReset().mockImplementation(async (pokemonId: number): Promise<PokemonDetail> => {
    if (pokemonId === DRAGONITE_EXAMPLE.pokemon_id) return DRAGONITE_EXAMPLE;
    return WEAVILE_EXAMPLE;
  });
  listStatPresetsMock.mockReset().mockResolvedValue({
    attacker: [
      { key: 'max_atk_neutral', label: '满攻', assumption: '攻击 EV 拉满。' },
      { key: 'max_atk_plus', label: '极攻', assumption: '攻击 EV 与性格均强化。' },
    ],
    defender: [
      { key: 'max_hp', label: '满 HP', assumption: 'HP EV 拉满。' },
    ],
  });
  createJobMock.mockReset().mockImplementation(async (request: CreateBattleConfigurationJobRequest) => {
    const submittedBudget = calculateConfigurationBudget(
      request.attacker.candidate_move_ids.length,
      request.defender.candidate_move_ids.length,
    );
    return {
      job_id: 'mock-battle-job-test',
      status: 'pending',
      submitted_configuration_pairs: submittedBudget.configuration_pair_count,
      created_at: '2026-07-25T00:00:00Z',
    };
  });
});

describe('BattleInferenceView', () => {
  it('renders 10+10 as 44,100 pairs and submits a normalized frozen DTO', async () => {
    /** 示例预设提供双方固定配置；继续扩展到 10+10 后应命中首版最大配置对预算。 */
    const wrapper = mountView();
    await wrapper.get('[data-testid="dragonite-weavile-preset"]').trigger('click');
    await flushPromises();
    await selectSupportedUntil(wrapper, 'attacker', 10);
    await selectSupportedUntil(wrapper, 'defender', 10);

    expect(wrapper.get('[data-testid="attacker-candidate-count"]').text()).toBe('10');
    expect(wrapper.get('[data-testid="defender-candidate-count"]').text()).toBe('10');
    expect(wrapper.get('[data-testid="total-candidate-count"]').text()).toContain('20 / 20');
    expect(wrapper.get('[data-testid="configuration-pair-count"]').text()).toBe('44,100');
    expect(wrapper.get('[data-testid="budget-status"]').text()).toContain('预算内');

    await wrapper.get('[data-testid="submit-configuration-job"]').trigger('click');
    await flushPromises();

    expect(createJobMock).toHaveBeenCalledTimes(1);
    const request = createJobMock.mock.calls[0]?.[0] as CreateBattleConfigurationJobRequest;
    expect(request).toMatchObject({
      contract_version: 'one-on-one-move-pool.v1',
      ruleset_id: 'pokemon-champion',
      version_group_id: 25,
      dimensions: {
        pokemon: 'fixed',
        form: 'fixed',
        level: 'fixed',
        stats: 'fixed',
        ability: 'fixed',
        item: 'fixed',
        moves: 'candidate_pool',
        special_mechanics: 'disabled',
      },
      weight_assumption: 'uniform_configuration_pair',
      attacker_policy: 'uniform-random',
      defender_policy: 'uniform-random',
      mechanism_admission: 'supported_only',
    });
    expect(request.attacker.candidate_move_ids).toHaveLength(10);
    expect(request.defender.candidate_move_ids).toHaveLength(10);
    expect(request.attacker.candidate_move_ids).toEqual(
      [...request.attacker.candidate_move_ids].sort((left, right) => left - right),
    );
    expect(request.defender.candidate_move_ids).toEqual(
      [...request.defender.candidate_move_ids].sort((left, right) => left - right),
    );
    expect(wrapper.get('[data-testid="frozen-submission-summary"]').text()).toContain(
      'pending · mock-battle-job-test',
    );
    expect(wrapper.get('[data-testid="frozen-submission-summary"]').text()).toContain('44,100');
  });

  it('allows the asymmetric 19+1 allocation at the same total candidate limit', async () => {
    /** 极端不对称分配仍然只生成 3,876 个配置对，不能被对称预算假设误伤。 */
    const wrapper = mountView();
    await wrapper.get('[data-testid="dragonite-weavile-preset"]').trigger('click');
    await flushPromises();
    await clearSelection(wrapper, 'attacker');
    await clearSelection(wrapper, 'defender');
    await selectSupportedUntil(wrapper, 'attacker', 19);
    await selectSupportedUntil(wrapper, 'defender', 1);

    expect(wrapper.get('[data-testid="total-candidate-count"]').text()).toContain('20 / 20');
    expect(wrapper.get('[data-testid="configuration-pair-count"]').text()).toBe('3,876');
    expect(wrapper.get('[data-testid="submit-configuration-job"]').attributes('disabled')).toBeUndefined();

    await wrapper.get('[data-testid="submit-configuration-job"]').trigger('click');
    await flushPromises();
    const request = createJobMock.mock.calls[0]?.[0] as CreateBattleConfigurationJobRequest;
    expect(request.attacker.candidate_move_ids).toHaveLength(19);
    expect(request.defender.candidate_move_ids).toHaveLength(1);
  });

  it('keeps unsupported candidates visible and clears stale selections after version-group change', async () => {
    /** version group 是候选准入主轴；切换后旧选择立即失效，新池继续展示明确的支持原因。 */
    const wrapper = mountView();
    await wrapper.get('[data-testid="dragonite-weavile-preset"]').trigger('click');
    await flushPromises();

    const partial = wrapper.get('[data-testid="attacker-move-option"][data-support="partial"]');
    const unsupported = wrapper.get('[data-testid="attacker-move-option"][data-support="unsupported"]');
    expect(partial.attributes('aria-disabled')).toBe('true');
    expect(unsupported.attributes('aria-disabled')).toBe('true');
    expect(wrapper.text()).toContain('dynamic-power-context');
    expect(wrapper.text()).toContain('version-group-legality');

    await wrapper.get('[data-testid="version-group-id"]').setValue('20');
    await flushPromises();

    expect(wrapper.get('[data-testid="attacker-candidate-count"]').text()).toBe('0');
    expect(wrapper.get('[data-testid="defender-candidate-count"]').text()).toBe('0');
    expect(wrapper.text()).toContain('version_group_id 已从 25 切换为 20');
    expect(wrapper.text()).toContain('version_group_id=20');
    expect(wrapper.get('[data-testid="submit-configuration-job"]').attributes('disabled')).toBeDefined();
  });
});
