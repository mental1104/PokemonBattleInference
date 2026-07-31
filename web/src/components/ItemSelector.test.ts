import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import type { BattleItemOption } from '../api/calculator';
import ItemSelector from './ItemSelector.vue';

const ITEMS: readonly BattleItemOption[] = [
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
  {
    item_id: 234,
    identifier: 'leftovers',
    display_name: '吃剩的东西',
    effect_identifier: null,
    sprite_url: null,
  },
];

/**
 * 挂载一个可交互的道具选择器。
 *
 * @returns 使用固定实现状态和图标数据创建的 Vue wrapper。
 */
function mountSelector() {
  return mount(ItemSelector, {
    props: {
      title: '携带道具',
      items: ITEMS,
      selectedIdentifier: 'none',
      disabled: false,
      loading: false,
    },
  });
}

describe('ItemSelector', () => {
  it('filters items by localized name and normalized identifier', async () => {
    /**
     * 道具目录展开后可能包含数百条记录，用户应能同时通过中文展示名和英文 identifier 缩小候选范围。
     * 测试先打开弹窗并输入带空格的 life orb，验证组件会忽略 identifier 中连字符与输入空格的差异，
     * 仅保留生命宝珠；随后改为中文“吃剩”，确认未实现道具同样能够被检索到。该场景保护搜索只改变展示集合，
     * 不会因为实现状态而隐藏目录项，也不会要求用户精确输入 PokeAPI 原始格式。
     */
    const wrapper = mountSelector();
    await wrapper.get('.item-selector__trigger').trigger('click');

    const search = wrapper.get('input[type="search"]');
    await search.setValue('life orb');
    expect(wrapper.findAll('.item-selector-option')).toHaveLength(1);
    expect(wrapper.get('.item-selector-option').text()).toContain('生命宝珠');

    await search.setValue('吃剩');
    expect(wrapper.findAll('.item-selector-option')).toHaveLength(1);
    expect(wrapper.get('.item-selector-option').text()).toContain('吃剩的东西');
  });

  it('marks unsupported items and prevents them from being selected', async () => {
    /**
     * 服务端会返回当前规则集全部战斗持有道具，其中未接入伤害 domain 的选项必须保持可见但不可选。
     * 测试定位吃剩的东西，断言它拥有 disabled 属性、禁止标志以及“当前未实现”的悬浮提示；再尝试点击该项，
     * 确认组件没有发出 select 事件且弹窗仍保持打开。最后选择已实现的生命宝珠，验证正常选项仍会发出事件并关闭弹窗。
     * 该场景同时保护视觉提示、交互守卫和既有选择流程，避免未来只做灰态却仍能提交未实现 identifier。
     */
    const wrapper = mountSelector();
    await wrapper.get('.item-selector__trigger').trigger('click');

    const unsupportedButton = wrapper.get('[data-item-identifier="leftovers"]');
    const unsupportedWrapper = unsupportedButton.element.parentElement;
    expect(unsupportedButton.attributes('disabled')).toBeDefined();
    expect(unsupportedButton.text()).toContain('⊘');
    expect(unsupportedButton.get('img').attributes('src')).toBe(
      '/api/v1/assets/items/leftovers/sprite',
    );
    expect(unsupportedWrapper?.getAttribute('title')).toBe('当前未实现');

    await unsupportedButton.trigger('click');
    expect(wrapper.emitted('select')).toBeUndefined();
    expect(wrapper.find('.item-selector-modal').exists()).toBe(true);

    await wrapper.get('[data-item-identifier="life-orb"]').trigger('click');
    expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({ identifier: 'life-orb' });
    expect(wrapper.find('.item-selector-modal').exists()).toBe(false);
  });
});
