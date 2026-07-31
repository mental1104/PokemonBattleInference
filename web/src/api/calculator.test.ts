import { afterEach, describe, expect, it, vi } from 'vitest';
import { calculateDamage, listPokemonAbilities } from './calculator';

describe('calculator api', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('posts selected ids, ruleset, abilities, presets and item identifiers to damage endpoint', async () => {
    /**
     * 该测试固定前端伤害计算请求边界：请求体只能包含双方 Pokémon ID、等级、配置模板、必选特性、
     * 可选持有道具和招式 ID，不能把种族值、招式威力、属性或伤害分类作为可信输入交给服务端。
     * 攻击方技术高手与防守方迷人之躯必须原样进入 JSON，证明新增特性字段不会覆盖既有生命宝珠选择，
     * 也不会让前端自行传递 implemented 或效果倍率等可伪造派生信息。
     */
    const fetchMock = vi.fn<[RequestInfo | URL, RequestInit?], Promise<Response>>(async () => {
      return new Response(
        JSON.stringify({
          ruleset_id: 'pokemon-champion',
          ruleset_name: 'Pokemon Champion',
          attacker: {
            pokemon_id: 212,
            identifier: 'scizor',
            display_name: '巨钳螳螂',
            sprite_url: '/api/v1/assets/pokemon/212/sprite?ruleset_id=pokemon-champion&slot=front_default',
            level: 50,
            preset_label: '满攻',
            preset_assumption: '50 级 · 252 Atk · 中性性格',
            stats: {},
            effective_attack: 182,
            effective_hp: null,
            effective_defense: null,
          },
          defender: {
            pokemon_id: 700,
            identifier: 'sylveon',
            display_name: '仙子伊布',
            sprite_url: '/api/v1/assets/pokemon/700/sprite?ruleset_id=pokemon-champion&slot=front_default',
            level: 50,
            preset_label: '满 HP',
            preset_assumption: '50 级 · 252 HP · 防御/特防无投入',
            stats: {},
            effective_attack: null,
            effective_hp: 202,
            effective_defense: 85,
          },
          move: {
            move_id: 418,
            identifier: 'bullet-punch',
            display_name: '子弹拳',
            type: 'steel',
            type_name: '钢',
            category: 'physical',
            power: 40,
          },
          damage: {
            min: 99,
            max: 117,
            min_percent: 49,
            max_percent: 57.9,
            expected: 108,
            expected_percent: 53.4,
            rolls: [],
          },
          ko: {
            ohko_probability: 0,
            two_hit_ko_probability: 0.65,
            guaranteed_ohko: false,
            guaranteed_2hko: false,
          },
          modifiers: [],
          scope: { mode: 'basic', included: [], excluded: [] },
          warnings: [],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await calculateDamage({
      ruleset_id: 'pokemon-champion',
      attacker: {
        pokemon_id: 212,
        level: 50,
        stat_preset: 'max_atk_neutral',
        ability_identifier: 'technician',
        item_identifier: 'life-orb',
      },
      defender: {
        pokemon_id: 700,
        level: 50,
        stat_preset: 'max_hp',
        ability_identifier: 'cute-charm',
      },
      move_id: 418,
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/calculator/damage');
    expect(JSON.parse(init?.body as string)).toEqual({
      ruleset_id: 'pokemon-champion',
      attacker: {
        pokemon_id: 212,
        level: 50,
        stat_preset: 'max_atk_neutral',
        ability_identifier: 'technician',
        item_identifier: 'life-orb',
      },
      defender: {
        pokemon_id: 700,
        level: 50,
        stat_preset: 'max_hp',
        ability_identifier: 'cute-charm',
      },
      move_id: 418,
    });
    expect(result.damage.min).toBe(99);
    expect(result.move.display_name).toBe('子弹拳');
  });

  it('loads every legal pokemon ability with implementation metadata', async () => {
    /**
     * 特性枚举请求必须以当前 Pokémon ID 和 ruleset_id 为唯一输入，从服务端读取完整合法候选及实现状态。
     * 测试返回已实现的技术高手与未实现的虫之预感，断言前端 API 不过滤后者，也不把它误当成不可选择项；
     * 同时验证请求路径只携带规则集上下文，不接受客户端上传槽位、隐藏标记或 implemented 等服务端派生字段，
     * 从而为选择组件的禁止标识和“按无特性处理”语义提供可信数据来源。
     */
    const fetchMock = vi.fn<[RequestInfo | URL, RequestInit?], Promise<Response>>(async () => {
      return new Response(
        JSON.stringify([
          {
            ability_id: 68,
            identifier: 'swarm',
            display_name: '虫之预感',
            slot: 1,
            is_hidden: false,
            implemented: false,
          },
          {
            ability_id: 101,
            identifier: 'technician',
            display_name: '技术高手',
            slot: 2,
            is_hidden: false,
            implemented: true,
          },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    });
    vi.stubGlobal('fetch', fetchMock);

    const abilities = await listPokemonAbilities(212, 'pokemon-champion');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/calculator/pokemon/212/abilities?ruleset_id=pokemon-champion',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
    );
    expect(abilities.map((ability) => [ability.identifier, ability.implemented])).toEqual([
      ['swarm', false],
      ['technician', true],
    ]);
  });
});
