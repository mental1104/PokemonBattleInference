<script setup lang="ts">
import { ref, watch } from 'vue';
import type { PokemonDetail } from '../api/calculator';
import './PokemonSummaryCard.css';

const props = defineProps<{
  pokemon: PokemonDetail | null;
}>();

const imageFailed = ref(false);

/** 选择变化后重新允许图片加载，404 或网络错误只隐藏图片。 */
watch(
  () => props.pokemon?.sprite_url,
  () => {
    imageFailed.value = false;
  },
);
</script>

<template>
  <div class="summary-box pokemon-summary-card" data-testid="pokemon-summary-card">
    <template v-if="pokemon">
      <div class="summary-layout">
        <img
          v-if="!imageFailed"
          class="pokemon-sprite"
          data-testid="pokemon-summary-visual"
          :src="pokemon.sprite_url"
          :alt="pokemon.display_name"
          loading="lazy"
          @error="imageFailed = true"
        />
        <div
          v-else
          class="pokemon-sprite placeholder"
          data-testid="pokemon-summary-visual"
          aria-hidden="true"
        ></div>
        <div class="summary-copy">
          <div class="summary-name">{{ pokemon.display_name }}</div>
          <div class="muted">{{ pokemon.identifier }}</div>
          <div class="type-list">
            <span v-for="type in pokemon.type_names" :key="type" class="type-chip">{{ type }}</span>
          </div>
        </div>
      </div>
    </template>
    <span v-else class="muted">未选择</span>
  </div>
</template>
