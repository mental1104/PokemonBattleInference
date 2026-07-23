import { ref, type Ref } from 'vue';
import type { PokemonSearchItem } from '../api/calculator';

export const RECENT_POKEMON_LIMIT = 8;

/**
 * 当前伤害计算器页面共享的最近 Pokémon 状态。
 *
 * 状态仅由页面级 composable 实例持有，不读写浏览器存储，也不调用后端持久化接口。
 */
export interface RecentPokemonStore {
  /** 按最近使用优先排列的只读 Pokémon 快照，最多保留配置的数量。 */
  items: Readonly<Ref<readonly PokemonSearchItem[]>>;

  /**
   * 记录一次 Pokémon 选择；已存在的 Pokémon 会移动到首位，并刷新为最新 DTO。
   *
   * @param pokemon 用户刚刚选择的 Pokémon 搜索结果。
   */
  remember(pokemon: PokemonSearchItem): void;
}

/**
 * 将一次选择合并到最近 Pokémon 列表，并返回新的 LRU 快照。
 *
 * @param current 当前最近列表，索引越小表示越近使用。
 * @param pokemon 本次选择的 Pokémon；使用 `pokemon_id` 去重。
 * @param limit 最大保留数量；小于等于零时返回空列表。
 * @returns 新数组，首项是本次选择，其余项目保持原有最近使用顺序。
 */
export function rememberRecentPokemon(
  current: readonly PokemonSearchItem[],
  pokemon: PokemonSearchItem,
  limit: number = RECENT_POKEMON_LIMIT,
): readonly PokemonSearchItem[] {
  if (limit <= 0) {
    return [];
  }

  const previousWithoutSelected = current.filter((item) => item.pokemon_id !== pokemon.pokemon_id);
  return [pokemon, ...previousWithoutSelected].slice(0, limit);
}

/**
 * 创建一个页面会话级最近 Pokémon store。
 *
 * @param limit 最大保存数量，默认保存 8 个最近选择。
 * @returns 当前页面实例独占的响应式列表和记录函数；页面卸载后状态自然释放。
 */
export function useRecentPokemon(limit: number = RECENT_POKEMON_LIMIT): RecentPokemonStore {
  const items = ref<readonly PokemonSearchItem[]>([]);

  /**
   * 更新当前页面内存中的 LRU 列表，不产生网络、Cookie 或 Web Storage 副作用。
   *
   * @param pokemon 用户刚刚选择的 Pokémon 搜索结果。
   */
  function remember(pokemon: PokemonSearchItem): void {
    items.value = rememberRecentPokemon(items.value, pokemon, limit);
  }

  return { items, remember };
}
