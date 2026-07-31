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
const searchQuery = ref('');

const selectedItem = computed(
  () =>
    props.items.find((item) => item.identifier === props.selectedIdentifier) ??
    props.items[0] ??
    null,
);

/**
 * 规范化道具搜索文本，使空格、连字符和下划线不影响 identifier 匹配。
 *
 * @param value 用户输入或道具名称。
 * @returns 小写且移除常见分隔符的检索文本。
 */
function normalizeSearchText(value: string): string {
  return value.trim().toLocaleLowerCase().replace(/[\s_-]+/g, '');
}

/**
 * 判断道具是否已经接入伤害 domain。
 *
 * @param item 服务端返回的一项道具；显式不携带道具始终可选。
 * @returns 无道具或拥有 effect identifier 时返回 true，否则表示仅展示、暂不可选。
 */
function isImplemented(item: BattleItemOption): boolean {
  return item.item_id === null || item.effect_identifier !== null;
}

/**
 * 解析道具图标地址；旧接口未给未实现道具返回 URL 时使用统一 assets 路径。
 *
 * @param item 服务端返回的一项道具。
 * @returns 可加载的项目内图标地址；“不携带道具”返回 null。
 */
function itemSpriteUrl(item: BattleItemOption): string | null {
  if (item.sprite_url) return item.sprite_url;
  if (item.item_id === null) return null;
  return `/api/v1/assets/items/${item.identifier}/sprite`;
}

const filteredItems = computed(() => {
  const normalizedQuery = normalizeSearchText(searchQuery.value);
  if (!normalizedQuery) return props.items;

  return props.items.filter((item) => {
    const displayName = normalizeSearchText(item.display_name);
    const identifier = normalizeSearchText(item.identifier);
    return displayName.includes(normalizedQuery) || identifier.includes(normalizedQuery);
  });
});

/** 打开道具选择弹窗；禁用或加载中时保持当前状态。 */
function openModal(): void {
  if (props.disabled || props.loading) return;
  // 每次打开都从完整列表开始，避免上次搜索词让用户误以为道具缺失。
  searchQuery.value = '';
  modalOpen.value = true;
}

/** 关闭道具选择弹窗。 */
function closeModal(): void {
  modalOpen.value = false;
}

/**
 * 选择一个已实现道具并关闭弹窗。
 *
 * @param item 用户在弹窗中点击的道具选项；未实现选项只展示，不产生状态变化。
 */
function selectItem(item: BattleItemOption): void {
  // UI 禁用之外保留函数级守卫，避免程序化触发绕过 disabled 属性。
  if (!isImplemented(item)) return;
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
          v-if="itemSpriteUrl(selectedItem)"
          class="item-selector__sprite"
          :src="itemSpriteUrl(selectedItem) ?? undefined"
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

        <div class="item-selector-modal__toolbar">
          <label class="item-selector-modal__search">
            <span class="item-selector__visually-hidden">搜索道具</span>
            <input
              v-model="searchQuery"
              type="search"
              placeholder="搜索中文名或 identifier"
              autocomplete="off"
            />
          </label>
          <span class="item-selector-modal__count" aria-live="polite">
            {{ filteredItems.length }} / {{ items.length }}
          </span>
        </div>

        <div class="item-selector-modal__list">
          <div
            v-for="item in filteredItems"
            :key="item.identifier"
            class="item-selector-option-wrap"
            :class="{ 'is-unimplemented': !isImplemented(item) }"
            :title="isImplemented(item) ? undefined : '当前未实现'"
          >
            <button
              type="button"
              class="item-selector-option"
              :class="{ active: item.identifier === selectedIdentifier }"
              :disabled="!isImplemented(item)"
              :data-item-identifier="item.identifier"
              @click="selectItem(item)"
            >
              <img
                v-if="itemSpriteUrl(item)"
                class="item-selector__sprite"
                :src="itemSpriteUrl(item) ?? undefined"
                :alt="item.display_name"
                loading="lazy"
              />
              <span v-else class="item-selector__empty-icon">无</span>
              <span class="item-selector-option__label">
                <strong>{{ item.display_name }}</strong>
                <small>{{ item.identifier }}</small>
              </span>
              <span
                v-if="!isImplemented(item)"
                class="item-selector-option__unimplemented"
                aria-label="当前未实现"
              >
                ⊘
              </span>
            </button>
          </div>
          <p v-if="filteredItems.length === 0" class="item-selector-modal__empty">
            未找到匹配的道具
          </p>
        </div>
      </section>
    </div>
  </section>
</template>
