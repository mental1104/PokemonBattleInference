import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  listPokemonMoves,
  type MoveSearchItem,
  type MoveSearchPage,
} from '../api/calculator';
import MoveSelector from './MoveSelector.vue';

vi.mock('../api/calculator', () => ({
  listPokemonMoves: vi.fn(),
}));

const listPokemonMovesMock = vi.mocked(listPokemonMoves);

/**
 * 构造 MoveSelector 测试使用的可计算招式。
 *
 * @param moveId PokeAPI move_id，也是分页追加时的去重键。
 * @param type 招式属性 identifier。
 * @param category 物理或特殊类别。
 * @param power 固定正威力。
 * @returns 满足招式 API 合同的 DTO。
 */
function move(
  moveId: number,
  type: string = 'electric',
  category: 'physical' | 'special' = 'special',
  power: number = 90,
): MoveSearchItem {
  return {
    move_id: moveId,
    identifier: `move-${moveId}`,
    display_name: `招式${moveId}`,
    type,
    type_name: type,
    category,
    power,
  };
}

/**
 * 构造服务端分页 envelope。
 *
 * @param items 当前页招式。
 * @param total 复合过滤后的去重总数。
 * @param limit 当前页上限。
 * @param offset 当前页偏移。
 * @returns 带完整电、水属性元数据的分页响应。
 */
function page(
  items: MoveSearchItem[],
  total: number = items.length,
  limit: number = 10,
  offset: number = 0,
): MoveSearchPage {
  return {
    items,
    total,
    limit,
    offset,
    has_more: offset + items.length < total,
    available_types: [
      { identifier: 'electric', display_name: '电' },
      { identifier: 'water', display_name: '水' },
    ],
  };
}

/** 创建一个由测试主动完成的 Promise，用于验证旧请求不会覆盖新结果。 */
function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolvePromise!: (value: T) => void;
  const promise = new Promise<T>((resolve) => {
    resolvePromise = resolve;
  });
  return { promise, resolve: resolvePromise };
}

beforeEach(() => {
  vi.useFakeTimers();
  listPokemonMovesMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('MoveSelector', () => {
  it('loads at most ten embedded moves with the default all-category filter', async () => {
    /**
     * 选择攻击方后，页面内嵌列表必须立即请求 offset 零、limit 十的第一页，类别默认为 all 且属性集合
     * 为空。测试返回十二条总数中的前十条，断言组件只渲染十项并显示“查看全部（12）”入口，同时
     * 服务端提供的电、水完整属性元数据被渲染为筛选按钮。该场景保护首屏不会一次拉取五十或全部
     * 招式，也确保更多入口由 total/has_more 决定，而不是根据当前数组长度进行不可靠猜测。
     */
    const embeddedMoves = Array.from({ length: 10 }, (_, index) => move(index + 1));
    listPokemonMovesMock.mockResolvedValue(page(embeddedMoves, 12, 10, 0));

    const wrapper = mount(MoveSelector, {
      props: {
        pokemonId: 25,
        rulesetId: 'pokemon-champion',
        selected: null,
        disabled: false,
      },
    });
    await flushPromises();

    expect(listPokemonMovesMock).toHaveBeenCalledWith(25, 'pokemon-champion', {
      query: '',
      category: 'all',
      typeIdentifiers: [],
      limit: 10,
      offset: 0,
    });
    expect(wrapper.findAll('[data-testid="embedded-move-list"] .list-option')).toHaveLength(10);
    expect(wrapper.get('[data-testid="open-move-modal"]').text()).toContain('12');
    expect(wrapper.text()).toContain('电');
    expect(wrapper.text()).toContain('水');
  });

  it('combines category and multiple type filters and can clear the type selection', async () => {
    /**
     * 类别单选与属性多选必须构造 category AND type-in-selected 的服务端请求。测试先加载属性元数据，
     * 再点击“物理”、电和水，逐步断言最后一次请求为 physical 加 electric/water 两个 identifier；随后
     * 点击“清空属性”，验证类别仍保持 physical 而 typeIdentifiers 恢复为空数组。该场景保护多个属性
     * 使用同一数组表达 OR，清空操作不会顺带重置类别，也不会退化为客户端本地过滤当前十条结果。
     */
    listPokemonMovesMock.mockResolvedValue(page([move(1)]));
    const wrapper = mount(MoveSelector, {
      props: {
        pokemonId: 25,
        rulesetId: 'pokemon-champion',
        selected: null,
        disabled: false,
      },
    });
    await flushPromises();

    const buttons = wrapper.findAll('.filter-button');
    await buttons[1].trigger('click');
    await flushPromises();
    const typeButtons = wrapper.findAll('.filter-chip');
    await typeButtons[0].trigger('click');
    await flushPromises();
    await typeButtons[1].trigger('click');
    await flushPromises();

    expect(listPokemonMovesMock).toHaveBeenLastCalledWith(25, 'pokemon-champion', {
      query: '',
      category: 'physical',
      typeIdentifiers: ['electric', 'water'],
      limit: 10,
      offset: 0,
    });

    await wrapper.get('.move-type-filter .text-button').trigger('click');
    await flushPromises();
    expect(listPokemonMovesMock).toHaveBeenLastCalledWith(25, 'pokemon-champion', {
      query: '',
      category: 'physical',
      typeIdentifiers: [],
      limit: 10,
      offset: 0,
    });
  });

  it('loads modal pages in batches of fifty and removes duplicate move ids', async () => {
    /**
     * 当内嵌页提示还有更多结果时，弹窗首次必须使用 limit 五十和 offset 零；继续加载则从已去重数量
     * 开始请求。测试让第二页故意重复 move_id 50，并追加 51 到 70，断言最终弹窗只保留七十个唯一
     * 招式、第二次请求 offset 为五十，并在全部加载后显示完成状态。该场景保护网络重试或服务端页边界
     * 重叠不会产生重复按钮，同时单次请求始终不超过服务端五十条硬上限。
     */
    const firstTen = Array.from({ length: 10 }, (_, index) => move(index + 1));
    const firstFifty = Array.from({ length: 50 }, (_, index) => move(index + 1));
    const secondBatch = Array.from({ length: 21 }, (_, index) => move(index + 50));
    listPokemonMovesMock
      .mockResolvedValueOnce(page(firstTen, 70, 10, 0))
      .mockResolvedValueOnce(page(firstFifty, 70, 50, 0))
      .mockResolvedValueOnce(page(secondBatch, 70, 50, 50));

    const wrapper = mount(MoveSelector, {
      props: {
        pokemonId: 25,
        rulesetId: 'pokemon-champion',
        selected: null,
        disabled: false,
      },
    });
    await flushPromises();

    await wrapper.get('[data-testid="open-move-modal"]').trigger('click');
    await flushPromises();
    expect(listPokemonMovesMock).toHaveBeenNthCalledWith(2, 25, 'pokemon-champion', {
      query: '',
      category: 'all',
      typeIdentifiers: [],
      limit: 50,
      offset: 0,
    });

    await wrapper.get('[data-testid="load-more-moves"]').trigger('click');
    await flushPromises();
    expect(listPokemonMovesMock).toHaveBeenNthCalledWith(3, 25, 'pokemon-champion', {
      query: '',
      category: 'all',
      typeIdentifiers: [],
      limit: 50,
      offset: 50,
    });
    expect(wrapper.findAll('.move-modal-list .list-option')).toHaveLength(70);
    expect(wrapper.text()).toContain('已加载全部结果');
  });

  it('ignores a late response from an older text filter', async () => {
    /**
     * 用户快速输入时，较早请求可能在新搜索词的 250ms 防抖窗口内返回。测试先让“old”搜索保持未完成，
     * 再输入“new”但暂不触发新请求，此时完成旧请求并断言 move_id 1 不会回闪；随后触发新请求并返回
     * move_id 2，界面最终只显示新结果。该场景固定 requestVersion 在输入变化瞬间即失效旧请求的保护，
     * 避免前一个搜索词、类别或攻击方的过期页面覆盖当前状态并让用户误选不属于当前条件的招式。
     */
    listPokemonMovesMock.mockResolvedValueOnce(page([]));
    const oldRequest = deferred<MoveSearchPage>();
    const newRequest = deferred<MoveSearchPage>();
    listPokemonMovesMock
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(newRequest.promise);

    const wrapper = mount(MoveSelector, {
      props: {
        pokemonId: 25,
        rulesetId: 'pokemon-champion',
        selected: null,
        disabled: false,
      },
    });
    await flushPromises();

    await wrapper.get('[data-testid="move-search-input"]').setValue('old');
    await vi.advanceTimersByTimeAsync(250);
    await wrapper.get('[data-testid="move-search-input"]').setValue('new');

    // 新防抖请求尚未发出时完成旧请求，也不能让旧结果在 250ms 窗口内回闪。
    oldRequest.resolve(page([move(1)]));
    await flushPromises();
    expect(wrapper.text()).not.toContain('招式1');

    await vi.advanceTimersByTimeAsync(250);
    newRequest.resolve(page([move(2)]));
    await flushPromises();

    expect(wrapper.text()).toContain('招式2');
    expect(wrapper.text()).not.toContain('招式1');
  });

  it('clears a selected move when a new filter excludes it', async () => {
    /**
     * 当前已选招式不能在筛选变化后悄悄保持可提交状态。测试以特殊电属性招式作为 selected，切换到
     * 物理类别后断言组件发出 clearSelection 事件；这让父级 calculator 立即清空 move_id，并阻止用户
     * 在界面只显示物理结果时仍提交先前的特殊招式。该判断只使用已选 DTO 可确认的类别、属性和文本，
     * 不依赖当前十条分页是否恰好包含该招式，因此不会把合法但位于后续页的选择误判为失效。
     */
    listPokemonMovesMock.mockResolvedValue(page([move(85)]));
    const wrapper = mount(MoveSelector, {
      props: {
        pokemonId: 25,
        rulesetId: 'pokemon-champion',
        selected: move(85, 'electric', 'special'),
        disabled: false,
      },
    });
    await flushPromises();

    await wrapper.findAll('.filter-button')[1].trigger('click');

    expect(wrapper.emitted('clearSelection')).toHaveLength(1);
  });
});
