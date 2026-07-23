import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { searchPokemon, type PokemonSearchItem } from '../api/calculator';
import PokemonSelector from './PokemonSelector.vue';

vi.mock('../api/calculator', () => ({
  searchPokemon: vi.fn(),
}));

const searchPokemonMock = vi.mocked(searchPokemon);

/**
 * 构造选择器测试使用的 Pokémon DTO。
 *
 * @param pokemonId Pokémon ID，也是按钮测试标识和去重键。
 * @param displayName 页面展示名称。
 * @returns 满足选择器 props 和事件合同的测试对象。
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

const BULBASAUR = pokemon(1, '妙蛙种子');
const IVYSAUR = pokemon(2, '妙蛙草');
const PIKACHU = pokemon(25, '皮卡丘');

beforeEach(() => {
  vi.useFakeTimers();
  searchPokemonMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('PokemonSelector', () => {
  it('loads and displays the backend default list when there is no recent history', async () => {
    /**
     * 用户第一次打开页面时不存在任何最近选择，组件必须维持原有默认浏览体验。测试让后端返回妙蛙种子
     * 和妙蛙草，断言组件立即以空搜索词请求当前规则集，并在 all 模式展示两项。该场景保护新功能不会
     * 让首次使用者面对空白选择器，也不会要求用户先输入关键词才能看到候选 Pokémon。
     */
    searchPokemonMock.mockResolvedValue([BULBASAUR, IVYSAUR]);

    const wrapper = mount(PokemonSelector, {
      props: {
        title: '攻击方 Pokémon',
        rulesetId: 'pokemon-champion',
        selected: null,
        recentPokemon: [],
      },
    });
    await flushPromises();

    expect(searchPokemonMock).toHaveBeenCalledWith('', 'pokemon-champion');
    expect(wrapper.find('[data-mode="all"]').exists()).toBe(true);
    expect(wrapper.findAll('.list-option')).toHaveLength(2);
    expect(wrapper.text()).toContain('妙蛙种子');
  });

  it('shows recent history by default and lets the user browse the backend list explicitly', async () => {
    /**
     * 页面已经存在最近选择时，空搜索状态不应继续展开完整候选列表。测试以皮卡丘作为最近项挂载组件，
     * 断言初始化阶段不请求默认列表且列表模式为 recent；随后点击“浏览全部”，验证组件才请求空查询，
     * 切换为 all 模式并保留可返回最近视图的入口。该场景固定折叠规则和显式展开操作。
     */
    searchPokemonMock.mockResolvedValue([BULBASAUR, IVYSAUR]);

    const wrapper = mount(PokemonSelector, {
      props: {
        title: '防守方 Pokémon',
        rulesetId: 'pokemon-champion',
        selected: null,
        recentPokemon: [PIKACHU],
      },
    });
    await flushPromises();

    expect(searchPokemonMock).not.toHaveBeenCalled();
    expect(wrapper.find('[data-mode="recent"]').text()).toContain('皮卡丘');
    expect(wrapper.get('[data-testid="pokemon-list-toggle"]').text()).toBe('浏览全部');

    await wrapper.get('[data-testid="pokemon-list-toggle"]').trigger('click');
    await flushPromises();

    expect(searchPokemonMock).toHaveBeenCalledWith('', 'pokemon-champion');
    expect(wrapper.find('[data-mode="all"]').exists()).toBe(true);
    expect(wrapper.get('[data-testid="pokemon-list-toggle"]').text()).toBe('返回最近');
  });

  it('uses search results while typing and returns to recent history after clearing the query', async () => {
    /**
     * 用户从最近列表临时搜索其他 Pokémon 时，非空搜索词应经过 250ms 防抖后展示服务端匹配结果；清空
     * 搜索词后则立即回到最近视图，不再请求或展开完整默认列表。测试使用皮卡丘搜索结果和妙蛙种子
     * 最近项，断言搜索调用次数、模式切换和最终可见内容，保护最近视图不会被搜索结果永久覆盖。
     */
    searchPokemonMock.mockResolvedValue([PIKACHU]);

    const wrapper = mount(PokemonSelector, {
      props: {
        title: '攻击方 Pokémon',
        rulesetId: 'pokemon-champion',
        selected: null,
        recentPokemon: [BULBASAUR],
      },
    });

    await wrapper.get('[data-testid="pokemon-search-input"]').setValue('pika');
    await vi.advanceTimersByTimeAsync(250);
    await flushPromises();

    expect(searchPokemonMock).toHaveBeenCalledTimes(1);
    expect(searchPokemonMock).toHaveBeenCalledWith('pika', 'pokemon-champion');
    expect(wrapper.find('[data-mode="search"]').text()).toContain('皮卡丘');

    await wrapper.get('[data-testid="pokemon-search-input"]').setValue('');

    expect(searchPokemonMock).toHaveBeenCalledTimes(1);
    expect(wrapper.find('[data-mode="recent"]').text()).toContain('妙蛙种子');
  });

  it('keeps recent history available when browsing all fails', async () => {
    /**
     * 最近选择属于父级页面内存，不能因为一次网络失败而丢失。测试让“浏览全部”请求返回离线错误，断言
     * 组件展示错误但仍保留“返回最近”入口；点击后最近模式重新显示皮卡丘，且没有要求重新请求或重建
     * 历史。该场景保护网络故障只影响服务端候选列表，不影响用户当前会话中的常用 Pokémon。
     */
    searchPokemonMock.mockRejectedValue(new Error('网络不可用'));

    const wrapper = mount(PokemonSelector, {
      props: {
        title: '防守方 Pokémon',
        rulesetId: 'pokemon-champion',
        selected: null,
        recentPokemon: [PIKACHU],
      },
    });

    await wrapper.get('[data-testid="pokemon-list-toggle"]').trigger('click');
    await flushPromises();

    expect(wrapper.text()).toContain('网络不可用');
    expect(wrapper.get('[data-testid="pokemon-list-toggle"]').text()).toBe('返回最近');

    await wrapper.get('[data-testid="pokemon-list-toggle"]').trigger('click');

    expect(wrapper.find('[data-mode="recent"]').text()).toContain('皮卡丘');
  });
});
