import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import {
  createNeutralBattleStatStages,
  type BattleStatStages,
} from '../api/calculator';
import BattleStatStageSelector from './BattleStatStageSelector.vue';

describe('BattleStatStageSelector', () => {
  it('renders all seven battle stages and emits an immutable updated snapshot', async () => {
    /**
     * 伤害计算器摘要卡需要同时提供攻击、防御、特攻、特防、速度、回避和命中七项能力等级，并允许每项
     * 从负六选择到正六。测试以全部零级快照挂载组件，确认七个原生 select 与稳定 data-stat-stage 字段
     * 完整存在，再把攻击改为正二、回避改为负一。每次事件都必须发出保留其余字段的新对象，而不能直接
     * 修改传入 props；正数选项还应显示显式加号，帮助用户区分提升与基础值。该场景保护字段顺序、范围、
     * 可访问性标签和不可变更新语义，避免攻击方操作意外污染防守方共享引用。
     */
    const stages = createNeutralBattleStatStages();
    const wrapper = mount(BattleStatStageSelector, {
      props: { modelValue: stages },
    });

    const selects = wrapper.findAll('select');
    expect(selects).toHaveLength(7);
    expect(selects.map((select) => select.attributes('data-stat-stage'))).toEqual([
      'attack',
      'defense',
      'special_attack',
      'special_defense',
      'speed',
      'evasion',
      'accuracy',
    ]);
    expect(selects[0].findAll('option')).toHaveLength(13);
    expect(selects[0].text()).toContain('+6');

    await wrapper.get('[data-stat-stage="attack"]').setValue('2');
    const firstUpdate = wrapper.emitted<[BattleStatStages]>('update:modelValue')?.[0]?.[0];
    expect(firstUpdate).toEqual({ ...stages, attack: 2 });
    expect(stages.attack).toBe(0);

    await wrapper.setProps({ modelValue: firstUpdate });
    await wrapper.get('[data-stat-stage="evasion"]').setValue('-1');
    const secondUpdate = wrapper.emitted<[BattleStatStages]>('update:modelValue')?.[1]?.[0];
    expect(secondUpdate).toEqual({ ...stages, attack: 2, evasion: -1 });
  });
});
