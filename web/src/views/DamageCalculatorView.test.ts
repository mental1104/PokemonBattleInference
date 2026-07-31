import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getPokemonDetail,
  listBattleItems,
  listPokemonMoves,
  listStatPresets,
  searchPokemon,
  type PokemonDetail,
  type PokemonSearchItem,
} from '../api/calculator';
import ItemSelector from '../components/ItemSelector.vue';
import PokemonSelector from '../components/PokemonSelector.vue';
import DamageCalculatorView from './DamageCalculatorView.vue';

vi.mock('../api/calculator', () => ({
  calculateDamage: vi.fn(),
  getPokemonDetail: vi.fn(),
  listBattleItems: vi.fn(),
  listPokemonMoves: vi.fn(),
  listStatPresets: vi.fn(),
  searchPokemon: vi.fn(),
}));

const searchPokemonMock = vi.mocked(searchPokemon);
const getPokemonDetailMock = vi.mocked(getPokemonDetail);
const listBattleItemsMock = vi.mocked(listBattleItems);
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
  listBattleItemsMock.mockReset().mockResolvedValue([
    {
      item_id: null,
      identifier: 'none',
      display_name: '不携带道具',
      effect_identifier: null,
      sprite_url: null,
    },
    {
      item_id: 247,
      identifier: 'life-orb',
      display_name: '生命宝珠',
      effect_identifier: 'life-orb',
      sprite_url: '/api/v1/assets/items/life-orb/sprite',
    },
  ]);
  listStatPresetsMock.mockReset().mockResolvedValue({ attacker: [], defender: [] });
});

describe('DamageCalculatorView', () => {
  it('keeps attacker and defender recent selections isolated', async () => {
    /**
     * 页面同时挂载攻击方和防守方两个 PokémonSelector。测试先在攻击方选择妙蛙种子，确认防守方仍保持
     * 默认候选列表且没有出现妙蛙种子的最近记录；随后在防守方选择皮卡丘，断言两侧最近列表分别只包含
     * 自己操作过的 Pokémon。该场景保护每个输入框独立维护 LRU 历史，避免另一侧选择污染展示顺序或占用
     * 八个历史名额，同时确认双方当前选中状态和详情加载仍然彼此独立。
     */
    const wrapper = mount(DamageCalculatorView);
    await flushPromises();

    let selectors = wrapper.findAllComponents(PokemonSelector);
    expect(selectors).toHaveLength(2);

    await selectors[0].get(`[data-pokemon-id="${BULBASAUR.pokemon_id}"]`).trigger('click');
    await flushPromises();

    selectors = wrapper.findAllComponents(PokemonSelector);
    expect((selectors[0].props('recentPokemon') as PokemonSearchItem[]).map((item) => item.pokemon_id)).toEqual([1]);
    expect(selectors[1].props('recentPokemon')).toEqual([]);
    expect(selectors[1].props('selected')).toBeNull();
    expect(selectors[1].find('[data-mode="recent"]').exists()).toBe(false);

    await selectors[1].get(`[data-pokemon-id="${PIKACHU.pokemon_id}"]`).trigger('click');
    await flushPromises();

    selectors = wrapper.findAllComponents(PokemonSelector);
    const attackerRecent = selectors[0].props('recentPokemon') as PokemonSearchItem[];
    const defenderRecent = selectors[1].props('recentPokemon') as PokemonSearchItem[];
    expect(attackerRecent.map((item) => item.pokemon_id)).toEqual([1]);
    expect(defenderRecent.map((item) => item.pokemon_id)).toEqual([25]);
    expect(selectors[0].props('selected')).toMatchObject({ pokemon_id: 1 });
    expect(selectors[1].props('selected')).toMatchObject({ pokemon_id: 25 });
    expect(getPokemonDetailMock).toHaveBeenCalledWith(1, 'pokemon-champion');
    expect(getPokemonDetailMock).toHaveBeenCalledWith(25, 'pokemon-champion');
    expect(listPokemonMovesMock).toHaveBeenCalledWith(1, 'pokemon-champion', {
      query: '',
      category: 'all',
      typeIdentifiers: [],
      limit: 10,
      offset: 0,
    });
  });

  it('places independent item selectors between both summaries and stat configurations', async () => {
    /**
     * 攻击方与防守方都必须在 Pokémon 摘要和能力配置之间展示独立的 ItemSelector，并且共享同一份服务端
     * 道具候选列表但维护各自的 selectedIdentifier。测试同时检查两个选择器初始都显示“不携带道具”、尚未
     * 选择对应 Pokémon 时保持禁用、双方列内排列顺序一致，以及 MoveSelector 仍然只出现在双栏之后并占满
     * calculator 主区域宽度。该场景防止后续视觉调整再次把防守方道具入口替换为空白占位，或错误复用攻击方
     * 的选择状态，同时保护最新招式区域布局不被本功能回退。
     */
    const wrapper = mount(DamageCalculatorView);
    await flushPromises();

    const attackerColumn = wrapper.get('[data-testid="attacker-column"]');
    const defenderColumn = wrapper.get('[data-testid="defender-column"]');
    const itemSelectors = wrapper.findAllComponents(ItemSelector);
    expect(itemSelectors).toHaveLength(2);

    const attackerItemSelector = attackerColumn.get('[data-testid="attacker-item"]');
    const defenderItemSelector = defenderColumn.get('[data-testid="defender-item"]');
    expect(attackerColumn.find('[data-testid="attacker-config"]').exists()).toBe(true);
    expect(defenderColumn.find('[data-testid="defender-config"]').exists()).toBe(true);
    expect(attackerItemSelector.text()).toContain('不携带道具');
    expect(defenderItemSelector.text()).toContain('不携带道具');
    expect(itemSelectors[0].props('selectedIdentifier')).toBe('none');
    expect(itemSelectors[1].props('selectedIdentifier')).toBe('none');
    expect(itemSelectors[0].props('disabled')).toBe(true);
    expect(itemSelectors[1].props('disabled')).toBe(true);
    expect(attackerColumn.find('.move-selector').exists()).toBe(false);
    expect(defenderColumn.find('.move-selector').exists()).toBe(false);

    const attackerConfig = attackerColumn.get('[data-testid="attacker-config"]').element;
    const defenderConfig = defenderColumn.get('[data-testid="defender-config"]').element;
    expect(
      attackerItemSelector.element.compareDocumentPosition(attackerConfig) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      defenderItemSelector.element.compareDocumentPosition(defenderConfig) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    const moveStage = wrapper.get('[data-testid="move-stage"]');
    expect(moveStage.findAll('.move-selector')).toHaveLength(1);
    expect(moveStage.attributes('aria-label')).toBe('攻击方招式选择');

    const grid = wrapper.get('.calculator-grid').element;
    const stage = moveStage.element;
    expect(grid.compareDocumentPosition(stage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
