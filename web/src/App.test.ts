import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it } from 'vitest';
import App from './App.vue';

beforeEach(() => {
  window.history.replaceState({}, '', '/');
});

describe('App home tabs', () => {
  it('keeps calculator default and exposes fixed configuration inference', async () => {
    /** 默认入口仍是单次伤害计算，第二页签只承载组合选择后的固定配置精确推演。 */
    const wrapper = mount(App, {
      global: {
        stubs: {
          DamageCalculatorView: { template: '<section data-test="damage-page" />' },
          BattleInferenceView: { template: '<section data-test="inference-page" />' },
        },
      },
    });
    const buttons = wrapper.findAll('.home-tabs__actions button');

    expect(buttons).toHaveLength(2);
    expect(buttons[0].text()).toContain('单次伤害计算');
    expect(buttons[1].text()).toContain('固定配置精确推演');
    expect(wrapper.find('[data-test="damage-page"]').exists()).toBe(true);
    expect(buttons[0].classes()).toContain('home-tab--active');

    await buttons[1].trigger('click');

    expect(wrapper.find('[data-test="inference-page"]').exists()).toBe(true);
    expect(buttons[1].classes()).toContain('home-tab--active');
  });

  it('does not restore the deferred batch-job page from a stale job_id', () => {
    /** 批量任务保留为后端实验能力，旧查询参数不能把默认产品入口重新切回空白结果页。 */
    window.history.replaceState({}, '', '/?job_id=job-restored-89');
    const wrapper = mount(App, {
      global: {
        stubs: {
          DamageCalculatorView: { template: '<section data-test="damage-page" />' },
          BattleInferenceView: { template: '<section data-test="inference-page" />' },
        },
      },
    });

    expect(wrapper.find('[data-test="damage-page"]').exists()).toBe(true);
    expect(wrapper.findAll('.home-tabs__actions button')).toHaveLength(2);
  });
});
