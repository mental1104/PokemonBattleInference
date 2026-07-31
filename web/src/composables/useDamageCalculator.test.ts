import { nextTick } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  calculateDamage,
  getPokemonDetail,
  listBattleItems,
  listStatPresets,
  type CalculateDamageResponse,
  type MoveSearchItem,
  type PokemonDetail,
} from '../api/calculator';
import { useDamageCalculator } from './useDamageCalculator';

vi.mock('../api/calculator', () => ({
  calculateDamage: vi.fn(),
  getPokemonDetail: vi.fn(),
  listBattleItems: vi.fn(),
  listStatPresets: vi.fn(),
}));

const calculateDamageMock = vi.mocked(calculateDamage);
const getPokemonDetailMock = vi.mocked(getPokemonDetail);
const listBattleItemsMock = vi.mocked(listBattleItems);
const listStatPresetsMock = vi.mocked(listStatPresets);

const ATTACKER: PokemonDetail = {
  pokemon_id: 212,
  identifier: 'scizor',
  display_name: '巨钳螳螂',
  form_identifier: 'scizor',
  types: ['bug', 'steel'],
  type_names: ['虫', '钢'],
  sprite_url: '/sprites/212.png',
  base_stats: {
    hp: 70,
    attack: 130,
    defense: 100,
    special_attack: 55,
    special_defense: 80,
    speed: 65,
  },
};

const DEFENDER: PokemonDetail = {
  pokemon_id: 25,
  identifier: 'pikachu',
  display_name: '皮卡丘',
  form_identifier: 'pikachu',
  types: ['electric'],
  type_names: ['电'],
  sprite_url: '/sprites/25.png',
  base_stats: {
    hp: 35,
    attack: 55,
    defense: 40,
    special_attack: 50,
    special_defense: 50,
    speed: 90,
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

const DAMAGE_RESPONSE: CalculateDamageResponse = {
  ruleset_id: 'pokemon-champion',
  ruleset_name: 'Pokemon Champion',
  attacker: {
    pokemon_id: ATTACKER.pokemon_id,
    identifier: ATTACKER.identifier,
    display_name: ATTACKER.display_name,
    sprite_url: ATTACKER.sprite_url,
    level: 50,
    preset_label: '满攻',
    preset_assumption: '50 级 · 252 Atk · 中性性格',
    stats: ATTACKER.base_stats,
    effective_attack: 182,
    effective_hp: null,
    effective_defense: null,
  },
  defender: {
    pokemon_id: DEFENDER.pokemon_id,
    identifier: DEFENDER.identifier,
    display_name: DEFENDER.display_name,
    sprite_url: DEFENDER.sprite_url,
    level: 50,
    preset_label: '满 HP',
    preset_assumption: '50 级 · 252 HP · 防御/特防无投入',
    stats: DEFENDER.base_stats,
    effective_attack: null,
    effective_hp: 142,
    effective_defense: 90,
  },
  move: MOVE,
  damage: {
    min: 20,
    max: 24,
    min_percent: 14.1,
    max_percent: 16.9,
    expected: 22,
    expected_percent: 15.5,
    rolls: [20, 21, 22, 23, 24],
  },
  ko: {
    ohko_probability: 0,
    two_hit_ko_probability: 0,
    guaranteed_ohko: false,
    guaranteed_2hko: false,
  },
  modifiers: [],
  scope: {
    mode: 'basic',
    included: ['已实现持有道具'],
    excluded: [],
  },
  warnings: [],
};

beforeEach(() => {
  calculateDamageMock.mockReset().mockResolvedValue(DAMAGE_RESPONSE);
  getPokemonDetailMock.mockReset();
  listStatPresetsMock.mockReset().mockResolvedValue({ attacker: [], defender: [] });
  listBattleItemsMock.mockReset().mockResolvedValue([
    {
      item_id: null,
      identifier: 'none',
      display_name: '不携带道具',
      effect_identifier: null,
      sprite_url: null,
    },
    {
      item_id: 247,
      identifier: 'life-orb',
      display_name: '生命宝珠',
      effect_identifier: 'life-orb',
      sprite_url: '/api/v1/assets/items/life-orb/sprite',
    },
    {
      item_id: 538,
      identifier: 'eviolite',
      display_name: '进化奇石',
      effect_identifier: 'eviolite',
      sprite_url: '/api/v1/assets/items/eviolite/sprite',
    },
  ]);
});

describe('useDamageCalculator', () => {
  it('submits independent attacker and defender items and invalidates the result after either changes', async () => {
    /**
     * 该场景直接验证单次伤害计算器的状态边界：攻击方和防守方共享服务端返回的道具候选，但必须分别保存
     * life-orb 与 eviolite 两个选择，并在提交时把它们写入各自的 CalculatorPokemonInput，不能遗漏防守方字段
     * 或错误复用攻击方值。服务端返回结果后，再修改防守方道具应立刻把旧结果标记为 stale，保证用户不会在
     * 已更换防守道具的情况下继续把旧伤害区间当作有效结论；该监听语义也必须与攻击方道具保持完全对称。
     */
    const calculator = useDamageCalculator();
    calculator.attacker.value = ATTACKER;
    calculator.defender.value = DEFENDER;
    calculator.move.value = MOVE;

    await calculator.loadItems();
    calculator.attackerItemIdentifier.value = 'life-orb';
    calculator.defenderItemIdentifier.value = 'eviolite';
    await calculator.submit();

    expect(calculateDamageMock).toHaveBeenCalledWith({
      ruleset_id: 'pokemon-champion',
      attacker: {
        pokemon_id: 212,
        level: 50,
        stat_preset: 'max_atk_neutral',
        item_identifier: 'life-orb',
      },
      defender: {
        pokemon_id: 25,
        level: 50,
        stat_preset: 'max_hp',
        item_identifier: 'eviolite',
      },
      move_id: 418,
    });
    expect(calculator.result.value).toEqual(DAMAGE_RESPONSE);
    expect(calculator.staleResult.value).toBe(false);

    calculator.defenderItemIdentifier.value = 'none';
    await nextTick();

    expect(calculator.staleResult.value).toBe(true);
  });
});
