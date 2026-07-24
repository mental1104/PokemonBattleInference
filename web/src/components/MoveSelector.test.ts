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
  it('loads ten embedded moves and renders PostgreSQL-backed type images', async () => {
    /**
     * 选择攻击方后，页面内嵌列表必须请求 offset 零、limit 十的第一页，类别默认为 all 且属性集合
     * 为空。服务端属性元数据渲染为项目内 assets URL，而不是文字 chip 或 submodule 文件路径。
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
    expect(wrapper.findAll('[data-testid="embedded-move-list"] .move-option-card')).toHaveLength(10);
    expect(wrapper.get('[data-testid="open-move-modal"]').text()).toContain('12');

    const typeImages = wrapper.findAll('.type-filter-image');
    expect(typeImages).toHaveLength(2);
    expect(typeImages[0].attributes('src')).toBe('/api/v1/assets/types/electric/sprite');
    expect(typeImages[1].attributes('src')).toBe('/api/v1/assets/types/water/sprite');
    expect(wrapper.findAll('.type-chip')).toHaveLength(0);
  });

  it('combines category with one replaceable type and clears it on a second click', async () => {
    /**
     * UI 属性筛选必须始终是零个或一个 identifier。测试先选择物理与 electric，再点击 water 验证
     * 直接替换，最后再次点击 water 验证恢复全部属性；类别在整个过程中保持 physical。
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

    await wrapper.findAll('.filter-button')[1].trigger('click');
    await flushPromises();
    await wrapper.findAll('.type-image-button')[0].trigger('click');
    await flushPromises();
    expect(listPokemonMovesMock).toHaveBeenLastCalledWith(25, 'pokemon-champion', {
      query: '',
      category: 'physical',
      typeIdentifiers: ['electric'],
      limit: 10,
      offset: 0,
    });
    expect(wrapper.findAll('.type-image-button.active')).toHaveLength(1);

    await wrapper.findAll('.type-image-button')[1].trigger('click');
    await flushPromises();
    expect(listPokemonMovesMock).toHaveBeenLastCalledWith(25, 'pokemon-champion', {
      query: '',
      category: 'physical',
      typeIdentifiers: ['water'],
      limit: 10,
      offset: 0,
    });
    expect(wrapper.findAll('.type-image-button.active')).toHaveLength(1);
    expect(wrapper.findAll('.type-image-button')[1].classes()).toContain('active');

    await wrapper.findAll('.type-image-button')[1].trigger('click');
    await flushPromises();
    expect(listPokemonMovesMock).toHaveBeenLastCalledWith(25, 'pokemon-champion', {
      query: '',
      category: 'physical',
      typeIdentifiers: [],
      limit: 10,
      offset: 0,
    });
    expect(wrapper.findAll('.type-image-button.active')).toHaveLength(0);
  });

  it('shows type artwork, category and power on selected and candidate move cards', async () => {
    /**
     * 已选招式与页面候选必须共享同一视觉合同：属性图片来自 assets API，分类使用醒目徽章，威力
     * 使用独立 POWER 数值块，卡片通过受控 CSS 变量获得属性浅色背景。
     */
    const selected = move(85, 'electric', 'special', 90);
    listPokemonMovesMock.mockResolvedValue(page([selected]));
    const wrapper = mount(MoveSelector, {
      props: {
        pokemonId: 25,
        rulesetId: 'pokemon-champion',
        selected,
        disabled: false,
      },
    });
    await flushPromises();

    const selectedCard = wrapper.get('[data-testid="selected-move-card"]');
    expect(selectedCard.get('.move-type-image').attributes('src')).toBe(
      '/api/v1/assets/types/electric/sprite',
    );
    expect(selectedCard.get('.move-category-badge').text()).toBe('SPECIAL');
    expect(selectedCard.get('.move-power-badge').text()).toContain('POWER90');
    expect(selectedCard.attributes('style')).toContain('--move-type-color: #f4d23c');

    const candidate = wrapper.get('[data-testid="embedded-move-list"] .move-option-card');
    expect(candidate.get('.move-category-badge').attributes('data-category')).toBe('special');
    expect(candidate.get('.move-power-badge').text()).toContain('90');
    expect(candidate.attributes('style')).toContain('--move-type-color: #f4d23c');
  });

  it('loads modal pages in batches of fifty and removes duplicate move ids', async () => {
    /**
     * 当内嵌页提示还有更多结果时，弹窗首次使用 limit 五十和 offset 零；继续加载从已去重数量
     * 开始请求。重复 move_id 不得生成重复卡片，弹窗也必须复用页面内的视觉结构。
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
    expect(wrapper.findAll('.move-modal-list .move-option-card')).toHaveLength(70);
    expect(wrapper.text()).toContain('已加载全部结果');
  });

  it('ignores a late response from an older text filter', async () => {
    /**
     * 用户快速输入时，较早请求可能在新搜索词的 250ms 防抖窗口内返回。旧结果不能回闪并覆盖
     * 当前筛选，最终只允许展示新请求的招式。
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

    // 新防抖请求尚未发出时完成旧请求，也不能让旧结果在窗口内回闪。
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
     * 当前已选招式不能在筛选变化后悄悄保持可提交状态。特殊电属性招式切换到物理类别后，
     * 组件必须发出 clearSelection，让父层立即清空 move_id。
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
