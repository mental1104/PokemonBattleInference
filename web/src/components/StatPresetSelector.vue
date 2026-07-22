<script setup lang="ts">
import type { StatPreset } from '../api/calculator';

defineProps<{
  title: string;
  presets: StatPreset[];
  modelValue: string;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: string];
}>();
</script>

<template>
  <section class="panel-block">
    <div class="field-title">{{ title }}</div>
    <div class="preset-grid">
      <button
        v-for="preset in presets"
        :key="preset.key"
        class="preset-button"
        :class="{ active: preset.key === modelValue }"
        type="button"
        @click="emit('update:modelValue', preset.key)"
      >
        <span>{{ preset.label }}</span>
        <small>{{ preset.assumption }}</small>
      </button>
    </div>
  </section>
</template>
