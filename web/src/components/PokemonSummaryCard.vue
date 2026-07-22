<script setup lang="ts">
import type { PokemonDetail } from '../api/calculator';

defineProps<{
  pokemon: PokemonDetail | null;
}>();
</script>

<template>
  <div class="summary-box">
    <template v-if="pokemon">
      <div class="summary-name">{{ pokemon.display_name }}</div>
      <div class="muted">{{ pokemon.identifier }}</div>
      <div class="type-list">
        <span v-for="type in pokemon.type_names" :key="type" class="type-chip">{{ type }}</span>
      </div>
    </template>
    <span v-else class="muted">未选择</span>
  </div>
</template>
