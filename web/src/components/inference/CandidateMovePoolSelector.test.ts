import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import type { CandidateMoveOption } from '../../types/battleConfigurationSpace';
import CandidateMovePoolSelector from './CandidateMovePoolSelector.vue';

const MOVES: readonly CandidateMoveOption[] = [
  {
    move_id: 20,
    identifier: 'supported-late',
    display_name: '可用招式二',
    type_identifier: 'normal',
    type_name: '一般',
    damage_class: 'physical',
    power: 80,
    admission: {
      status: 'supported',
      selectable: true,
      reason: '当前计算版本已完整支持。',
      disabled_reason: null,
      missing_mechanism_identifiers: [],
    },
  },
  {
    move_id: 10,
    identifier: 'no-effect-first',
    display_name: '无需额外效果招式',
    type_identifier: 'water',
    type_name: '水',
    damage_class: 'special',
    power: 70,
    admission: {
      status: 'no_effect',
      selectable: true,
      reason: '已确认无需额外 effect。',
      disabled_reason: null,
      missing_mechanism_identifiers: [],
    },
  },
  {
    move_id: 30,
    identifier: 'partial-move',
    display_name: '部分支持招式',
    type_identifier: 'normal',
    type_name: '一般',
    damage_class: 'physical',
    power: null,
    admission: {
      status: 'partial',
      selectable: false,
      reason: '尚未实现动态威力上下文。',
      disabled_reason: '尚未实现动态威力上下文。',
      missing_mechanism_identifiers: ['dynamic-power-context'],
    },
  },
  {
    move_id: 40,
    identifier: 'unsupported-move',
    display_name: '不支持招式',
    type_identifier: 'fairy',
    type_name: '妖精',
    damage_class: 'special',
    power: 95,
    admission: {
      status: 'unsupported',
      selectable: false,
      reason: '当前 version group 不允许精确推演。',
      disabled_reason: '当前 version group 不允许精确推演。',
      missing_mechanism_identifiers: ['version-group-legality'],
    },
  },
];

/**
 * 挂载候选池并提供可更新的 v-model 测试壳。
 *
 * @param modelValue 初始已选 move_id。
 * @param remainingGlobalSlots 双方总预算剩余槽位。
 * @returns 可检查事件和可访问状态的 Vue wrapper。
 */
function mountSelector(
  modelValue: readonly number[] = [],
  remainingGlobalSlots: number = 20,
) {
  return mount(CandidateMovePoolSelector, {
    props: {
      side: 'attacker',
      title: '攻击方候选技能池',
      moves: MOVES,
      modelValue,
      loading: false,
      disabled: false,
      remainingGlobalSlots,
    },
  });
}

describe('CandidateMovePoolSelector', () => {
  it('keeps partial and unsupported moves visible but non-selectable with text reasons', async () => {
    /** 禁用状态由 aria-disabled、大写状态标签和原因文本共同表达，不只依赖颜色。 */
    const wrapper = mountSelector();
    const partial = wrapper.get('[data-move-id="30"]');
    const unsupported = wrapper.get('[data-move-id="40"]');

    expect(partial.attributes('aria-disabled')).toBe('true');
    expect(unsupported.attributes('aria-disabled')).toBe('true');
    expect(wrapper.text()).toContain('PARTIAL');
    expect(wrapper.text()).toContain('dynamic-power-context');
    expect(wrapper.text()).toContain('UNSUPPORTED');
    expect(wrapper.text()).toContain('version-group-legality');

    await partial.trigger('click');
    await unsupported.trigger('click');
    expect(wrapper.emitted('update:modelValue')).toBeUndefined();
  });

  it('treats supported and no_effect as selectable admissions', async () => {
    /** no_effect 是已经明确验证无需额外 effect 的可执行状态，不能误当成禁用项。 */
    const wrapper = mountSelector();
    expect(wrapper.text()).toContain('NO_EFFECT');
    expect(wrapper.get('[data-move-id="10"]').attributes('aria-disabled')).toBe('false');
    await wrapper.get('[data-move-id="10"]').trigger('click');
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([[10]]);
  });

  it('emits normalized IDs and keeps selected moves removable at the global limit', async () => {
    /** 新增时按 move_id 升序规范化；预算耗尽后禁止新选，但不能锁死已有候选的移除入口。 */
    const wrapper = mountSelector([20], 1);
    await wrapper.get('[data-move-id="10"]').trigger('click');
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([[10, 20]]);

    await wrapper.setProps({ modelValue: [10, 20], remainingGlobalSlots: 0 });
    expect(wrapper.get('[data-move-id="10"]').attributes('aria-disabled')).toBe('false');
    await wrapper.get('[data-move-id="10"]').trigger('click');
    expect(wrapper.emitted('update:modelValue')?.[1]).toEqual([[20]]);
  });
});
