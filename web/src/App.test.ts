import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it } from 'vitest';
import App from './App.vue';

beforeEach(() => {
  window.history.replaceState({}, '', '/');
});

describe('App home tabs', () => {
  it('keeps calculator default and exposes solver before fixed configuration inference', async () => {
    /** 默认入口仍是单次伤害计算，配置反向求解排在固定配置精确推演之前。 */
    const wrapper = mount(App, {
      global: {
        stubs: {
          DamageCalculatorView: { template: '<section data-test="damage-page" />' },
          BattleInferenceView: { template: '<section data-test="inference-page" />' },
          ConfigurationSolverView: { template: '<section data-test="solver-page" />' },
          InferenceJobDetailView: { template: '<section data-test="job-detail-page" />' },
        },
      },
    });
    const buttons = wrapper.findAll('.home-tabs__actions button');

    expect(buttons).toHaveLength(3);
    expect(buttons[0].text()).toContain('单次伤害计算');
    expect(buttons[1].text()).toContain('配置反向求解');
    expect(buttons[2].text()).toContain('固定配置精确推演');
    expect(wrapper.find('[data-test="damage-page"]').exists()).toBe(true);
    expect(buttons[0].classes()).toContain('home-tab--active');

    await buttons[1].trigger('click');

    expect(wrapper.find('[data-test="solver-page"]').exists()).toBe(true);
    expect(buttons[1].classes()).toContain('home-tab--active');

    await buttons[2].trigger('click');

    expect(wrapper.find('[data-test="inference-page"]').exists()).toBe(true);
    expect(buttons[2].classes()).toContain('home-tab--active');
  });

  it('does not restore the deferred batch-job page from a stale job_id', () => {
    /** 批量任务保留为后端实验能力，旧查询参数不能把默认产品入口重新切回空白结果页。 */
    window.history.replaceState({}, '', '/?job_id=job-restored-89');
    const wrapper = mount(App, {
      global: {
        stubs: {
          DamageCalculatorView: { template: '<section data-test="damage-page" />' },
          BattleInferenceView: { template: '<section data-test="inference-page" />' },
          ConfigurationSolverView: { template: '<section data-test="solver-page" />' },
          InferenceJobDetailView: { template: '<section data-test="job-detail-page" />' },
        },
      },
    });

    expect(wrapper.find('[data-test="damage-page"]').exists()).toBe(true);
    expect(wrapper.findAll('.home-tabs__actions button')).toHaveLength(3);
  });

  it('opens and restores the inference job detail view from a stable query URL', async () => {
    /** 完成任务需要可刷新、可分享的详情页，因此 App 负责把 job_id 写入 query 参数。 */
    const wrapper = mount(App, {
      global: {
        stubs: {
          DamageCalculatorView: { template: '<section data-test="damage-page" />' },
          BattleInferenceView: {
            template: '<section data-test="inference-page"><button @click="$emit(\'openJob\', \'fixed-one-on-one-job-1\')">open</button></section>',
          },
          ConfigurationSolverView: { template: '<section data-test="solver-page" />' },
          InferenceJobDetailView: {
            props: ['jobId'],
            template: '<section data-test="job-detail-page">{{ jobId }}</section>',
          },
        },
      },
    });

    await wrapper.findAll('.home-tabs__actions button')[2].trigger('click');
    await wrapper.get('[data-test="inference-page"] button').trigger('click');

    expect(wrapper.find('[data-test="job-detail-page"]').text()).toContain('fixed-one-on-one-job-1');
    expect(window.location.search).toContain('view=inference-job');
    expect(window.location.search).toContain('job_id=fixed-one-on-one-job-1');

    window.history.replaceState({}, '', '/?view=inference-job&job_id=fixed-one-on-one-job-restored');
    const restored = mount(App, {
      global: {
        stubs: {
          DamageCalculatorView: { template: '<section data-test="damage-page" />' },
          BattleInferenceView: { template: '<section data-test="inference-page" />' },
          ConfigurationSolverView: { template: '<section data-test="solver-page" />' },
          InferenceJobDetailView: {
            props: ['jobId'],
            template: '<section data-test="job-detail-page">{{ jobId }}</section>',
          },
        },
      },
    });

    expect(restored.find('[data-test="job-detail-page"]').text()).toContain('fixed-one-on-one-job-restored');
  });
});
