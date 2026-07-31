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
  searchConfigurationSpreads,
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
  searchConfigurationSpreads: vi.fn(),
}));

const getPokemonDetailMock = vi.mocked(getPokemonDetail);
const listBattleItemsMock = vi.mocked(listBattleItems);
const listPokemonAbilitiesMock = vi.mocked(listPokemonAbilities);
const listStatPresetsMock = vi.mocked(listStatPresets);
const solveConfigurationMock = vi.mocked(solveConfiguration);
const searchConfigurationSpreadsMock = vi.mocked(searchConfigurationSpreads);

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
  searchConfigurationSpreadsMock.mockReset().mockResolvedValue(RESPONSE);
});

describe('useConfigurationSolver', () => {
  it('saves a complete dialog draft and submits independent mechanisms', async () => {
    /**
     * 新增目标先在独立草稿中完成 Pokémon、招式、配置、道具与特性选择，保存后才进入列表。
     * 断言同时保护求解请求仍携带待配置 Pokémon 与目标双方的独立机制字段。
     */
    const solver = useConfigurationSolver();
    await solver.loadItems();
    await solver.selectSubject(SUBJECT);

    const draft = solver.createGoalDraft('defense');
    await solver.selectGoalTarget(draft, TARGET);
    draft.move = MOVE;
    draft.targetItemIdentifier = 'eviolite';
    solver.subjectItemIdentifier.value = 'life-orb';

    expect(solver.goals.value).toEqual([]);
    expect(solver.saveGoalDraft(draft)).toBe(true);
    expect(solver.goals.value).toHaveLength(1);

    await solver.submit();

    expect(solveConfigurationMock).toHaveBeenCalledWith({
      ruleset_id: 'pokemon-champion',
      subject_pokemon_id: SUBJECT.pokemon_id,
      subject_ability_identifier: 'technician',
      subject_item_identifier: 'life-orb',
      level: 50,
      goals: [{
        goal_id: draft.id,
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
    expect(searchConfigurationSpreadsMock).not.toHaveBeenCalled();
  });

  it('keeps target details outside the selected list until the full draft is saved', async () => {
    /**
     * 仅加载 Pokémon 和默认特性仍属于弹窗内部状态；缺少招式时保存失败且列表为空。
     * 完成招式后再次保存，列表才得到一份与草稿隔离的目标快照。
     */
    const solver = useConfigurationSolver();
    const draft = solver.createGoalDraft('attack');

    await solver.selectGoalTarget(draft, TARGET);

    expect(solver.goals.value).toEqual([]);
    expect(solver.saveGoalDraft(draft)).toBe(false);
    expect(solver.goals.value).toEqual([]);

    draft.move = MOVE;
    expect(solver.saveGoalDraft(draft)).toBe(true);
    expect(solver.goals.value[0]).not.toBe(draft);
    expect(solver.goals.value[0]).toMatchObject({
      kind: 'attack',
      target: TARGET,
      move: MOVE,
      targetPreset: 'max_hp',
      targetAbilityIdentifier: 'cute-charm',
      rollPolicy: 'min',
    });
  });

  it('edits a cloned goal without changing the compact list before save', async () => {
    /**
     * 编辑弹窗必须持有已选目标的副本。用户修改次数和道具但尚未保存时，列表仍显示旧值；
     * 保存后再按相同 id 原子替换，避免取消编辑留下半成品状态。
     */
    const solver = useConfigurationSolver();
    const draft = solver.createGoalDraft('defense');
    await solver.selectGoalTarget(draft, TARGET);
    draft.move = MOVE;
    solver.saveGoalDraft(draft);

    const editing = solver.cloneGoal(solver.goals.value[0]);
    editing.repetitions = 3;
    editing.targetItemIdentifier = 'eviolite';

    expect(solver.goals.value[0].repetitions).toBe(1);
    expect(solver.goals.value[0].targetItemIdentifier).toBe('none');

    expect(solver.saveGoalDraft(editing)).toBe(true);
    expect(solver.goals.value).toHaveLength(1);
    expect(solver.goals.value[0].repetitions).toBe(3);
    expect(solver.goals.value[0].targetItemIdentifier).toBe('eviolite');
  });

  it('keeps the selected list unchanged when target loading fails', async () => {
    /** 目标资料请求失败时只更新错误状态，不会把不完整草稿写入列表。 */
    getPokemonDetailMock.mockRejectedValueOnce(new Error('target unavailable'));
    const solver = useConfigurationSolver();
    const draft = solver.createGoalDraft('defense');

    const loaded = await solver.selectGoalTarget(draft, TARGET);

    expect(loaded).toBe(false);
    expect(solver.goals.value).toEqual([]);
    expect(solver.error.value).toBe('target unavailable');
  });

  it('submits spread search without requiring a selected subject preset', async () => {
    /**
     * 全局反推开关开启后，待配置 Pokémon 的性格、EV 与 IV 不再来自左侧模板，因此即使用户清空
     * selectedPresetKeys，只要 Pokémon、特性、道具和至少一个完整目标已经准备完成，提交按钮仍应
     * 可用。请求必须改发 search-spreads 接口、最多索取十条候选，并完全省略 allowed_stat_presets；
     * 同时不能误调用旧模板求解接口。该测试保护两个模式的输入边界不会在 composable 中再次混合。
     */
    const solver = useConfigurationSolver();
    await solver.selectSubject(SUBJECT);
    const draft = solver.createGoalDraft('attack');
    await solver.selectGoalTarget(draft, TARGET);
    draft.move = MOVE;
    expect(solver.saveGoalDraft(draft)).toBe(true);

    solver.selectedPresetKeys.value = [];
    solver.searchMode.value = 'spread';

    expect(solver.canSubmit.value).toBe(true);
    await solver.submit();

    expect(searchConfigurationSpreadsMock).toHaveBeenCalledWith({
      ruleset_id: 'pokemon-champion',
      subject_pokemon_id: SUBJECT.pokemon_id,
      subject_ability_identifier: 'technician',
      subject_item_identifier: null,
      level: 50,
      goals: [{
        goal_id: draft.id,
        kind: 'attack',
        target_pokemon_id: TARGET.pokemon_id,
        move_id: MOVE.move_id,
        required_turns: 1,
        target_ability_identifier: 'cute-charm',
        target_item_identifier: null,
        target_stat_preset: 'max_hp',
        damage_roll_policy: 'min',
      }],
      max_candidates: 10,
    });
    expect(solveConfigurationMock).not.toHaveBeenCalled();
  });
});
