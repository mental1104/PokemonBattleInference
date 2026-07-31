import { flushPromises, mount } from '@vue/test-utils';
import { defineComponent, h } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getPokemonDetail,
  listBattleItems,
  listPokemonAbilities,
  listStatPresets,
  type MoveSearchItem,
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

const MOVE: MoveSearchItem = {
  move_id: 418,
  identifier: 'bullet-punch',
  display_name: '子弹拳',
  type: 'steel',
  type_name: '钢',
  category: 'physical',
  power: 40,
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
    /** 只展示 Pokémon 名称，便于区分弹窗草稿和紧凑摘要行。 */
    return () => h(
      'div',
      { class: 'pokemon-summary-card-stub' },
      (props.pokemon as PokemonDetail | null)?.display_name ?? '未选择',
    );
  },
});

const MoveSelectorStub = defineComponent({
  name: 'MoveSelector',
  emits: ['select', 'clearSelection'],
  setup(_props, { emit }) {
    /** 渲染显式招式选择按钮，使保存按钮从不完整转为可用。 */
    return () => h('section', { class: 'move-selector-stub' }, [
      h(
        'button',
        {
          type: 'button',
          'data-testid': 'choose-target-move',
          onClick: () => emit('select', MOVE),
        },
        '选择子弹拳',
      ),
    ]);
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
  listStatPresetsMock.mockReset().mockResolvedValue({
    attacker: [{ key: 'max_atk_neutral', label: '满攻', assumption: 'Attack 252' }],
    defender: [{ key: 'max_hp', label: '满 HP', assumption: 'HP 252' }],
  });
});

describe('ConfigurationSolverView goal detail dialog', () => {
  it('keeps all detailed parameters in the dialog and one compact row in the list', async () => {
    /**
     * 新增攻目标时，Pokémon、次数、随机档、道具、特性、配置与招式必须全部位于弹窗。
     * 保存前列表为空；完成全部必填项后只生成一条紧凑摘要，列表中不能继续渲染详细选择器。
     */
    const wrapper = mount(ConfigurationSolverView, {
      global: {
        stubs: {
          PokemonSelector: PokemonSelectorStub,
          PokemonSummaryCard: PokemonSummaryCardStub,
          ItemSelector: { template: '<section class="item-selector-stub" />' },
          AbilitySelector: { template: '<section class="ability-selector-stub" />' },
          StatConfigurationPicker: { template: '<section class="stat-picker-stub" />' },
          MoveSelector: MoveSelectorStub,
        },
      },
    });
    await flushPromises();

    await wrapper.get('[data-testid="open-attack-goal-dialog"]').trigger('click');

    const dialog = wrapper.get('[data-testid="goal-dialog-backdrop"]');
    expect(dialog.find('.item-selector-stub').exists()).toBe(true);
    expect(dialog.find('.ability-selector-stub').exists()).toBe(true);
    expect(dialog.find('.stat-picker-stub').exists()).toBe(true);
    expect(dialog.find('.move-selector-stub').exists()).toBe(true);
    expect(wrapper.findAll('[data-testid="goal-summary-row"]')).toHaveLength(0);

    await dialog.get('[data-testid="choose-target-pokemon"]').trigger('click');
    await flushPromises();
    await dialog.get('[data-testid="choose-target-move"]').trigger('click');
    await wrapper.get('[data-testid="confirm-goal-dialog"]').trigger('click');
    await flushPromises();

    expect(wrapper.find('[data-testid="goal-dialog-backdrop"]').exists()).toBe(false);
    expect(wrapper.findAll('[data-testid="goal-summary-row"]')).toHaveLength(1);
    const summary = wrapper.get('[data-testid="goal-summary-row"]');
    expect(summary.text()).toContain('仙子伊布');
    expect(summary.text()).toContain('子弹拳');
    expect(summary.text()).toContain('1 次');
    expect(wrapper.get('.goal-column').find('.item-selector-stub').exists()).toBe(false);
    expect(wrapper.get('.goal-column').find('.ability-selector-stub').exists()).toBe(false);
    expect(wrapper.get('.goal-column').find('.stat-picker-stub').exists()).toBe(false);
    expect(wrapper.get('.goal-column').find('.move-selector-stub').exists()).toBe(false);
  });

  it('opens the compact row for isolated detail editing and applies changes only after save', async () => {
    /**
     * 点击摘要行后应重新打开完整参数弹窗。修改次数时列表仍显示旧值；点击保存修改后，
     * 同一目标行原子更新为新次数，避免弹窗输入过程直接污染已选列表。
     */
    const wrapper = mount(ConfigurationSolverView, {
      global: {
        stubs: {
          PokemonSelector: PokemonSelectorStub,
          PokemonSummaryCard: PokemonSummaryCardStub,
          ItemSelector: { template: '<section class="item-selector-stub" />' },
          AbilitySelector: { template: '<section class="ability-selector-stub" />' },
          StatConfigurationPicker: { template: '<section class="stat-picker-stub" />' },
          MoveSelector: MoveSelectorStub,
        },
      },
    });
    await flushPromises();
    await wrapper.get('[data-testid="open-defense-goal-dialog"]').trigger('click');
    await wrapper.get('[data-testid="choose-target-pokemon"]').trigger('click');
    await flushPromises();
    await wrapper.get('[data-testid="choose-target-move"]').trigger('click');
    await wrapper.get('[data-testid="confirm-goal-dialog"]').trigger('click');
    await flushPromises();

    const summaryButton = wrapper.get('.goal-summary-row__main');
    expect(summaryButton.text()).toContain('1 次');
    await summaryButton.trigger('click');

    const repetitions = wrapper.get('.goal-condition-panel input');
    await repetitions.setValue('3');
    expect(wrapper.get('.goal-summary-row__main').text()).toContain('1 次');

    await wrapper.get('[data-testid="confirm-goal-dialog"]').trigger('click');
    await flushPromises();

    expect(wrapper.get('.goal-summary-row__main').text()).toContain('3 次');
    expect(wrapper.findAll('[data-testid="goal-summary-row"]')).toHaveLength(1);
  });
});
