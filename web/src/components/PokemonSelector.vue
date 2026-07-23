<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { searchPokemon, type PokemonSearchItem } from '../api/calculator';

const props = defineProps<{
  title: string;
  rulesetId: string;
  selected: PokemonSearchItem | null;
  recentPokemon: readonly PokemonSearchItem[];
}>();

const emit = defineEmits<{
  select: [pokemon: PokemonSearchItem];
}>();

const query = ref('');
const results = ref<PokemonSearchItem[]>([]);
const browsingAll = ref(false);
const loading = ref(false);
const error = ref<string | null>(null);
let timer: number | undefined;

const normalizedQuery = computed(() => query.value.trim());
const hasRecentPokemon = computed(() => props.recentPokemon.length > 0);
const showingRecentPokemon = computed(
  () => hasRecentPokemon.value && normalizedQuery.value === '' && !browsingAll.value,
);
const visiblePokemon = computed<readonly PokemonSearchItem[]>(() =>
  showingRecentPokemon.value ? props.recentPokemon : results.value,
);
const listMode = computed<'recent' | 'search' | 'all'>(() => {
  if (showingRecentPokemon.value) return 'recent';
  if (normalizedQuery.value !== '') return 'search';
  return 'all';
});

/**
 * 按指定搜索词读取当前规则集的 Pokémon，并把网络错误收敛成组件内状态。
 *
 * @param searchQuery 本次请求使用的搜索词；空字符串表示浏览后端默认列表。
 */
async function runSearch(searchQuery: string): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    results.value = await searchPokemon(searchQuery, props.rulesetId);
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '搜索失败';
  } finally {
    loading.value = false;
  }
}

/**
 * 将组件选择事件转发给页面，并恢复到空搜索状态。
 *
 * @param pokemon 用户从默认列表、搜索结果或最近记录中选择的 Pokémon。
 */
function selectPokemon(pokemon: PokemonSearchItem): void {
  emit('select', pokemon);
  browsingAll.value = false;
  if (query.value !== '') {
    query.value = '';
  }
}

/** 主动展开后端默认列表；最近记录仍保留在父级页面状态中。 */
function showAllPokemon(): void {
  browsingAll.value = true;
  void runSearch('');
}

/** 返回最近选择视图，并隐藏浏览全部期间产生的加载或错误状态。 */
function showRecentPokemon(): void {
  browsingAll.value = false;
  loading.value = false;
  error.value = null;
}

/** 在空搜索状态下切换“最近选择”和“浏览全部”两种列表视图。 */
function toggleEmptyQueryList(): void {
  if (showingRecentPokemon.value) {
    showAllPokemon();
    return;
  }
  showRecentPokemon();
}

/**
 * 防抖执行文本搜索；清空搜索词且已有最近记录时直接回到最近视图，不额外请求默认列表。
 */
watch(query, (nextQuery) => {
  window.clearTimeout(timer);
  browsingAll.value = false;
  error.value = null;

  if (nextQuery.trim() === '' && hasRecentPokemon.value) {
    loading.value = false;
    return;
  }

  loading.value = true;
  timer = window.setTimeout(() => {
    void runSearch(nextQuery);
  }, 250);
});

/** 组件卸载时取消尚未触发的防抖任务，避免离开页面后继续发起搜索。 */
onBeforeUnmount(() => {
  window.clearTimeout(timer);
});

// 首次进入且没有页面会话历史时，保持原有的默认列表体验。
if (!hasRecentPokemon.value) {
  void runSearch('');
}
</script>

<template>
  <section class="panel-block">
    <div class="field-title">{{ title }}</div>
    <input
      v-model="query"
      class="search-input"
      data-testid="pokemon-search-input"
      type="search"
      placeholder="中文名或 identifier"
    />
    <div v-if="selected" class="selected-line">
      <span>{{ selected.display_name }}</span>
      <span class="muted">{{ selected.identifier }}</span>
    </div>
    <div v-if="hasRecentPokemon && normalizedQuery === ''" class="selected-line">
      <span class="muted">{{ showingRecentPokemon ? '最近选择' : '全部 Pokémon' }}</span>
      <button
        class="state-pill"
        data-testid="pokemon-list-toggle"
        type="button"
        @click="toggleEmptyQueryList"
      >
        {{ showingRecentPokemon ? '浏览全部' : '返回最近' }}
      </button>
    </div>
    <div v-if="!showingRecentPokemon && loading" class="muted row-message">加载中</div>
    <div v-else-if="!showingRecentPokemon && error" class="error row-message">{{ error }}</div>
    <div v-else-if="visiblePokemon.length === 0" class="muted row-message">没有匹配的 Pokémon</div>
    <div v-else class="option-list" :data-mode="listMode">
      <button
        v-for="pokemon in visiblePokemon"
        :key="pokemon.pokemon_id"
        class="list-option"
        :data-pokemon-id="pokemon.pokemon_id"
        type="button"
        @click="selectPokemon(pokemon)"
      >
        <span class="option-main">{{ pokemon.display_name }}</span>
        <span class="option-sub">{{ pokemon.identifier }}</span>
        <span class="type-list">
          <span v-for="type in pokemon.type_names" :key="type" class="type-chip">{{ type }}</span>
        </span>
      </button>
    </div>
  </section>
</template>
