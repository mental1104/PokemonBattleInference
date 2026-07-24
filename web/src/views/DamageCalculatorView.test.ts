import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getPokemonDetail,
  listPokemonMoves,
  listStatPresets,
  searchPokemon,
  type PokemonDetail,
  type PokemonSearchItem,
} from '../api/calculator';
import MoveSelector from '../components/MoveSelector.vue';
import PokemonSelector from '../components/PokemonSelector.vue';
import StatPresetSelector from '../components/StatPresetSelector.vue';
import DamageCalculatorView from './DamageCalculatorView.vue';

vi.mock('../api/calculator', () => ({
  calculateDamage: vi.fn(),
  getPokemonDetail: vi.fn(),
  listPokemonMoves: vi.fn(),
  listStatPresets: vi.fn(),
  searchPokemon: vi.fn(),
}));

const searchPokemonMock = vi.mocked(searchPokemon);
const getPokemonDetailMock = vi.mocked(getPokemonDetail);
const listPokemonMovesMock = vi.mocked(listPokemonMoves);
const listStatPresetsMock = vi.mocked(listStatPresets);

/**
 * 构造页面联动测试使用的 Pokémon 搜索结果。
 *
 * @param pokemonId Pokémon ID。
 * @param displayName 页面展示名称。
 * @returns 满足搜索接口合同的 DTO。
 */
function searchItem(pokemonId: number, displayName: string): PokemonSearchItem {
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
 * 将搜索结果扩展成 calculator 选择后需要的详情 DTO。
 *
 * @param item 已选 Pokémon 搜索结果。
 * @returns 带有基础种族值字段的详情对象。
 */
function detail(item: PokemonSearchItem): PokemonDetail {
  return {
    ...item,
    base_stats: {
      hp: 50,
      attack: 50,
      defense: 50,
      special_attack: 50,
      special_defense: 50,
      speed: 50,
    },
  };
}

const BULBASAUR = searchItem(1, '妙蛙种子');
const PIKACHU = searchItem(25, '皮卡丘');

beforeEach(() => {
  searchPokemonMock.mockReset().mockResolvedValue([BULBASAUR, PIKACHU]);
  getPokemonDetailMock.mockReset().mockImplementation(async (pokemonId) => {
    const selected = pokemonId === BULBASAUR.pokemon_id ? BULBASAUR : PIKACHU;
    return detail(selected);
  });
  listPokemonMovesMock.mockReset().mockResolvedValue({
    items: [],
    total: 0,
    limit: 10,
    offset: 0,
    has_more: false,
    available_types: [],
  });
  listStatPresetsMock.mockReset().mockResolvedValue({ attacker: [], defender: [] });
});

describe('DamageCalculatorView', () => {
  it('shares a selection between both selectors without changing the other side selection', async () => {
    /**
     * 攻击方和防守方必须共享页面级最近记录，但各自当前选择仍保持独立。测试在攻击方点击妙蛙种子，
     * 断言两个 PokemonSelector 都收到最近列表，防守方仍未被自动选中。
     */
    const wrapper = mount(DamageCalculatorView);
    await flushPromises();

    let selectors = wrapper.findAllComponents(PokemonSelector);
    expect(selectors).toHaveLength(2);

    await selectors[0].get(`[data-pokemon-id="${BULBASAUR.pokemon_id}"]`).trigger('click');
    await flushPromises();

    selectors = wrapper.findAllComponents(PokemonSelector);
    const attackerRecent = selectors[0].props('recentPokemon') as PokemonSearchItem[];
    const defenderRecent = selectors[1].props('recentPokemon') as PokemonSearchItem[];
    expect(attackerRecent.map((item) => item.pokemon_id)).toEqual([1]);
    expect(defenderRecent.map((item) => item.pokemon_id)).toEqual([1]);
    expect(selectors[1].props('selected')).toBeNull();
    expect(selectors[1].find('[data-mode="recent"]').text()).toContain('妙蛙种子');
    expect(getPokemonDetailMock).toHaveBeenCalledWith(1, 'pokemon-champion');
    expect(listPokemonMovesMock).toHaveBeenCalledWith(1, 'pokemon-champion', {
      query: '',
      category: 'all',
      typeIdentifiers: [],
      limit: 10,
      offset: 0,
    });
  });

  it('aligns both stat configurations and places the attacker-only move selector below them', async () => {
    /**
     * 双栏内部必须拥有相同的 Pokémon、摘要、配置顺序，MoveSelector 不再占据攻击方列高度。
     * 测试检查两个配置组件分别属于左右列，并且唯一 MoveSelector 位于 calculator-grid 之后的居中区域。
     */
    const wrapper = mount(DamageCalculatorView);
    await flushPromises();

    const attackerColumn = wrapper.get('[data-testid="attacker-column"]');
    const defenderColumn = wrapper.get('[data-testid="defender-column"]');
    expect(attackerColumn.findAllComponents(StatPresetSelector)).toHaveLength(1);
    expect(defenderColumn.findAllComponents(StatPresetSelector)).toHaveLength(1);
    expect(attackerColumn.findComponent(MoveSelector).exists()).toBe(false);
    expect(defenderColumn.findComponent(MoveSelector).exists()).toBe(false);

    const moveStage = wrapper.get('[data-testid="move-stage"]');
    expect(moveStage.findAllComponents(MoveSelector)).toHaveLength(1);
    expect(moveStage.attributes('aria-label')).toBe('攻击方招式选择');

    const grid = wrapper.get('.calculator-grid').element;
    const stage = moveStage.element;
    expect(grid.compareDocumentPosition(stage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
