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
    const solver = useConfigurationSolver();
    await solver.loadItems();
    await solver.selectSubject(SUBJECT);

    const goal = solver.goals.value[0];
    await solver.selectGoalTarget(goal, TARGET);
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

  it('adds attack and defense targets into stable independent kinds', () => {
    const solver = useConfigurationSolver();

    solver.addGoal('attack');
    solver.addGoal('defense');

    expect(solver.goals.value.map((goal) => goal.kind)).toEqual([
      'defense',
      'attack',
      'defense',
    ]);
    expect(solver.goals.value[1].targetPreset).toBe('max_hp');
    expect(solver.goals.value[1].rollPolicy).toBe('min');
  });
});
