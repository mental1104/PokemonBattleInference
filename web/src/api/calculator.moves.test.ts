import { afterEach, describe, expect, it, vi } from 'vitest';
import { listPokemonMoves } from './calculator';

describe('calculator move api', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('encodes category, repeated type filters and pagination explicitly', async () => {
    /**
     * 前端不能一次拉取全部招式后自行过滤。测试调用招式分页 API，传入特殊类别、电和水两个属性、
     * limit 五十及 offset 五十，断言 URL 保留两个独立 type 参数，并完整携带 ruleset、搜索词、类别和
     * 分页字段。服务端响应则必须按 envelope 解析出 items、total、has_more 和 available_types，保护
     * MoveSelector 不再依赖裸数组长度猜测是否还有结果，也不会从当前页反推全部属性按钮。
     */
    const fetchMock = vi.fn<[RequestInfo | URL, RequestInit?], Promise<Response>>(async () => {
      return new Response(
        JSON.stringify({
          items: [],
          total: 61,
          limit: 50,
          offset: 50,
          has_more: true,
          available_types: [
            { identifier: 'electric', display_name: '电' },
            { identifier: 'water', display_name: '水' },
          ],
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      );
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await listPokemonMoves(25, 'pokemon-champion', {
      query: 'bolt',
      category: 'special',
      typeIdentifiers: ['electric', 'water'],
      limit: 50,
      offset: 50,
    });

    const requestUrl = String(fetchMock.mock.calls[0][0]);
    const parsed = new URL(requestUrl, 'http://localhost');
    expect(parsed.pathname).toBe('/api/v1/calculator/pokemon/25/moves');
    expect(parsed.searchParams.get('ruleset_id')).toBe('pokemon-champion');
    expect(parsed.searchParams.get('query')).toBe('bolt');
    expect(parsed.searchParams.get('category')).toBe('special');
    expect(parsed.searchParams.getAll('type')).toEqual(['electric', 'water']);
    expect(parsed.searchParams.get('limit')).toBe('50');
    expect(parsed.searchParams.get('offset')).toBe('50');
    expect(result.total).toBe(61);
    expect(result.available_types).toHaveLength(2);
  });
});
