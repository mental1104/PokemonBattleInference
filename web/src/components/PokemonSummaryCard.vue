<script setup lang="ts">
import { ref, watch } from 'vue';
import type { BattleStatStages, PokemonDetail } from '../api/calculator';
import BattleStatStageSelector from './BattleStatStageSelector.vue';
import './PokemonSummaryCard.css';

const props = defineProps<{
  /** 当前已选择的 Pokémon；为空时摘要卡只显示未选择提示。 */
  pokemon: PokemonDetail | null;
  /** 可选的战斗能力等级；提供时在摘要卡右侧展示七项选择器。 */
  statStages?: BattleStatStages;
}>();

const emit = defineEmits<{
  /** 用户修改战斗能力等级后，把完整新快照交给页面状态。 */
  'update:statStages': [value: BattleStatStages];
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
      <div class="summary-layout" :class="{ 'has-stat-stages': statStages }">
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
        <BattleStatStageSelector
          v-if="statStages"
          :model-value="statStages"
          @update:model-value="emit('update:statStages', $event)"
        />
      </div>
    </template>
    <span v-else class="muted">未选择</span>
  </div>
</template>
