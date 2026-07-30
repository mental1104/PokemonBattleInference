import { flushPromises, mount } from '@vue/test-utils';
import { afterEach, describe, expect, it, vi } from 'vitest';
import StatConfigurationPicker from './StatConfigurationPicker.vue';

const snapshot = 'preset-snapshot:test';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('StatConfigurationPicker', () => {
  it('loads configurations, emits fallback snapshot, and limits EV edits', async () => {
    /** 共享配置组件必须在 Pokémon 选中后读取后端统一列表，并把选中值写成快照。 */
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/natures')) {
        return response([
          { identifier: 'hardy', label: 'Hardy', increased_stat: null, decreased_stat: null },
          { identifier: 'bold', label: 'Bold', increased_stat: 'defense', decreased_stat: 'attack' },
        ]);
      }
      if (url.includes('/stat-configurations') && !url.includes('/natures')) {
        return response({
          items: [
            configuration('builtin:max_hp', 'max_hp', '满 HP', snapshot),
          ],
          visible_items: [
            configuration('builtin:max_hp', 'max_hp', '满 HP', snapshot),
          ],
          default_visible_limit: 6,
          fallback_id: 'builtin:max_hp',
        });
      }
      throw new Error(`unexpected fetch ${url}`);
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

    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([snapshot]);
    await wrapper.get('button.preset-button:last-child').trigger('click');
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
  });
});

function response(payload: unknown): Response {
  /** 创建最小 fetch Response 替身，满足组件 API client 读取 JSON 的需求。 */
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  } as Response;
}

function configuration(
  id: string,
  key: string,
  name: string,
  snapshotProfileId: string,
) {
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
  };
}
