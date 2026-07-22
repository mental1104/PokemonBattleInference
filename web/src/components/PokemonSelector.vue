<script setup lang="ts">
import { ref, watch } from 'vue';
import { searchPokemon, type PokemonSearchItem } from '../api/calculator';

const props = defineProps<{
  title: string;
  rulesetId: string;
  selected: PokemonSearchItem | null;
}>();

const emit = defineEmits<{
  select: [pokemon: PokemonSearchItem];
}>();

const query = ref('');
const results = ref<PokemonSearchItem[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);
let timer: number | undefined;

/** 按当前输入搜索宝可梦，并把网络错误收敛成组件内错误状态。 */
async function runSearch(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    results.value = await searchPokemon(query.value, props.rulesetId);
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '搜索失败';
  } finally {
    loading.value = false;
  }
}

/** 防抖搜索，避免每个按键都立即打到后端。 */
watch(query, () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(() => {
    void runSearch();
  }, 250);
});

void runSearch();
</script>

<template>
  <section class="panel-block">
    <div class="field-title">{{ title }}</div>
    <input
      v-model="query"
      class="search-input"
      type="search"
      placeholder="中文名或 identifier"
    />
    <div v-if="selected" class="selected-line">
      <span>{{ selected.display_name }}</span>
      <span class="muted">{{ selected.identifier }}</span>
    </div>
    <div v-if="loading" class="muted row-message">加载中</div>
    <div v-else-if="error" class="error row-message">{{ error }}</div>
    <div v-else class="option-list">
      <button
        v-for="pokemon in results"
        :key="pokemon.pokemon_id"
        class="list-option"
        type="button"
        @click="emit('select', pokemon)"
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
