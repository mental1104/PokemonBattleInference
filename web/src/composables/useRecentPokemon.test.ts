import { afterEach, describe, expect, it, vi } from 'vitest';
import type { PokemonSearchItem } from '../api/calculator';
import {
  RECENT_POKEMON_LIMIT,
  rememberRecentPokemon,
  useRecentPokemon,
} from './useRecentPokemon';

/**
 * 构造最近选择测试使用的 Pokémon DTO。
 *
 * @param pokemonId Pokémon ID，也是 LRU 去重键。
 * @param displayName 页面展示名称；未提供时根据 ID 生成稳定文本。
 * @returns 满足 `PokemonSearchItem` 合同的最小测试对象。
 */
function pokemon(pokemonId: number, displayName: string = `Pokémon ${pokemonId}`): PokemonSearchItem {
  return {
    pokemon_id: pokemonId,
    identifier: `pokemon-${pokemonId}`,
    display_name: displayName,
    form_identifier: null,
    types: ['normal'],
    type_names: ['一般'],
    sprite_url: `/sprites/${pokemonId}.png`,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useRecentPokemon', () => {
  it('deduplicates by pokemon id and moves the latest selection to the front', () => {
    /**
     * 用户可能在攻击方和防守方之间反复选择同一只 Pokémon。该测试先记录妙蛙种子，再记录皮卡丘，
     * 最后用更新后的妙蛙种子 DTO 再次选择同一 ID；断言列表不产生重复项，并把最新选择移动到首位，
     * 同时保留最新 DTO 内容。该场景保护 LRU 的“访问即更新”语义，而不是只在首次出现时插入。
     */
    let items: readonly PokemonSearchItem[] = [];
    items = rememberRecentPokemon(items, pokemon(1, '妙蛙种子'));
    items = rememberRecentPokemon(items, pokemon(25, '皮卡丘'));
    items = rememberRecentPokemon(items, pokemon(1, '妙蛙种子（最新）'));

    expect(items.map((item) => item.pokemon_id)).toEqual([1, 25]);
    expect(items[0].display_name).toBe('妙蛙种子（最新）');
  });

  it('keeps at most eight pokemon and evicts the least recently used item', () => {
    /**
     * 页面会话只允许保留八个最近选择。测试按 ID 1 到 9 连续记录九只不同 Pokémon，断言最终列表长度
     * 等于固定上限，顺序为最近选择优先，并且最早加入且之后未再次使用的 ID 1 被淘汰。该断言同时
     * 防止实现误删最新项、按 ID 排序或无限增长，从而固定真正的 LRU 淘汰边界。
     */
    let items: readonly PokemonSearchItem[] = [];
    for (let pokemonId = 1; pokemonId <= RECENT_POKEMON_LIMIT + 1; pokemonId += 1) {
      items = rememberRecentPokemon(items, pokemon(pokemonId));
    }

    expect(items).toHaveLength(RECENT_POKEMON_LIMIT);
    expect(items.map((item) => item.pokemon_id)).toEqual([9, 8, 7, 6, 5, 4, 3, 2]);
  });

  it('stores selections only in the current composable instance', () => {
    /**
     * 当前项目没有租户和账号机制，最近选择必须只存在于当前 SPA 页面内存。测试创建两个独立 store，
     * 只向第一个实例记录妙蛙种子，并监视 localStorage 与 sessionStorage 的写入方法；断言第二个实例
     * 仍为空且没有任何 Web Storage 写入。该场景保护刷新即清空和实例隔离，不允许未来顺手加入持久化。
     */
    const localStorageSetItem = vi.spyOn(Storage.prototype, 'setItem');
    const firstStore = useRecentPokemon();
    const secondStore = useRecentPokemon();

    firstStore.remember(pokemon(1, '妙蛙种子'));

    expect(firstStore.items.value.map((item) => item.pokemon_id)).toEqual([1]);
    expect(secondStore.items.value).toEqual([]);
    expect(localStorageSetItem).not.toHaveBeenCalled();
  });
});
