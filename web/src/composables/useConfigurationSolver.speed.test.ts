import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getPokemonDetail,
  listBattleItems,
  listPokemonAbilities,
  listStatPresets,
  type PokemonDetail,
} from '../api/calculator';
import {
  searchConfigurationSpreads,
  solveConfiguration,
} from '../api/configurationSolver';
import {
  searchConfigurationSpreadsWithSpeed,
  solveConfigurationWithSpeed,
  type SpeedAwareSolveConfigurationResponse,
} from '../api/configurationSpeedGoals';
import { createConfigurationSolver } from './useConfigurationSolver';

vi.mock('../api/calculator', () => ({
  getPokemonDetail: vi.fn(),
  listBattleItems: vi.fn(),
  listPokemonAbilities: vi.fn(),
  listStatPresets: vi.fn(),
}));

vi.mock('../api/configurationSolver', () => ({
  searchConfigurationSpreads: vi.fn(),
  solveConfiguration: vi.fn(),
}));

vi.mock('../api/configurationSpeedGoals', () => ({
  searchConfigurationSpreadsWithSpeed: vi.fn(),
  solveConfigurationWithSpeed: vi.fn(),
}));

const getPokemonDetailMock = vi.mocked(getPokemonDetail);
const listBattleItemsMock = vi.mocked(listBattleItems);
const listPokemonAbilitiesMock = vi.mocked(listPokemonAbilities);
const listStatPresetsMock = vi.mocked(listStatPresets);
const solveConfigurationMock = vi.mocked(solveConfiguration);
const searchConfigurationSpreadsMock = vi.mocked(searchConfigurationSpreads);
const solveConfigurationWithSpeedMock = vi.mocked(solveConfigurationWithSpeed);
const searchConfigurationSpreadsWithSpeedMock = vi.mocked(searchConfigurationSpreadsWithSpeed);

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

const SPEED_TARGET: PokemonDetail = {
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

const SPEED_RESPONSE: SpeedAwareSolveConfigurationResponse = {
  ruleset_id: 'pokemon-champion',
  ruleset_name: 'Pokemon Champion',
  subject: SUBJECT,
  level: 50,
  reachable: true,
  candidates: [],
  rejected_goals: [],
  rejected_speed_goals: [],
  scope: ['严格速度比较'],
  warnings: [],
};

beforeEach(() => {
  getPokemonDetailMock.mockReset().mockImplementation(async (pokemonId) => (
    pokemonId === SUBJECT.pokemon_id ? SUBJECT : SPEED_TARGET
  ));
  listPokemonAbilitiesMock.mockReset().mockResolvedValue([{
    ability_id: 68,
    identifier: 'swarm',
    display_name: '虫之预感',
    slot: 1,
    is_hidden: false,
    implemented: false,
  }]);
  listBattleItemsMock.mockReset().mockResolvedValue([]);
  listStatPresetsMock.mockReset().mockResolvedValue({ attacker: [], defender: [] });
  solveConfigurationMock.mockReset();
  searchConfigurationSpreadsMock.mockReset();
  solveConfigurationWithSpeedMock.mockReset().mockResolvedValue(SPEED_RESPONSE);
  searchConfigurationSpreadsWithSpeedMock.mockReset().mockResolvedValue(SPEED_RESPONSE);
});

describe('useConfigurationSolver speed goals', () => {
  it('submits a speed-only target through the speed-aware preset client', async () => {
    /**
     * 页面允许用户只添加速度目标而不创建任何攻目标或防目标。选择巨钳螳螂作为待配置 Pokémon、
     * 仙子伊布作为速度参照并保存极限速度配置后，canSubmit 必须变为 true；提交请求应携带空的
     * goals 和一条 speed_goals，目标 ID、pokemon_id 与配置标识均保持不变。该测试还要求组合式
     * API 选择扩展客户端而不是旧纯伤害客户端，防止新增第三列只有界面状态却没有真正进入后端求解，
     * 同时保护原有无速度目标流程仍可继续复用旧 API 和既有测试 mock。
     */
    const solver = createConfigurationSolver();
    await solver.selectSubject(SUBJECT);

    const draft = solver.createSpeedGoalDraft();
    await solver.selectSpeedGoalTarget(draft, SPEED_TARGET);
    draft.targetPreset = 'max_speed_plus';
    expect(solver.saveSpeedGoalDraft(draft)).toBe(true);
    expect(solver.canSubmit.value).toBe(true);

    await solver.submit();

    expect(solveConfigurationWithSpeedMock).toHaveBeenCalledWith({
      ruleset_id: 'pokemon-champion',
      subject_pokemon_id: SUBJECT.pokemon_id,
      subject_ability_identifier: 'swarm',
      subject_item_identifier: null,
      level: 50,
      goals: [],
      speed_goals: [{
        goal_id: draft.id,
        target_pokemon_id: SPEED_TARGET.pokemon_id,
        target_stat_preset: 'max_speed_plus',
      }],
      allowed_stat_presets: [
        'max_hp_def_plus',
        'max_hp_spdef_plus',
        'max_spatk_plus',
        'max_atk_plus',
      ],
      max_candidates: 3,
    });
    expect(solveConfigurationMock).not.toHaveBeenCalled();
    expect(searchConfigurationSpreadsMock).not.toHaveBeenCalled();
  });
});
