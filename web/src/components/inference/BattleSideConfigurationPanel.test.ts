import { flushPromises, mount, type VueWrapper } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  searchPokemon,
  type PokemonSearchItem,
} from '../../api/calculator';
import BattleSideConfigurationPanel from './BattleSideConfigurationPanel.vue';

vi.mock('../../api/calculator', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/calculator')>();
  return {
    ...actual,
    searchPokemon: vi.fn(),
  };
});

const searchPokemonMock = vi.mocked(searchPokemon);

/**
 * 构造选择器历史隔离测试使用的 Pokémon 搜索项。
 *
 * @param pokemonId Pokémon ID，也是最近记录的去重键。
 * @param displayName 页面展示名称。
 * @returns 满足搜索接口合同的最小 DTO。
 */
function pokemon(pokemonId: number, displayName: string): PokemonSearchItem {
  return {
    pokemon_id: pokemonId,
    identifier: `pokemon-${pokemonId}`,
    display_name: displayName,
    form_identifier: null,
    types: ['normal'],
    type_names: ['一般'],
    sprite_url: `/sprites/${pokemonId}.png`,
  };
}

/**
 * 挂载一侧固定推演配置面板，并用轻量 stub 隔离与历史记录无关的摘要、能力值和技能池组件。
 *
 * @param side 当前面板代表攻击方还是防守方。
 * @param title 面板展示标题。
 * @param sharedRecentPokemon 父级传入的共享历史数组，用于验证组件不会直接复用该状态。
 * @returns 可操作真实 PokemonSelector 的面板 wrapper。
 */
function mountPanel(
  side: 'attacker' | 'defender',
  title: string,
  sharedRecentPokemon: readonly PokemonSearchItem[],
): VueWrapper {
  return mount(BattleSideConfigurationPanel, {
    props: {
      side,
      title,
      rulesetId: 'pokemon-champion',
      pokemon: null,
      recentPokemon: sharedRecentPokemon,
      statPreset: '',
      formId: null,
      level: 50,
      abilityIdentifier: '',
      itemIdentifier: '',
      candidateMoves: [],
      selectedMoveIds: [],
      movesLoading: false,
      remainingGlobalSlots: 8,
    },
    global: {
      stubs: {
        PokemonSummaryCard: true,
        StatConfigurationPicker: true,
        CandidateMovePoolSelector: true,
      },
    },
  });
}

const BULBASAUR = pokemon(1, '妙蛙种子');
const PIKACHU = pokemon(25, '皮卡丘');

beforeEach(() => {
  searchPokemonMock.mockReset().mockResolvedValue([BULBASAUR, PIKACHU]);
});

describe('BattleSideConfigurationPanel', () => {
  it('keeps recent pokemon inside each panel instance', async () => {
    /**
     * 固定推演页面会同时创建攻击方和防守方两个配置面板，旧实现把父级同一个最近记录数组传给两侧，导致
     * 攻击方选择妙蛙种子后防守方也立即显示妙蛙种子。测试用同一个空数组挂载两个真实选择器实例，先在
     * 攻击方面板选择妙蛙种子，再在防守方面板选择皮卡丘；断言每侧最近视图只包含自己触发过的 Pokémon，
     * 且另一侧操作不会改变既有顺序。该场景同时保护独立八项 LRU 容量和面板实例的会话生命周期边界。
     */
    const sharedRecentPokemon: readonly PokemonSearchItem[] = [];
    const attackerPanel = mountPanel('attacker', '攻击方', sharedRecentPokemon);
    const defenderPanel = mountPanel('defender', '防守方', sharedRecentPokemon);
    await flushPromises();

    await attackerPanel.get(`[data-pokemon-id="${BULBASAUR.pokemon_id}"]`).trigger('click');
    await flushPromises();

    expect(attackerPanel.get('[data-mode="recent"]').text()).toContain('妙蛙种子');
    expect(attackerPanel.get('[data-mode="recent"]').text()).not.toContain('皮卡丘');
    expect(defenderPanel.find('[data-mode="recent"]').exists()).toBe(false);

    await defenderPanel.get(`[data-pokemon-id="${PIKACHU.pokemon_id}"]`).trigger('click');
    await flushPromises();

    expect(attackerPanel.get('[data-mode="recent"]').text()).toContain('妙蛙种子');
    expect(attackerPanel.get('[data-mode="recent"]').text()).not.toContain('皮卡丘');
    expect(defenderPanel.get('[data-mode="recent"]').text()).toContain('皮卡丘');
    expect(defenderPanel.get('[data-mode="recent"]').text()).not.toContain('妙蛙种子');
    expect(attackerPanel.emitted('select-pokemon')?.[0]).toEqual([BULBASAUR]);
    expect(defenderPanel.emitted('select-pokemon')?.[0]).toEqual([PIKACHU]);
  });
});
