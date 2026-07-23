<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import {
  listPokemonMoves,
  type ListPokemonMovesRequest,
  type MoveFilterCategory,
  type MoveSearchItem,
  type MoveSearchPage,
  type MoveTypeOption,
} from '../api/calculator';
import './MoveSelector.css';

const EMBEDDED_LIMIT = 10;
const MODAL_LIMIT = 50;
const CATEGORY_OPTIONS: readonly (readonly [MoveFilterCategory, string])[] = [
  ['all', '全部'],
  ['physical', '物理'],
  ['special', '特殊'],
];

const props = defineProps<{
  pokemonId: number | null;
  rulesetId: string;
  selected: MoveSearchItem | null;
  disabled: boolean;
}>();

const emit = defineEmits<{
  select: [move: MoveSearchItem];
  clearSelection: [];
}>();

const query = ref('');
const category = ref<MoveFilterCategory>('all');
const selectedTypes = ref<string[]>([]);
const page = ref<MoveSearchPage | null>(null);
const typeOptions = ref<MoveTypeOption[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);
const modalOpen = ref(false);
const modalItems = ref<MoveSearchItem[]>([]);
const modalTotal = ref(0);
const modalHasMore = ref(false);
const modalLoading = ref(false);
const modalError = ref<string | null>(null);
const modalElement = ref<HTMLElement | null>(null);
let searchTimer: number | undefined;
let embeddedRequestVersion = 0;
let modalRequestVersion = 0;

const moves = computed(() => page.value?.items ?? []);
const availableTypes = computed(() => typeOptions.value);
const canOpenModal = computed(
  () => Boolean(page.value && (page.value.has_more || page.value.total > EMBEDDED_LIMIT)),
);

/**
 * 根据当前筛选状态构造一次服务端招式查询。
 *
 * @param limit 本次分页上限，页面内使用 10，弹窗使用 50。
 * @param offset 稳定排序结果中的起始偏移。
 * @returns 可直接传给 API client 的显式查询对象。
 */
function buildRequest(limit: number, offset: number): ListPokemonMovesRequest {
  return {
    query: query.value.trim(),
    category: category.value,
    typeIdentifiers: selectedTypes.value,
    limit,
    offset,
  };
}

/**
 * 判断当前已选招式是否仍符合前端可直接判断的筛选条件。
 *
 * @param move 当前 calculator 已选招式。
 * @returns 类别、属性和文本条件均匹配时返回 true。
 */
function matchesCurrentFilters(move: MoveSearchItem): boolean {
  if (category.value !== 'all' && move.category !== category.value) return false;
  if (selectedTypes.value.length > 0 && !selectedTypes.value.includes(move.type)) return false;

  const normalizedQuery = query.value.trim().toLocaleLowerCase();
  if (normalizedQuery === '') return true;
  return (
    move.identifier.toLocaleLowerCase().includes(normalizedQuery) ||
    move.display_name.toLocaleLowerCase().includes(normalizedQuery)
  );
}

/** 当前选择被新筛选排除时通知父层清空，避免提交失效 move_id。 */
function clearSelectionIfFilteredOut(): void {
  if (props.selected && !matchesCurrentFilters(props.selected)) {
    emit('clearSelection');
  }
}

/** 关闭并清空弹窗分页状态，同时使尚未返回的旧弹窗请求失效。 */
function resetModalState(): void {
  modalOpen.value = false;
  modalItems.value = [];
  modalTotal.value = 0;
  modalHasMore.value = false;
  modalLoading.value = false;
  modalError.value = null;
  modalRequestVersion += 1;
}

/** 加载页面内嵌的前 10 条结果；旧请求晚到时不会覆盖新筛选。 */
async function loadEmbeddedPage(): Promise<void> {
  const requestVersion = ++embeddedRequestVersion;
  if (props.disabled || props.pokemonId === null) {
    page.value = null;
    loading.value = false;
    error.value = null;
    return;
  }

  loading.value = true;
  error.value = null;
  try {
    const response = await listPokemonMoves(
      props.pokemonId,
      props.rulesetId,
      buildRequest(EMBEDDED_LIMIT, 0),
    );
    if (requestVersion !== embeddedRequestVersion) return;
    page.value = response;
    typeOptions.value = response.available_types;
  } catch (caught) {
    if (requestVersion !== embeddedRequestVersion) return;
    page.value = null;
    error.value = caught instanceof Error ? caught.message : '招式加载失败';
  } finally {
    if (requestVersion === embeddedRequestVersion) {
      loading.value = false;
    }
  }
}

/** 在筛选条件变化后立即重置分页，并重新加载页面内结果。 */
function reloadForFilterChange(): void {
  resetModalState();
  clearSelectionIfFilteredOut();
  void loadEmbeddedPage();
}

/**
 * 切换类别单选值并重置分页。
 *
 * @param nextCategory 用户选择的全部、物理或特殊类别。
 */
function setCategory(nextCategory: MoveFilterCategory): void {
  if (category.value === nextCategory) return;
  category.value = nextCategory;
  reloadForFilterChange();
}

/**
 * 切换一个属性筛选项；多个已选属性之间由服务端按 OR 处理。
 *
 * @param typeIdentifier 当前规则集属性元数据中的稳定 identifier。
 */
function toggleType(typeIdentifier: string): void {
  if (selectedTypes.value.includes(typeIdentifier)) {
    selectedTypes.value = selectedTypes.value.filter((item) => item !== typeIdentifier);
  } else {
    selectedTypes.value = [...selectedTypes.value, typeIdentifier];
  }
  reloadForFilterChange();
}

/** 清空全部属性筛选并重新加载第一页。 */
function clearTypeFilters(): void {
  if (selectedTypes.value.length === 0) return;
  selectedTypes.value = [];
  reloadForFilterChange();
}

/**
 * 加载弹窗中的一页结果并按 move_id 去重追加。
 *
 * @param offset 本次弹窗请求的起始偏移；首次为 0，后续为已加载数量。
 */
async function loadModalPage(offset: number): Promise<void> {
  if (props.disabled || props.pokemonId === null || modalLoading.value) return;

  const requestVersion = ++modalRequestVersion;
  modalLoading.value = true;
  modalError.value = null;
  try {
    const response = await listPokemonMoves(
      props.pokemonId,
      props.rulesetId,
      buildRequest(MODAL_LIMIT, offset),
    );
    if (requestVersion !== modalRequestVersion || !modalOpen.value) return;

    const uniqueMoves = new Map<number, MoveSearchItem>();
    for (const move of modalItems.value) uniqueMoves.set(move.move_id, move);
    for (const move of response.items) uniqueMoves.set(move.move_id, move);
    modalItems.value = [...uniqueMoves.values()];
    modalTotal.value = response.total;
    modalHasMore.value = modalItems.value.length < response.total;
  } catch (caught) {
    if (requestVersion !== modalRequestVersion || !modalOpen.value) return;
    modalError.value = caught instanceof Error ? caught.message : '招式加载失败';
  } finally {
    if (requestVersion === modalRequestVersion) {
      modalLoading.value = false;
    }
  }
}

/** 打开弹窗，继承当前筛选并从最多 50 条的第一页开始加载。 */
async function openModal(): Promise<void> {
  if (props.disabled || props.pokemonId === null) return;
  modalOpen.value = true;
  modalItems.value = [];
  modalTotal.value = 0;
  modalHasMore.value = false;
  modalError.value = null;
  await nextTick();
  modalElement.value?.focus();
  void loadModalPage(0);
}

/** 关闭弹窗并取消接受尚未返回的弹窗请求。 */
function closeModal(): void {
  modalOpen.value = false;
  modalLoading.value = false;
  modalError.value = null;
  modalRequestVersion += 1;
}

/** 从当前已加载数量继续请求下一批最多 50 条结果。 */
function loadMore(): void {
  void loadModalPage(modalItems.value.length);
}

/**
 * 选择招式并关闭弹窗。
 *
 * @param move 用户在页面内列表或弹窗列表中选择的招式。
 */
function selectMove(move: MoveSearchItem): void {
  emit('select', move);
  closeModal();
}

/** 文本输入保留 250ms 防抖，筛选变化时立即清理旧分页和失效选择。 */
watch(query, () => {
  window.clearTimeout(searchTimer);
  // 输入一变化就让在途请求失效并清空旧页，防止防抖窗口内短暂回闪过期结果。
  embeddedRequestVersion += 1;
  page.value = null;
  resetModalState();
  clearSelectionIfFilteredOut();
  loading.value = true;
  searchTimer = window.setTimeout(() => {
    void loadEmbeddedPage();
  }, 250);
});

/** 攻击方或规则集变化时清空旧分页，并为新上下文加载第一页。 */
watch(
  () => [props.pokemonId, props.rulesetId, props.disabled] as const,
  (nextContext, previousContext) => {
    window.clearTimeout(searchTimer);
    embeddedRequestVersion += 1;
    resetModalState();
    page.value = null;
    error.value = null;

    // 属性 identifier 属于规则集元数据；规则集变化时清空旧选项与旧选择，避免提交非法筛选。
    if (previousContext && nextContext[1] !== previousContext[1]) {
      selectedTypes.value = [];
      typeOptions.value = [];
    }
    void loadEmbeddedPage();
  },
  { immediate: true },
);

/** 组件卸载时让所有计时器和未完成请求失效。 */
onBeforeUnmount(() => {
  window.clearTimeout(searchTimer);
  embeddedRequestVersion += 1;
  modalRequestVersion += 1;
});
</script>

<template>
  <section class="panel-block move-selector">
    <div class="field-title">招式</div>

    <div class="move-filter-group" role="group" aria-label="招式类别">
      <button
        v-for="option in CATEGORY_OPTIONS"
        :key="option[0]"
        class="filter-button"
        :class="{ active: category === option[0] }"
        type="button"
        :disabled="disabled"
        :aria-pressed="category === option[0]"
        @click="setCategory(option[0])"
      >
        {{ option[1] }}
      </button>
    </div>

    <div v-if="availableTypes.length > 0" class="move-type-filter" aria-label="招式属性">
      <button
        v-for="typeOption in availableTypes"
        :key="typeOption.identifier"
        class="type-chip filter-chip"
        :class="{ active: selectedTypes.includes(typeOption.identifier) }"
        type="button"
        :disabled="disabled"
        :aria-pressed="selectedTypes.includes(typeOption.identifier)"
        @click="toggleType(typeOption.identifier)"
      >
        {{ typeOption.display_name }}
      </button>
      <button
        v-if="selectedTypes.length > 0"
        class="text-button"
        type="button"
        @click="clearTypeFilters"
      >
        清空属性
      </button>
    </div>

    <input
      v-model="query"
      class="search-input"
      data-testid="move-search-input"
      type="search"
      placeholder="名称或 identifier"
      :disabled="disabled"
    />

    <div v-if="selected" class="selected-line">
      <span>{{ selected.display_name }}</span>
      <span class="muted">{{ selected.type_name }} · {{ selected.category }} · {{ selected.power }}</span>
    </div>

    <div v-if="disabled" class="muted row-message">先选择攻击方</div>
    <div v-else-if="loading" class="muted row-message">加载中</div>
    <div v-else-if="error" class="error row-message">
      <span>{{ error }}</span>
      <button class="text-button" type="button" @click="loadEmbeddedPage">重试</button>
    </div>
    <div v-else-if="moves.length === 0" class="muted row-message">没有符合条件的可计算招式</div>
    <div v-else class="option-list compact" data-testid="embedded-move-list">
      <button
        v-for="moveItem in moves"
        :key="moveItem.move_id"
        class="list-option"
        type="button"
        @click="selectMove(moveItem)"
      >
        <span class="option-main">{{ moveItem.display_name }}</span>
        <span class="option-sub">{{ moveItem.type_name }} · {{ moveItem.category }} · {{ moveItem.power }}</span>
      </button>
    </div>

    <button
      v-if="canOpenModal"
      class="secondary-button move-more-button"
      data-testid="open-move-modal"
      type="button"
      @click="openModal"
    >
      查看全部（{{ page?.total }}）
    </button>

    <div v-if="modalOpen" class="move-modal-backdrop" @click.self="closeModal">
      <section
        ref="modalElement"
        class="move-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="move-modal-title"
        tabindex="-1"
        @keydown.esc.prevent="closeModal"
      >
        <header class="move-modal-header">
          <div>
            <h2 id="move-modal-title">选择招式</h2>
            <p class="muted">当前筛选共 {{ modalTotal }} 项</p>
          </div>
          <button class="text-button" type="button" aria-label="关闭招式弹窗" @click="closeModal">
            关闭
          </button>
        </header>

        <div v-if="modalItems.length > 0" class="option-list move-modal-list">
          <button
            v-for="moveItem in modalItems"
            :key="moveItem.move_id"
            class="list-option"
            type="button"
            @click="selectMove(moveItem)"
          >
            <span class="option-main">{{ moveItem.display_name }}</span>
            <span class="option-sub">{{ moveItem.type_name }} · {{ moveItem.category }} · {{ moveItem.power }}</span>
          </button>
        </div>

        <div v-if="modalLoading" class="muted row-message">加载中</div>
        <div v-else-if="modalError" class="error row-message">
          <span>{{ modalError }}</span>
          <button class="text-button" type="button" @click="loadMore">重试</button>
        </div>
        <button
          v-else-if="modalHasMore"
          class="secondary-button move-more-button"
          data-testid="load-more-moves"
          type="button"
          @click="loadMore"
        >
          加载更多
        </button>
        <div v-else-if="modalItems.length > 0" class="muted row-message">已加载全部结果</div>
        <div v-else class="muted row-message">没有符合条件的可计算招式</div>
      </section>
    </div>
  </section>
</template>
