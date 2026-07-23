import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import App from './App.vue';

describe('App home tabs', () => {
  it('keeps the damage calculator as default and switches to the independent inference page', async () => {
    /**
     * 首页需要在不引入前端路由复杂度的前提下保留原单次伤害计算器，并为 issue #33 提供真正独立的多回合推演页面。测试只替换两个重型业务子页，保留真实 KeepAlive 和 App 模板执行；先确认默认页签渲染伤害计算页，避免现有用户入口被替换，再点击“多回合战斗推演”并确认独立页面进入活动 DOM、按钮状态同步切换。该场景直接验收首页 Tab 用户旅程，同时避免浅挂载把 KeepAlive 本身替换后造成的假阴性。
     */
    const wrapper = mount(App, {
      global: {
        stubs: {
          DamageCalculatorView: {
            template: '<section data-test="damage-page" />',
          },
          BattleInferenceView: {
            template: '<section data-test="inference-page" />',
          },
        },
      },
    });
    const buttons = wrapper.findAll('.home-tabs__actions button');

    expect(buttons).toHaveLength(2);
    expect(wrapper.find('[data-test="damage-page"]').exists()).toBe(true);
    expect(wrapper.find('[data-test="inference-page"]').exists()).toBe(false);
    expect(buttons[0].classes()).toContain('home-tab--active');

    await buttons[1].trigger('click');

    expect(wrapper.find('[data-test="inference-page"]').exists()).toBe(true);
    expect(buttons[1].classes()).toContain('home-tab--active');
  });
});
