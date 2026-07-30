import type { PokemonDetail } from './calculator';
import {
  battleConfigurationSpaceAdapter as httpBattleConfigurationSpaceAdapter,
} from './configurationSpaceHttp';
import { calculateConfigurationBudget } from '../domain/configurationBudget';
import type {
  BattleConfigurationSpaceAdapter,
  CandidateMoveOption,
  CandidateMovePoolRequest,
  CandidateMovePoolResponse,
  CreateBattleConfigurationJobRequest,
  CreateBattleConfigurationJobResponse,
} from '../types/battleConfigurationSpace';

export const SUPPORTED_VERSION_GROUPS = [25, 20, 15] as const;

export const DRAGONITE_EXAMPLE: PokemonDetail = {
  pokemon_id: 149,
  identifier: 'dragonite',
  display_name: '快龙',
  form_identifier: null,
  types: ['dragon', 'flying'],
  type_names: ['龙', '飞行'],
  sprite_url: '/api/v1/assets/pokemon/149/sprite?ruleset_id=pokemon-champion&slot=front_default',
  base_stats: {
    hp: 91,
    attack: 134,
    defense: 95,
    special_attack: 100,
    special_defense: 100,
    speed: 80,
  },
};

export const WEAVILE_EXAMPLE: PokemonDetail = {
  pokemon_id: 461,
  identifier: 'weavile',
  display_name: '玛纽拉',
  form_identifier: null,
  types: ['dark', 'ice'],
  type_names: ['恶', '冰'],
  sprite_url: '/api/v1/assets/pokemon/461/sprite?ruleset_id=pokemon-champion&slot=front_default',
  base_stats: {
    hp: 70,
    attack: 120,
    defense: 65,
    special_attack: 45,
    special_defense: 85,
    speed: 125,
  },
};

interface MoveFixtureSeed {
  moveId: number;
  identifier: string;
  displayName: string;
  typeIdentifier: string;
  typeName: string;
  damageClass: CandidateMoveOption['damage_class'];
  power: number | null;
}

const DRAGONITE_MOVE_SEEDS: readonly MoveFixtureSeed[] = [
  { moveId: 280, identifier: 'brick-break', displayName: '劈瓦', typeIdentifier: 'fighting', typeName: '格斗', damageClass: 'physical', power: 75 },
  { moveId: 245, identifier: 'extreme-speed', displayName: '神速', typeIdentifier: 'normal', typeName: '一般', damageClass: 'physical', power: 80 },
  { moveId: 337, identifier: 'dragon-claw', displayName: '龙爪', typeIdentifier: 'dragon', typeName: '龙', damageClass: 'physical', power: 80 },
  { moveId: 89, identifier: 'earthquake', displayName: '地震', typeIdentifier: 'ground', typeName: '地面', damageClass: 'physical', power: 100 },
  { moveId: 7, identifier: 'fire-punch', displayName: '火焰拳', typeIdentifier: 'fire', typeName: '火', damageClass: 'physical', power: 75 },
  { moveId: 9, identifier: 'thunder-punch', displayName: '雷电拳', typeIdentifier: 'electric', typeName: '电', damageClass: 'physical', power: 75 },
  { moveId: 8, identifier: 'ice-punch', displayName: '冰冻拳', typeIdentifier: 'ice', typeName: '冰', damageClass: 'physical', power: 75 },
  { moveId: 200, identifier: 'outrage', displayName: '逆鳞', typeIdentifier: 'dragon', typeName: '龙', damageClass: 'physical', power: 120 },
  { moveId: 349, identifier: 'dragon-dance', displayName: '龙之舞', typeIdentifier: 'dragon', typeName: '龙', damageClass: 'status', power: null },
  { moveId: 406, identifier: 'dragon-pulse', displayName: '龙之波动', typeIdentifier: 'dragon', typeName: '龙', damageClass: 'special', power: 85 },
];

const WEAVILE_MOVE_SEEDS: readonly MoveFixtureSeed[] = [
  { moveId: 8, identifier: 'ice-punch', displayName: '冰冻拳', typeIdentifier: 'ice', typeName: '冰', damageClass: 'physical', power: 75 },
  { moveId: 252, identifier: 'fake-out', displayName: '击掌奇袭', typeIdentifier: 'normal', typeName: '一般', damageClass: 'physical', power: 40 },
  { moveId: 400, identifier: 'night-slash', displayName: '暗袭要害', typeIdentifier: 'dark', typeName: '恶', damageClass: 'physical', power: 70 },
  { moveId: 420, identifier: 'ice-shard', displayName: '冰砾', typeIdentifier: 'ice', typeName: '冰', damageClass: 'physical', power: 40 },
  { moveId: 269, identifier: 'taunt', displayName: '挑衅', typeIdentifier: 'dark', typeName: '恶', damageClass: 'status', power: null },
  { moveId: 280, identifier: 'brick-break', displayName: '劈瓦', typeIdentifier: 'fighting', typeName: '格斗', damageClass: 'physical', power: 75 },
  { moveId: 404, identifier: 'x-scissor', displayName: '十字剪', typeIdentifier: 'bug', typeName: '虫', damageClass: 'physical', power: 80 },
  { moveId: 332, identifier: 'aerial-ace', displayName: '燕返', typeIdentifier: 'flying', typeName: '飞行', damageClass: 'physical', power: 60 },
  { moveId: 421, identifier: 'shadow-claw', displayName: '暗影爪', typeIdentifier: 'ghost', typeName: '幽灵', damageClass: 'physical', power: 70 },
  { moveId: 14, identifier: 'swords-dance', displayName: '剑舞', typeIdentifier: 'normal', typeName: '一般', damageClass: 'status', power: null },
];

const GENERIC_MOVE_NAMES = [
  ['quick-strike', '迅捷打击', 'normal', '一般'],
  ['power-blow', '强力猛击', 'fighting', '格斗'],
  ['aqua-burst', '水流爆发', 'water', '水'],
  ['flame-charge', '火焰突进', 'fire', '火'],
  ['leaf-blade', '叶刃', 'grass', '草'],
  ['thunder-wave', '电磁波', 'electric', '电'],
  ['rock-slide', '岩崩', 'rock', '岩石'],
  ['shadow-hit', '暗影突袭', 'ghost', '幽灵'],
  ['steel-wing', '钢翼', 'steel', '钢'],
  ['psychic-wave', '精神波', 'psychic', '超能力'],
  ['bug-bite', '虫咬', 'bug', '虫'],
  ['poison-jab', '毒击', 'poison', '毒'],
  ['air-slash', '空气斩', 'flying', '飞行'],
  ['dragon-rush', '龙之俯冲', 'dragon', '龙'],
  ['dark-pulse', '恶之波动', 'dark', '恶'],
  ['ice-beam', '冰冻光束', 'ice', '冰'],
  ['moon-blast', '月亮之力', 'fairy', '妖精'],
  ['mud-shot', '泥巴射击', 'ground', '地面'],
  ['focus-energy', '聚气', 'normal', '一般'],
  ['protect', '守住', 'normal', '一般'],
] as const;

let mockJobSequence = 0;

function supportedMove(seed: MoveFixtureSeed): CandidateMoveOption {
  return {
    move_id: seed.moveId,
    identifier: seed.identifier,
    display_name: seed.displayName,
    type_identifier: seed.typeIdentifier,
    type_name: seed.typeName,
    damage_class: seed.damageClass,
    power: seed.power,
    admission: {
      status: 'supported',
      selectable: true,
      reason: '当前计算版本已完整支持该招式。',
      disabled_reason: null,
      missing_mechanism_identifiers: [],
    },
  };
}

function buildSupportedMoves(
  pokemonId: number,
  existingSeeds: readonly MoveFixtureSeed[],
): CandidateMoveOption[] {
  const moves = existingSeeds.map(supportedMove);
  const usedMoveIds = new Set(moves.map((move) => move.move_id));
  const generatedBase = pokemonId * 10_000;
  for (let index = 0; moves.length < 20; index += 1) {
    const [identifier, displayName, typeIdentifier, typeName] =
      GENERIC_MOVE_NAMES[index % GENERIC_MOVE_NAMES.length];
    const moveId = generatedBase + index + 1;
    if (usedMoveIds.has(moveId)) continue;
    usedMoveIds.add(moveId);
    moves.push({
      move_id: moveId,
      identifier: `${identifier}-${index + 1}`,
      display_name: `${displayName}${index + 1}`,
      type_identifier: typeIdentifier,
      type_name: typeName,
      damage_class: index % 7 === 6 ? 'status' : index % 2 === 0 ? 'physical' : 'special',
      power: index % 7 === 6 ? null : 60 + (index % 5) * 10,
      admission: {
        status: 'supported',
        selectable: true,
        reason: '当前计算版本已完整支持该招式。',
        disabled_reason: null,
        missing_mechanism_identifiers: [],
      },
    });
  }
  return moves;
}

function buildDisabledMoves(
  pokemonId: number,
  versionGroupId: number,
): CandidateMoveOption[] {
  const base = pokemonId * 10_000 + 900;
  return [
    {
      move_id: base + 1,
      identifier: 'variable-power-fixture',
      display_name: '变化威力示例',
      type_identifier: 'normal',
      type_name: '一般',
      damage_class: 'physical',
      power: null,
      admission: {
        status: 'partial',
        selectable: false,
        reason: `version_group_id=${versionGroupId} 下尚未实现动态威力上下文。`,
        disabled_reason: `version_group_id=${versionGroupId} 下尚未实现动态威力上下文。`,
        missing_mechanism_identifiers: ['dynamic-power-context'],
      },
    },
    {
      move_id: base + 2,
      identifier: 'future-generation-fixture',
      display_name: '未来世代示例',
      type_identifier: 'fairy',
      type_name: '妖精',
      damage_class: 'special',
      power: 95,
      admission: {
        status: 'unsupported',
        selectable: false,
        reason: `该 fixture 不属于 version_group_id=${versionGroupId} 的严格准入范围。`,
        disabled_reason: `该 fixture 不属于 version_group_id=${versionGroupId} 的严格准入范围。`,
        missing_mechanism_identifiers: ['version-group-legality'],
      },
    },
  ];
}

function fixtureSeedsForPokemon(pokemonId: number): readonly MoveFixtureSeed[] {
  if (pokemonId === DRAGONITE_EXAMPLE.pokemon_id) return DRAGONITE_MOVE_SEEDS;
  if (pokemonId === WEAVILE_EXAMPLE.pokemon_id) return WEAVILE_MOVE_SEEDS;
  return [];
}

async function listFixtureCandidateMoves(
  request: CandidateMovePoolRequest,
): Promise<CandidateMovePoolResponse> {
  return {
    pokemon_id: request.pokemon_id,
    ruleset_id: request.ruleset_id,
    version_group_id: request.version_group_id,
    calculation_revision: `fixture.configuration-space.v1.vg-${request.version_group_id}`,
    moves: [
      ...buildSupportedMoves(
        request.pokemon_id,
        fixtureSeedsForPokemon(request.pokemon_id),
      ),
      ...buildDisabledMoves(request.pokemon_id, request.version_group_id),
    ],
  };
}

async function createFixtureJob(
  request: CreateBattleConfigurationJobRequest,
): Promise<CreateBattleConfigurationJobResponse> {
  mockJobSequence += 1;
  const budget = calculateConfigurationBudget(
    request.attacker.candidate_move_ids.length,
    request.defender.candidate_move_ids.length,
  );
  return {
    job_id: `fixture-battle-job-${String(mockJobSequence).padStart(4, '0')}`,
    status: 'pending',
    submitted_configuration_pairs: budget.configuration_pair_count,
    created_at: new Date().toISOString(),
  };
}

/** 仅供 Vitest 和显式演示入口使用的内存 fixture。 */
export const fixtureBattleConfigurationSpaceAdapter: BattleConfigurationSpaceAdapter = {
  listCandidateMoves: listFixtureCandidateMoves,
  createJob: createFixtureJob,
};

/** 产品构建默认走真实后端；测试环境保留可重复 fixture。 */
export const battleConfigurationSpaceAdapter: BattleConfigurationSpaceAdapter =
  import.meta.env.MODE === 'test'
    ? fixtureBattleConfigurationSpaceAdapter
    : httpBattleConfigurationSpaceAdapter;
