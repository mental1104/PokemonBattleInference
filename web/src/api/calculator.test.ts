import { afterEach, describe, expect, it, vi } from 'vitest';
import { calculateDamage } from './calculator';

describe('calculator api', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('posts only selected ids, ruleset, level and presets to damage endpoint', async () => {
    /**
     * 该测试固定前端请求边界：请求体只能包含用户选择和模板 key，不能把种族值、
     * 招式威力、属性或伤害分类作为可信输入交给服务端。
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
      attacker: { pokemon_id: 212, level: 50, stat_preset: 'max_atk_neutral' },
      defender: { pokemon_id: 700, level: 50, stat_preset: 'max_hp' },
      move_id: 418,
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/calculator/damage');
    expect(JSON.parse(init?.body as string)).toEqual({
      ruleset_id: 'pokemon-champion',
      attacker: { pokemon_id: 212, level: 50, stat_preset: 'max_atk_neutral' },
      defender: { pokemon_id: 700, level: 50, stat_preset: 'max_hp' },
      move_id: 418,
    });
    expect(result.damage.min).toBe(99);
    expect(result.move.display_name).toBe('子弹拳');
  });
});
