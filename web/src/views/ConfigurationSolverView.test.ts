import { flushPromises, mount } from '@vue/test-utils';
import { defineComponent, h } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getPokemonDetail,
  listBattleItems,
  listPokemonAbilities,
  listStatPresets,
  type PokemonDetail,
} from '../api/calculator';
import ConfigurationSolverView from './ConfigurationSolverView.vue';

vi.mock('../api/calculator', () => ({
  getPokemonDetail: vi.fn(),
  listBattleItems: vi.fn(),
  listPokemonAbilities: vi.fn(),
  listStatPresets: vi.fn(),
  listPokemonMoves: vi.fn(),
  searchPokemon: vi.fn(),
}));

vi.mock('../api/configurationSolver', () => ({
  solveConfiguration: vi.fn(),
}));

const getPokemonDetailMock = vi.mocked(getPokemonDetail);
const listBattleItemsMock = vi.mocked(listBattleItems);
const listPokemonAbilitiesMock = vi.mocked(listPokemonAbilities);
const listStatPresetsMock = vi.mocked(listStatPresets);

const TARGET: PokemonDetail = {
  pokemon_id: 700,
  identifier: 'sylveon',
  display_name: '仙子伊布',
  form_identifier: 'sylveon',
  types: ['fairy'],
  type_names: ['妖精'],
  sprite_url: '/sprites/700.png',
  base_stats: {
    hp: 95,
    attack: 65,
    defense: 65,
    special_attack: 110,
    special_defense: 130,
    speed: 60,
  },
};

const PokemonSelectorStub = defineComponent({
  name: 'PokemonSelector',
  props: {
    title: { type: String, required: true },
  },
  emits: ['select'],
  setup(props, { emit }) {
    /** 渲染可由测试主动选择固定目标的轻量 Pokémon 选择器。 */
    return () => h('section', { class: 'pokemon-selector-stub' }, [
      h('span', props.title),
      h(
        'button',
        {
          type: 'button',
          'data-testid': 'choose-target-pokemon',
          onClick: () => emit('select', TARGET),
        },
        '选择仙子伊布',
      ),
    ]);
  },
});

const PokemonSummaryCardStub = defineComponent({
  name: 'PokemonSummaryCard',
  props: {
    pokemon: { type: Object, default: null },
  },
  setup(props) {
    /** 只展示目标名称，便于断言确认后卡片已经进入已选列表。 */
    return () => h(
      'div',
      { class: 'pokemon-summary-card-stub' },
      (props.pokemon as PokemonDetail | null)?.display_name ?? '未选择',
    );
  },
});

beforeEach(() => {
  window.localStorage.clear();
  getPokemonDetailMock.mockReset().mockResolvedValue(TARGET);
  listPokemonAbilitiesMock.mockReset().mockResolvedValue([{
    ability_id: 56,
    identifier: 'cute-charm',
    display_name: '迷人之躯',
    slot: 1,
    is_hidden: false,
    implemented: false,
  }]);
  listBattleItemsMock.mockReset().mockResolvedValue([{
    item_id: null,
    identifier: 'none',
    display_name: '不携带道具',
    effect_identifier: null,
    sprite_url: null,
  }]);
  listStatPresetsMock.mockReset().mockResolvedValue({ attacker: [], defender: [] });
});

describe('ConfigurationSolverView goal dialog', () => {
  it('keeps pending Pokémon out of the selected list until confirmation', async () => {
    /**
     * 点击“添加攻目标”后只能出现独立弹窗，攻目标列仍为空；在弹窗中选择并确认后，
     * 才生成包含目标摘要的卡片。已选卡片内部不再渲染 Pokémon 搜索器，避免待选列表
     * 与已经确认的对象出现在同一视觉层级。
     */
    const wrapper = mount(ConfigurationSolverView, {
      global: {
        stubs: {
          PokemonSelector: PokemonSelectorStub,
          PokemonSummaryCard: PokemonSummaryCardStub,
          ItemSelector: { template: '<section class="item-selector-stub" />' },
          AbilitySelector: { template: '<section class="ability-selector-stub" />' },
          StatConfigurationPicker: { template: '<section class="stat-picker-stub" />' },
          MoveSelector: { template: '<section class="move-selector-stub" />' },
        },
      },
    });
    await flushPromises();

    expect(wrapper.findAll('.goal-editor')).toHaveLength(0);

    await wrapper.get('[data-testid="open-attack-goal-dialog"]').trigger('click');

    expect(wrapper.find('[data-testid="goal-dialog-backdrop"]').exists()).toBe(true);
    expect(wrapper.findAll('.goal-editor')).toHaveLength(0);

    await wrapper
      .get('[data-testid="goal-dialog-backdrop"] [data-testid="choose-target-pokemon"]')
      .trigger('click');
    await wrapper.get('[data-testid="confirm-goal-dialog"]').trigger('click');
    await flushPromises();

    expect(wrapper.find('[data-testid="goal-dialog-backdrop"]').exists()).toBe(false);
    expect(wrapper.findAll('.goal-editor')).toHaveLength(1);
    expect(wrapper.get('.goal-editor .pokemon-summary-card-stub').text()).toBe('仙子伊布');
    expect(wrapper.get('.goal-column').find('.pokemon-selector-stub').exists()).toBe(false);
  });
});
