<script setup lang="ts">
import { computed } from 'vue';
import type { BattleAbilityOption } from '../api/calculator';
import './AbilitySelector.css';

const props = defineProps<{
  title: string;
  abilities: readonly BattleAbilityOption[];
  selectedIdentifier: string;
  disabled: boolean;
  loading: boolean;
}>();

const emit = defineEmits<{
  select: [ability: BattleAbilityOption];
}>();

const selectedAbility = computed(
  () =>
    props.abilities.find(
      (ability) => ability.identifier === props.selectedIdentifier,
    ) ?? null,
);
</script>

<template>
  <section class="panel-block ability-selector">
    <div class="field-title">{{ title }}</div>
    <p v-if="loading" class="muted">特性加载中</p>
    <p v-else-if="abilities.length === 0" class="muted">暂无可选特性</p>
    <div v-else class="ability-selector__options" role="radiogroup" :aria-label="title">
      <button
        v-for="ability in abilities"
        :key="ability.identifier"
        type="button"
        class="ability-selector__option"
        :class="{
          active: ability.identifier === selectedIdentifier,
          unsupported: !ability.implemented,
        }"
        :disabled="disabled"
        role="radio"
        :aria-checked="ability.identifier === selectedIdentifier"
        @click="emit('select', ability)"
      >
        <span class="ability-selector__name">
          <strong>{{ ability.display_name }}</strong>
          <small>{{ ability.identifier }}</small>
        </span>
        <span v-if="ability.is_hidden" class="ability-selector__hidden">隐藏特性</span>
        <span
          v-if="!ability.implemented"
          class="ability-selector__unsupported"
          title="当前未实现，参与计算时按无特性处理"
          aria-label="当前未实现，参与计算时按无特性处理"
        >
          ⊘ 未实现
        </span>
      </button>
    </div>
    <p
      v-if="selectedAbility && !selectedAbility.implemented"
      class="ability-selector__notice"
    >
      当前选择尚未实现，本次计算按无特性处理。
    </p>
  </section>
</template>
