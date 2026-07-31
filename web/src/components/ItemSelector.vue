<script setup lang="ts">
import { computed, ref } from 'vue';
import type { BattleItemOption } from '../api/calculator';
import './ItemSelector.css';

const props = defineProps<{
  title: string;
  items: readonly BattleItemOption[];
  selectedIdentifier: string;
  disabled: boolean;
  loading: boolean;
}>();

const emit = defineEmits<{
  select: [item: BattleItemOption];
}>();

const modalOpen = ref(false);

const selectedItem = computed(
  () =>
    props.items.find((item) => item.identifier === props.selectedIdentifier) ??
    props.items[0] ??
    null,
);

/** 打开道具选择弹窗；禁用或加载中时保持当前状态。 */
function openModal(): void {
  if (props.disabled || props.loading) return;
  modalOpen.value = true;
}

/** 关闭道具选择弹窗。 */
function closeModal(): void {
  modalOpen.value = false;
}

/**
 * 选择一个道具并关闭弹窗。
 *
 * @param item 用户在弹窗中点击的道具选项。
 */
function selectItem(item: BattleItemOption): void {
  emit('select', item);
  closeModal();
}
</script>

<template>
  <section class="panel-block item-selector">
    <div class="field-title">{{ title }}</div>
    <button
      type="button"
      class="item-selector__trigger"
      :disabled="disabled || loading"
      @click="openModal"
    >
      <span v-if="loading" class="muted">道具加载中</span>
      <span v-else-if="selectedItem" class="item-selector__current">
        <img
          v-if="selectedItem.sprite_url"
          class="item-selector__sprite"
          :src="selectedItem.sprite_url"
          :alt="selectedItem.display_name"
          loading="lazy"
        />
        <span v-else class="item-selector__empty-icon">无</span>
        <span>{{ selectedItem.display_name }}</span>
      </span>
      <span v-else class="muted">暂无可选道具</span>
    </button>

    <div v-if="modalOpen" class="item-selector-modal" role="dialog" aria-modal="true" @click.self="closeModal">
      <section class="item-selector-modal__panel" aria-label="选择道具">
        <header>
          <h3>选择道具</h3>
          <button type="button" class="icon-button" aria-label="关闭道具弹窗" @click="closeModal">×</button>
        </header>
        <div class="item-selector-modal__list">
          <button
            v-for="item in items"
            :key="item.identifier"
            type="button"
            class="item-selector-option"
            :class="{ active: item.identifier === selectedIdentifier }"
            @click="selectItem(item)"
          >
            <img
              v-if="item.sprite_url"
              class="item-selector__sprite"
              :src="item.sprite_url"
              :alt="item.display_name"
              loading="lazy"
            />
            <span v-else class="item-selector__empty-icon">无</span>
            <span>
              <strong>{{ item.display_name }}</strong>
              <small>{{ item.identifier }}</small>
            </span>
          </button>
        </div>
      </section>
    </div>
  </section>
</template>
