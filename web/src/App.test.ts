import { mount } from '@vue/test-utils';
import { beforeEach, describe, expect, it } from 'vitest';
import App from './App.vue';

beforeEach(() => {
  window.history.replaceState({}, '', '/');
});

describe('App home tabs', () => {
  it('keeps calculator default and opens the independent inference and job result pages', async () => {
    /**
     * 首页继续把单次伤害计算器作为默认入口，同时增加与固定旅程分离的配置空间任务结果页。测试用轻量 stub 保留真实 KeepAlive、页签按钮和 URL 更新逻辑：先确认默认只渲染计算器，再进入固定多回合推演，最后进入配置空间任务并验证 job_id 被写入地址。该场景保护三个产品入口互不覆盖，也证明结果页不要求一次性把 44,100 条配置塞进原有固定旅程组件。
     */
    const wrapper = mount(App, {
      global: {
        stubs: {
          DamageCalculatorView: { template: '<section data-test="damage-page" />' },
          BattleInferenceView: { template: '<section data-test="inference-page" />' },
          BattleInferenceJobView: {
            props: ['jobId'],
            template: '<section data-test="job-page">{{ jobId }}</section>',
          },
        },
      },
    });
    const buttons = wrapper.findAll('.home-tabs__actions button');

    expect(buttons).toHaveLength(3);
    expect(wrapper.find('[data-test="damage-page"]').exists()).toBe(true);
    expect(buttons[0].classes()).toContain('home-tab--active');

    await buttons[1].trigger('click');
    expect(wrapper.find('[data-test="inference-page"]').exists()).toBe(true);
    expect(buttons[1].classes()).toContain('home-tab--active');

    await buttons[2].trigger('click');
    expect(wrapper.find('[data-test="job-page"]').text()).toContain('fixture-running-44100');
    expect(buttons[2].classes()).toContain('home-tab--active');
    expect(new URL(window.location.href).searchParams.get('job_id')).toBe('fixture-running-44100');
  });

  it('restores the configuration-space result page from job_id after refresh', () => {
    /**
     * 用户刷新页面或离开后返回时，任务结果页必须仅凭稳定 job_id 恢复，而不是依赖组件内存或批量 graph artifact。测试在挂载前写入真实查询参数，并确认 App 直接选择任务页签、把 job_id 原样传给结果页，同时不激活计算器和固定旅程。这条合同为后续从 #88 配置页创建真实后台任务后跳转到结果页保留稳定入口。
     */
    window.history.replaceState({}, '', '/?job_id=job-restored-89');
    const wrapper = mount(App, {
      global: {
        stubs: {
          DamageCalculatorView: { template: '<section data-test="damage-page" />' },
          BattleInferenceView: { template: '<section data-test="inference-page" />' },
          BattleInferenceJobView: {
            props: ['jobId'],
            template: '<section data-test="job-page">{{ jobId }}</section>',
          },
        },
      },
    });

    expect(wrapper.find('[data-test="job-page"]').text()).toBe('job-restored-89');
    expect(wrapper.find('[data-test="damage-page"]').exists()).toBe(false);
    expect(wrapper.findAll('.home-tabs__actions button')[2].classes()).toContain('home-tab--active');
  });
});
