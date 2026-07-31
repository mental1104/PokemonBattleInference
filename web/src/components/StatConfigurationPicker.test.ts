import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { StatConfiguration } from '../api/statConfigurations';
import StatConfigurationPicker from './StatConfigurationPicker.vue';

const snapshot = 'preset-snapshot:test';

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('StatConfigurationPicker', () => {
  it('opens management with the current preset in a read-only right-side editor', async () => {
    /** 管理入口必须直接打开两栏工作区，右侧默认载入当前配置；内置预设只能查看不能编辑。 */
    const maxHp = configuration('builtin:max_hp', 'max_hp', '满 HP', snapshot);
    vi.stubGlobal('fetch', statConfigFetch([maxHp]));

    const wrapper = mount(StatConfigurationPicker, {
      props: {
        title: '耐久配置',
        role: 'defender',
        pokemonId: 700,
        pokemonName: 'Sylveon',
        modelValue: '',
      },
    });
    await flushPromises();

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([snapshot]);
    expect(wrapper.find('.stat-config-add-button').exists()).toBe(false);
    await wrapper.get('button.secondary-button').trigger('click');
    await flushPromises();

    expect(wrapper.get('.stat-config-sidebar-item.active').text()).toContain('满 HP');
    expect(wrapper.get('.stat-config-editor').text()).toContain('预设配置，只能查看。');
    expect((wrapper.get('input[maxlength="48"]').element as HTMLInputElement).disabled).toBe(true);
    expect((wrapper.findAll('input[type="range"]')[0].element as HTMLInputElement).disabled).toBe(true);
    expect(wrapper.find('button.primary-button').exists()).toBe(false);
    expect(wrapper.get('.stat-config-editor').text()).not.toContain('隐藏');
    expect(wrapper.get('.stat-config-editor').text()).not.toContain('删除');
  });

  it('creates a custom configuration from the sidebar plus button and limits EV edits', async () => {
    /** 新建入口必须在左侧栏顶部，点击后右侧同区编辑并通过保存配置提交创建请求。 */
    const requests: RequestInit[] = [];
    const created = configuration('custom:bulk', 'bulk', 'Custom Bulk', 'preset-snapshot:custom', {
      source: 'custom',
      editable: true,
      deletable: true,
    });
    vi.stubGlobal('fetch', statConfigFetch([configuration('builtin:max_hp', 'max_hp', '满 HP', snapshot)], {
      requests,
      created,
    }));

    const wrapper = mount(StatConfigurationPicker, {
      props: {
        title: '耐久配置',
        role: 'defender',
        pokemonId: 700,
        pokemonName: 'Sylveon',
        modelValue: '',
      },
    });
    await flushPromises();

    await wrapper.get('button.secondary-button').trigger('click');
    await wrapper.get('.stat-config-add-button').trigger('click');
    await wrapper.find('input[maxlength="48"]').setValue('Custom Bulk');
    const numberInputs = wrapper.findAll('input[type="number"]');

    await numberInputs[0].setValue('252');
    await numberInputs[0].trigger('change');
    await numberInputs[1].setValue('252');
    await numberInputs[1].trigger('change');
    await numberInputs[2].setValue('252');
    await numberInputs[2].trigger('change');

    expect(wrapper.text()).toContain('EV 504 / 510');
    expect(wrapper.text()).toContain('剩余 6');
    await wrapper.get('form.stat-config-editor').trigger('submit');
    await flushPromises();

    const createRequest = requests.find((request) => request.method === 'POST');
    expect(createRequest).toBeDefined();
    expect(JSON.parse(String(createRequest?.body))).toMatchObject({
      name: 'Custom Bulk',
      role: 'defender',
      binding_kind: 'global',
      pokemon_id: null,
    });
    const emittedSelections = wrapper.emitted('update:modelValue') ?? [];
    expect(emittedSelections[emittedSelections.length - 1]).toEqual(['preset-snapshot:custom']);
  });

  it('saves sidebar order after a long-press drag on the handle', async () => {
    /** 排序必须从三条杠手柄长按进入拖拽状态，释放后通过 order API 保存当前可见顺序。 */
    vi.useFakeTimers();
    const requests: RequestInit[] = [];
    vi.stubGlobal('fetch', statConfigFetch([
      configuration('builtin:a', 'a', '配置 A', 'snapshot:a'),
      configuration('builtin:b', 'b', '配置 B', 'snapshot:b'),
    ], { requests }));

    const wrapper = mount(StatConfigurationPicker, {
      props: {
        title: '攻击配置',
        role: 'attacker',
        pokemonId: 1,
        pokemonName: 'Bulbasaur',
        modelValue: 'snapshot:a',
      },
    });
    await flushPromises();

    await wrapper.get('button.secondary-button').trigger('click');
    const handles = wrapper.findAll('.stat-config-drag-handle');
    await handles[0].trigger('pointerdown');
    await vi.advanceTimersByTimeAsync(300);
    await wrapper.findAll('.stat-config-sidebar-item')[1].trigger('pointerenter');
    await wrapper.get('.stat-config-modal').trigger('pointerup');
    await flushPromises();

    const orderRequest = requests.find((request) => request.method === 'POST' && String(request.body).includes('references'));
    expect(orderRequest).toBeDefined();
    expect(JSON.parse(String(orderRequest?.body)).references).toEqual([
      { source: 'builtin', key: 'b' },
      { source: 'builtin', key: 'a' },
    ]);
  });

  it('deletes custom configurations and never exposes deletion for builtin presets', async () => {
    /** 管理区不再提供隐藏操作；只有后端标记为 deletable 的自定义配置可以发起删除。 */
    const requests: RequestInit[] = [];
    vi.stubGlobal('fetch', statConfigFetch([
      configuration('builtin:max_hp', 'max_hp', '满 HP', snapshot),
      configuration('custom:bulk', 'bulk', 'Custom Bulk', 'preset-snapshot:custom', {
        source: 'custom',
        editable: true,
        deletable: true,
      }),
    ], { requests }));

    const wrapper = mount(StatConfigurationPicker, {
      props: {
        title: '耐久配置',
        role: 'defender',
        pokemonId: 700,
        pokemonName: 'Sylveon',
        modelValue: 'preset-snapshot:custom',
      },
    });
    await flushPromises();

    await wrapper.get('button.secondary-button').trigger('click');
    expect(wrapper.get('.stat-config-editor').text()).not.toContain('隐藏');
    expect(wrapper.get('.stat-config-editor').text()).toContain('删除');
    await wrapper.findAll('.stat-config-sidebar-item')[0].trigger('click');
    expect(wrapper.get('.stat-config-editor').text()).not.toContain('删除');

    await wrapper.findAll('.stat-config-sidebar-item')[1].trigger('click');
    await wrapper.findAll('button.secondary-button').find((button) => button.text() === '删除')?.trigger('click');
    await wrapper.findAll('button.primary-button').find((button) => button.text() === '确认删除')?.trigger('click');
    await flushPromises();

    expect(requests.some((request) => request.method === 'DELETE')).toBe(true);
  });
});

function response(payload: unknown, status: number = 200): Response {
  /** 创建最小 fetch Response 替身，满足组件 API client 读取 JSON 的需求。 */
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

function naturesResponse(): unknown {
  /** 返回测试需要的最小性格元数据集合。 */
  return [
    { identifier: 'hardy', label: 'Hardy', increased_stat: null, decreased_stat: null },
    { identifier: 'bold', label: 'Bold', increased_stat: 'defense', decreased_stat: 'attack' },
  ];
}

function statConfigFetch(
  items: StatConfiguration[],
  options: {
    requests?: RequestInit[];
    created?: StatConfiguration;
  } = {},
): (input: RequestInfo | URL, init?: RequestInit) => Promise<Response> {
  /** 创建覆盖性格、列表、创建和排序接口的 fetch mock。 */
  return async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    options.requests?.push(init);
    if (url.includes('/natures')) {
      return response(naturesResponse());
    }
    if (init.method === 'POST' && url.endsWith('/stat-configurations')) {
      return response(options.created ?? items[0], 201);
    }
    if (url.includes('/stat-configurations/order')) {
      return response(undefined, 204);
    }
    if (init.method === 'DELETE' && url.includes('/stat-configurations/')) {
      return response(undefined, 204);
    }
    if (url.includes('/stat-configurations') && !url.includes('/natures')) {
      return response({
        items,
        visible_items: items.filter((item) => item.visible),
        default_visible_limit: 6,
        fallback_id: items[0]?.id ?? null,
      });
    }
    throw new Error(`unexpected fetch ${url}`);
  };
}

function configuration(
  id: string,
  key: string,
  name: string,
  snapshotProfileId: string,
  overrides: Partial<StatConfiguration> = {},
): StatConfiguration {
  /** 创建后端统一配置响应 fixture。 */
  return {
    id,
    source: 'builtin',
    key,
    name,
    nature_id: 'hardy',
    evs: { hp: 252, attack: 0, defense: 0, special_attack: 0, special_defense: 0, speed: 0 },
    ivs: { hp: 31, attack: 31, defense: 31, special_attack: 31, special_defense: 31, speed: 31 },
    role: 'defender',
    binding_kind: 'global',
    pokemon_id: null,
    description: 'fixture',
    hidden: false,
    visible: true,
    sort_order: 0,
    editable: false,
    renamable: false,
    deletable: false,
    hideable: true,
    snapshot_profile_id: snapshotProfileId,
    updated_at: null,
    ...overrides,
  };
}
