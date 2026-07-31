import { nextTick } from 'vue';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  calculateDamage,
  getPokemonDetail,
  listBattleItems,
  listPokemonAbilities,
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
  listPokemonAbilities: vi.fn(),
  listStatPresets: vi.fn(),
  createNeutralBattleStatStages: vi.fn(() => ({
    attack: 0,
    defense: 0,
    special_attack: 0,
    special_defense: 0,
    speed: 0,
    accuracy: 0,
    evasion: 0,
  })),
  hasNonNeutralBattleStatStages: vi.fn((stages) =>
    Object.values(stages).some((value) => value !== 0),
  ),
}));

const calculateDamageMock = vi.mocked(calculateDamage);
const getPokemonDetailMock = vi.mocked(getPokemonDetail);
const listBattleItemsMock = vi.mocked(listBattleItems);
const listPokemonAbilitiesMock = vi.mocked(listPokemonAbilities);
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
    included: ['已实现持有道具', '已实现特性'],
    excluded: [],
  },
  warnings: [],
};

beforeEach(() => {
  calculateDamageMock.mockReset().mockResolvedValue(DAMAGE_RESPONSE);
  getPokemonDetailMock.mockReset();
  listPokemonAbilitiesMock.mockReset().mockResolvedValue([]);
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
  it('submits independent items and required abilities then invalidates changed results', async () => {
    /**
     * 该场景验证特性接入不能破坏已合入的双方道具状态：攻击方和防守方分别保存 life-orb 与 eviolite，
     * 同时必须显式选择 technician 和 static，提交时四个 identifier 都进入各自 CalculatorPokemonInput。
     * 服务端返回结果后，无论修改防守方道具还是任一特性都应把旧结果标记为 stale；测试先改变防守方道具，
     * 保护双方道具继续独立，再确认请求中的必选特性没有被默认值、另一侧状态或 UI 实现标记覆盖。
     */
    const calculator = useDamageCalculator();
    calculator.attacker.value = ATTACKER;
    calculator.defender.value = DEFENDER;
    calculator.move.value = MOVE;
    calculator.attackerAbilityIdentifier.value = 'technician';
    calculator.defenderAbilityIdentifier.value = 'static';

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
        ability_identifier: 'technician',
        item_identifier: 'life-orb',
      },
      defender: {
        pokemon_id: 25,
        level: 50,
        stat_preset: 'max_hp',
        ability_identifier: 'static',
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

  it('submits non-neutral stat stages independently and invalidates the result when they change', async () => {
    /**
     * 攻击方攻击正二与命中正一、防守方防御负一与回避正二必须作为两份独立 stat_stages 快照进入请求，
     * 而不是共享同一个对象或只提交影响伤害的四项字段。计算完成后再次替换攻击方速度等级，旧结果应立即
     * 标记为 stale，证明速度、命中和回避虽然当前不改变单次伤害值，仍属于用户输入和结果有效性合同。
     * 该测试同时保护中性请求继续省略 stat_stages 以兼容旧客户端，而非中性请求完整发送七项字段，避免
     * 后端默认值吞掉用户在摘要卡红框中的选择。
     */
    const calculator = useDamageCalculator();
    calculator.attacker.value = ATTACKER;
    calculator.defender.value = DEFENDER;
    calculator.move.value = MOVE;
    calculator.attackerAbilityIdentifier.value = 'technician';
    calculator.defenderAbilityIdentifier.value = 'static';
    calculator.attackerStatStages.value = {
      attack: 2,
      defense: 0,
      special_attack: 0,
      special_defense: 0,
      speed: 0,
      accuracy: 1,
      evasion: 0,
    };
    calculator.defenderStatStages.value = {
      attack: 0,
      defense: -1,
      special_attack: 0,
      special_defense: 0,
      speed: 0,
      accuracy: 0,
      evasion: 2,
    };

    await calculator.submit();

    expect(calculateDamageMock).toHaveBeenCalledWith({
      ruleset_id: 'pokemon-champion',
      attacker: expect.objectContaining({
        stat_stages: {
          attack: 2,
          defense: 0,
          special_attack: 0,
          special_defense: 0,
          speed: 0,
          accuracy: 1,
          evasion: 0,
        },
      }),
      defender: expect.objectContaining({
        stat_stages: {
          attack: 0,
          defense: -1,
          special_attack: 0,
          special_defense: 0,
          speed: 0,
          accuracy: 0,
          evasion: 2,
        },
      }),
      move_id: 418,
    });
    expect(calculator.staleResult.value).toBe(false);

    calculator.attackerStatStages.value = {
      ...calculator.attackerStatStages.value,
      speed: 1,
    };
    await nextTick();

    expect(calculator.staleResult.value).toBe(true);
  });
});
