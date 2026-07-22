<script setup lang="ts">
import type { CalculationScope } from '../api/calculator';

defineProps<{
  scope: CalculationScope | null;
}>();
</script>

<template>
  <section class="scope-band">
    <div>
      <h2>计入范围</h2>
      <div class="scope-list">
        <span v-for="item in scope?.included ?? []" :key="item">{{ item }}</span>
      </div>
    </div>
    <div>
      <h2>未启用机制</h2>
      <div class="scope-list muted-list">
        <span v-for="item in scope?.excluded ?? []" :key="item">{{ item }}</span>
      </div>
    </div>
  </section>
</template>
