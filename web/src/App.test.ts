import { shallowMount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import App from './App.vue';

describe('App home tabs', () => {
  it('keeps the damage calculator as default and switches to the independent inference page', async () => {
    /**
     * 首页需要在不引入前端路由复杂度的前提下保留原单次伤害计算器，并为 issue #33 提供真正独立的多回合推演页面。测试使用浅挂载隔离两个重型子页面，先确认默认页签仍渲染 DamageCalculatorView，避免现有用户入口被替换；随后点击“多回合战斗推演”，断言 BattleInferenceView 出现、按钮激活状态同步切换且原页面被 KeepAlive 隐藏。该场景直接验收用户要求的首页 Tab 切换，而不是只证明新组件文件存在。
     */
    const wrapper = shallowMount(App);
    const buttons = wrapper.findAll('.home-tabs__actions button');

    expect(buttons).toHaveLength(2);
    expect(wrapper.find('damage-calculator-view-stub').exists()).toBe(true);
    expect(wrapper.find('battle-inference-view-stub').exists()).toBe(false);
    expect(buttons[0].classes()).toContain('home-tab--active');

    await buttons[1].trigger('click');

    expect(wrapper.find('damage-calculator-view-stub').exists()).toBe(false);
    expect(wrapper.find('battle-inference-view-stub').exists()).toBe(true);
    expect(buttons[1].classes()).toContain('home-tab--active');
  });
});
