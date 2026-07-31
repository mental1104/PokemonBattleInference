import { flushPromises, mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getPokemonDetail,
  listBattleItems,
  listPokemonAbilities,
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
  listPokemonAbilities: vi.fn(),
  listPokemonMoves: vi.fn(),
  listStatPresets: vi.fn(),
  searchPokemon: vi.fn(),
}));

const searchPokemonMock = vi.mocked(searchPokemon);
const getPokemonDetailMock = vi.mocked(getPokemonDetail);
const listBattleItemsMock = vi.mocked(listBattleItems);
const listPokemonAbilitiesMock = vi.mocked(listPokemonAbilities);
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
  listPokemonAbilitiesMock.mockReset().mockImplementation(async (pokemonId) => {
    if (pokemonId === BULBASAUR.pokemon_id) {
      return [
        {
          ability_id: 65,
          identifier: 'overgrow',
          display_name: '茂盛',
          slot: 1,
          is_hidden: false,
          implemented: false,
        },
        {
          ability_id: 34,
          identifier: 'chlorophyll',
          display_name: '叶绿素',
          slot: 3,
          is_hidden: true,
          implemented: false,
        },
      ];
    }
    return [
      {
        ability_id: 9,
        identifier: 'static',
        display_name: '静电',
        slot: 1,
        is_hidden: false,
        implemented: false,
      },
    ];
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
     * 自己操作过的 Pokémon。该场景保护每个输入框独立维护 LRU 历史，同时确认详情和特性列表按各自
     * pokemon_id 独立加载，避免另一侧选择污染展示顺序、能力候选或占用八个历史名额。
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
    expect(listPokemonAbilitiesMock).toHaveBeenCalledWith(1, 'pokemon-champion');
    expect(listPokemonAbilitiesMock).toHaveBeenCalledWith(25, 'pokemon-champion');
    expect(listPokemonMovesMock).toHaveBeenCalledWith(1, 'pokemon-champion', {
      query: '',
      category: 'all',
      typeIdentifiers: [],
      limit: 10,
      offset: 0,
    });
  });

  it('keeps independent item selectors in both battle columns', async () => {
    /**
     * 攻击方与防守方都必须在 Pokémon 摘要后展示独立 ItemSelector，并共享服务端候选但维护各自的
     * selectedIdentifier。未选择对应 Pokémon 时两个入口都保持禁用且默认显示不携带道具；该场景保护
     * 已合入主分支的防守方道具能力不会被特性面板改造覆盖，也保证后续新增选择项时双方状态仍然对称，
     * MoveSelector 继续只出现在双栏之后而不会被嵌入某一侧配置区域。
     */
    const wrapper = mount(DamageCalculatorView);
    await flushPromises();

    const itemSelectors = wrapper.findAllComponents(ItemSelector);
    expect(itemSelectors).toHaveLength(2);
    expect(itemSelectors[0].props('selectedIdentifier')).toBe('none');
    expect(itemSelectors[1].props('selectedIdentifier')).toBe('none');
    expect(itemSelectors[0].props('disabled')).toBe(true);
    expect(itemSelectors[1].props('disabled')).toBe(true);
    expect(wrapper.get('[data-testid="attacker-item"]').text()).toContain('不携带道具');
    expect(wrapper.get('[data-testid="defender-item"]').text()).toContain('不携带道具');
  });

  it('places required ability selectors below equipment and above stat configuration', async () => {
    /**
     * 攻击方选择妙蛙种子、防守方选择皮卡丘后，两栏都必须展示真实特性候选，并严格保持“携带道具、特性、
     * 攻击或耐久配置”的纵向顺序。未实现候选仍可点击，但必须显示禁止符号、“未实现”标识和按无特性处理
     * 的悬浮说明；隐藏特性继续保留。MoveSelector 独立位于双栏之后，防止新增特性面板破坏现有道具能力、
     * 攻防等宽布局或招式选择区域的位置。
     */
    const wrapper = mount(DamageCalculatorView);
    await flushPromises();

    let selectors = wrapper.findAllComponents(PokemonSelector);
    await selectors[0].get(`[data-pokemon-id="${BULBASAUR.pokemon_id}"]`).trigger('click');
    await flushPromises();
    selectors = wrapper.findAllComponents(PokemonSelector);
    await selectors[1].get(`[data-pokemon-id="${PIKACHU.pokemon_id}"]`).trigger('click');
    await flushPromises();

    const attackerColumn = wrapper.get('[data-testid="attacker-column"]');
    const defenderColumn = wrapper.get('[data-testid="defender-column"]');
    const attackerItemSelector = attackerColumn.get('[data-testid="attacker-item"]');
    const defenderItemSelector = defenderColumn.get('[data-testid="defender-item"]');
    const attackerAbilitySelector = attackerColumn.get('[data-testid="attacker-ability"]');
    const defenderAbilitySelector = defenderColumn.get('[data-testid="defender-ability"]');
    const attackerConfig = attackerColumn.get('[data-testid="attacker-config"]');
    const defenderConfig = defenderColumn.get('[data-testid="defender-config"]');

    expect(attackerAbilitySelector.text()).toContain('茂盛');
    expect(attackerAbilitySelector.text()).toContain('叶绿素');
    expect(attackerAbilitySelector.text()).toContain('⊘ 未实现');
    expect(attackerAbilitySelector.get('.ability-selector__unsupported').attributes('title')).toBe(
      '当前未实现，参与计算时按无特性处理',
    );
    expect(defenderAbilitySelector.text()).toContain('静电');
    expect(attackerColumn.find('.move-selector').exists()).toBe(false);
    expect(defenderColumn.find('.move-selector').exists()).toBe(false);

    expect(
      attackerItemSelector.element.compareDocumentPosition(attackerAbilitySelector.element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      attackerAbilitySelector.element.compareDocumentPosition(attackerConfig.element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      defenderItemSelector.element.compareDocumentPosition(defenderAbilitySelector.element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      defenderAbilitySelector.element.compareDocumentPosition(defenderConfig.element) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    const moveStage = wrapper.get('[data-testid="move-stage"]');
    expect(moveStage.findAll('.move-selector')).toHaveLength(1);
    expect(moveStage.attributes('aria-label')).toBe('攻击方招式选择');

    const grid = wrapper.get('.calculator-grid').element;
    const stage = moveStage.element;
    expect(grid.compareDocumentPosition(stage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
