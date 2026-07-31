import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getPokemonDetail,
  listBattleItems,
  listPokemonAbilities,
  listStatPresets,
  type MoveSearchItem,
  type PokemonDetail,
} from '../api/calculator';
import {
  solveConfiguration,
  type SolveConfigurationResponse,
} from '../api/configurationSolver';
import { useConfigurationSolver } from './useConfigurationSolver';

vi.mock('../api/calculator', () => ({
  getPokemonDetail: vi.fn(),
  listBattleItems: vi.fn(),
  listPokemonAbilities: vi.fn(),
  listStatPresets: vi.fn(),
}));

vi.mock('../api/configurationSolver', () => ({
  solveConfiguration: vi.fn(),
}));

const getPokemonDetailMock = vi.mocked(getPokemonDetail);
const listBattleItemsMock = vi.mocked(listBattleItems);
const listPokemonAbilitiesMock = vi.mocked(listPokemonAbilities);
const listStatPresetsMock = vi.mocked(listStatPresets);
const solveConfigurationMock = vi.mocked(solveConfiguration);

const SUBJECT: PokemonDetail = {
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

const RESPONSE: SolveConfigurationResponse = {
  ruleset_id: 'pokemon-champion',
  ruleset_name: 'Pokemon Champion',
  subject: SUBJECT,
  level: 50,
  reachable: false,
  candidates: [],
  rejected_goals: [],
  scope: [],
  warnings: [],
};

beforeEach(() => {
  getPokemonDetailMock.mockReset().mockImplementation(async (pokemonId) => (
    pokemonId === SUBJECT.pokemon_id ? SUBJECT : TARGET
  ));
  listPokemonAbilitiesMock.mockReset().mockImplementation(async (pokemonId) => (
    pokemonId === SUBJECT.pokemon_id
      ? [{
          ability_id: 101,
          identifier: 'technician',
          display_name: '技术高手',
          slot: 2,
          is_hidden: false,
          implemented: true,
        }]
      : [{
          ability_id: 56,
          identifier: 'cute-charm',
          display_name: '迷人之躯',
          slot: 1,
          is_hidden: false,
          implemented: false,
        }]
  ));
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
  listStatPresetsMock.mockReset().mockResolvedValue({ attacker: [], defender: [] });
  solveConfigurationMock.mockReset().mockResolvedValue(RESPONSE);
});

describe('useConfigurationSolver', () => {
  it('submits independent subject and target items and abilities', async () => {
    /**
     * 目标必须先通过新增流程完成 Pokémon 与特性加载，之后再配置招式、道具并提交。
     * 断言保护新增弹窗改造不能丢失双方独立的机制字段。
     */
    const solver = useConfigurationSolver();
    await solver.loadItems();
    await solver.selectSubject(SUBJECT);

    const goal = await solver.addGoalWithTarget('defense', TARGET);
    expect(goal).not.toBeNull();
    if (goal === null) throw new Error('goal should be created');
    goal.move = MOVE;
    solver.subjectItemIdentifier.value = 'life-orb';
    goal.targetItemIdentifier = 'eviolite';

    await solver.submit();

    expect(solveConfigurationMock).toHaveBeenCalledWith({
      ruleset_id: 'pokemon-champion',
      subject_pokemon_id: SUBJECT.pokemon_id,
      subject_ability_identifier: 'technician',
      subject_item_identifier: 'life-orb',
      level: 50,
      goals: [{
        goal_id: goal.id,
        kind: 'defense',
        target_pokemon_id: TARGET.pokemon_id,
        move_id: MOVE.move_id,
        required_turns: 1,
        target_ability_identifier: 'cute-charm',
        target_item_identifier: 'eviolite',
        target_stat_preset: 'max_atk_neutral',
        damage_roll_policy: 'max',
      }],
      allowed_stat_presets: [
        'max_hp_def_plus',
        'max_hp_spdef_plus',
        'max_spatk_plus',
        'max_atk_plus',
      ],
      max_candidates: 3,
    });
  });

  it('keeps the selected list empty until a target is fully loaded', async () => {
    /**
     * 点击添加只应打开选择流程，不能预先插入空白目标。新增 Promise 完成前列表保持为空，
     * 目标详情和默认特性加载完成后才出现一条攻目标，避免待新增对象混入已选择列表。
     */
    const solver = useConfigurationSolver();

    const addPromise = solver.addGoalWithTarget('attack', TARGET);
    expect(solver.goals.value).toEqual([]);

    const goal = await addPromise;

    expect(goal).not.toBeNull();
    expect(solver.goals.value).toHaveLength(1);
    expect(solver.goals.value[0]).toMatchObject({
      kind: 'attack',
      target: TARGET,
      targetPreset: 'max_hp',
      targetAbilityIdentifier: 'cute-charm',
      rollPolicy: 'min',
    });
  });

  it('does not retain a blank goal when target loading fails', async () => {
    /**
     * 新增目标资料请求失败时必须返回 null，并继续保持已选列表为空；否则失败请求会生成
     * 无法提交、也容易被误认为已选对象的残留卡片。
     */
    getPokemonDetailMock.mockRejectedValueOnce(new Error('target unavailable'));
    const solver = useConfigurationSolver();

    const goal = await solver.addGoalWithTarget('defense', TARGET);

    expect(goal).toBeNull();
    expect(solver.goals.value).toEqual([]);
    expect(solver.error.value).toBe('target unavailable');
  });
});
