<script setup lang="ts">
import { ref, watch } from 'vue';
import type { MoveSearchItem } from '../api/calculator';

defineProps<{
  moves: MoveSearchItem[];
  selected: MoveSearchItem | null;
  disabled: boolean;
}>();

const emit = defineEmits<{
  select: [move: MoveSearchItem];
  search: [query: string];
}>();

const query = ref('');
let timer: number | undefined;

/** 防抖转发招式搜索词，实际数据由父层按攻击方和 ruleset 查询。 */
watch(query, () => {
  window.clearTimeout(timer);
  timer = window.setTimeout(() => emit('search', query.value), 250);
});
</script>

<template>
  <section class="panel-block">
    <div class="field-title">招式</div>
    <input
      v-model="query"
      class="search-input"
      type="search"
      placeholder="按攻击方过滤"
      :disabled="disabled"
    />
    <div v-if="selected" class="selected-line">
      <span>{{ selected.display_name }}</span>
      <span class="muted">{{ selected.power }} · {{ selected.category }}</span>
    </div>
    <div v-if="disabled" class="muted row-message">先选择攻击方</div>
    <div v-else class="option-list compact">
      <button
        v-for="move in moves"
        :key="move.move_id"
        class="list-option"
        type="button"
        @click="emit('select', move)"
      >
        <span class="option-main">{{ move.display_name }}</span>
        <span class="option-sub">{{ move.type_name }} · {{ move.category }} · {{ move.power }}</span>
      </button>
    </div>
  </section>
</template>
