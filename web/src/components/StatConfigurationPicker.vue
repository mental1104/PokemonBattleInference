<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import {
  createStatConfiguration,
  deleteStatConfiguration,
  listNatures,
  listStatConfigurations,
  saveStatConfigurationOrder,
  updateStatConfiguration,
  type NatureOption,
  type PokemonBindingKind,
  type SaveStatConfigurationRequest,
  type StatConfiguration,
  type StatConfigurationRole,
  type StatSpread,
} from '../api/statConfigurations';

const props = defineProps<{
  title: string;
  role: 'attacker' | 'defender';
  pokemonId: number | null;
  pokemonName: string | null;
  modelValue: string;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: string];
}>();

const EMPTY_EVS: StatSpread = {
  hp: 0,
  attack: 0,
  defense: 0,
  special_attack: 0,
  special_defense: 0,
  speed: 0,
};
const PERFECT_IVS: StatSpread = {
  hp: 31,
  attack: 31,
  defense: 31,
  special_attack: 31,
  special_defense: 31,
  speed: 31,
};
const FIELD_LABELS: Record<keyof StatSpread, string> = {
  hp: 'HP',
  attack: 'Attack',
  defense: 'Defense',
  special_attack: 'Sp. Atk',
  special_defense: 'Sp. Def',
  speed: 'Speed',
};
const STAT_FIELDS = Object.keys(FIELD_LABELS) as (keyof StatSpread)[];

const loading = ref(false);
const saving = ref(false);
const error = ref<string | null>(null);
const natures = ref<NatureOption[]>([]);
const configurations = ref<StatConfiguration[]>([]);
const fallbackId = ref<string | null>(null);
const manageOpen = ref(false);
const deleteTarget = ref<StatConfiguration | null>(null);
const showIvs = ref(false);
const activeConfigId = ref<string | null>(null);
const managerMode = ref<'view' | 'create'>('view');
const draggingConfigId = ref<string | null>(null);
const draggingDirty = ref(false);
const draggingIndex = ref<number | null>(null);
let dragPressTimer: number | undefined;

const form = reactive<SaveStatConfigurationRequest>({
  name: '',
  nature_id: 'hardy',
  evs: { ...EMPTY_EVS },
  ivs: { ...PERFECT_IVS },
  role: props.role,
  binding_kind: 'global',
  pokemon_id: null,
});

const visibleConfigurations = computed(() => configurations.value.filter((item) => !item.hidden));
const topConfigurations = computed(() => visibleConfigurations.value.slice(0, 6));
const selectedConfiguration = computed(
  () => configurations.value.find((item) => item.snapshot_profile_id === props.modelValue) ?? null,
);
const activeConfiguration = computed(
  () => configurations.value.find((item) => item.id === activeConfigId.value) ?? null,
);
const activeCanEdit = computed(
  () => managerMode.value === 'create' || (activeConfiguration.value?.editable ?? false),
);
const evTotal = computed(() => STAT_FIELDS.reduce((total, field) => total + form.evs[field], 0));
const evRemaining = computed(() => Math.max(0, 510 - evTotal.value));
const formErrors = computed(() => {
  const messages: string[] = [];
  if (form.name.trim().length === 0) messages.push('名称不能为空。');
  if (form.name.trim().length > 48) messages.push('名称最多 48 个字符。');
  if (!natures.value.some((nature) => nature.identifier === form.nature_id)) {
    messages.push('请选择合法性格。');
  }
  for (const field of STAT_FIELDS) {
    if (!Number.isInteger(form.evs[field]) || form.evs[field] < 0 || form.evs[field] > 252) {
      messages.push(`${FIELD_LABELS[field]} EV 必须为 0..252。`);
    }
    if (!Number.isInteger(form.ivs[field]) || form.ivs[field] < 0 || form.ivs[field] > 31) {
      messages.push(`${FIELD_LABELS[field]} IV 必须为 0..31。`);
    }
  }
  if (evTotal.value > 510) messages.push('EV 总和不能超过 510。');
  if (form.binding_kind === 'pokemon' && props.pokemonId === null) {
    messages.push('指定 Pokémon 配置需要先选择 Pokémon。');
  }
  return messages;
});
const canSave = computed(() => formErrors.value.length === 0 && !saving.value);

/** 初始化性格元数据并读取当前侧配置。 */
onMounted(async () => {
  try {
    natures.value = await listNatures();
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '性格列表加载失败';
  }
  await refreshConfigurations();
});

/** 组件卸载时清理长按拖拽计时器。 */
onBeforeUnmount(() => {
  window.clearTimeout(dragPressTimer);
});

watch(
  () => [props.pokemonId, props.role] as const,
  () => {
    void refreshConfigurations();
  },
);

/**
 * 读取当前 Pokémon 与角色可见的完整配置列表。
 *
 * @returns 请求完成后的 Promise。
 */
async function refreshConfigurations(): Promise<void> {
  if (props.pokemonId === null) {
    configurations.value = [];
    fallbackId.value = null;
    return;
  }
  loading.value = true;
  error.value = null;
  try {
    const result = await listStatConfigurations({
      role: props.role,
      pokemonId: props.pokemonId,
      includeHidden: true,
    });
    configurations.value = result.items;
    fallbackId.value = result.fallback_id;
    ensureValidSelection();
    ensureActiveManagerSelection();
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '配置列表加载失败';
  } finally {
    loading.value = false;
  }
}

/** 当前选择删除或因 Pokémon 切换失效时回退到第一条可见配置。 */
function ensureValidSelection(): void {
  const current = configurations.value.find(
    (item) => item.snapshot_profile_id === props.modelValue && !item.hidden,
  );
  if (current !== undefined) return;
  const fallback = visibleConfigurations.value[0] ?? null;
  if (fallback !== null) emit('update:modelValue', fallback.snapshot_profile_id);
}

/** 管理面板打开或列表刷新后，保证右侧始终有一条可渲染的配置。 */
function ensureActiveManagerSelection(): void {
  if (!manageOpen.value || managerMode.value === 'create') return;
  const active = activeConfiguration.value;
  if (active !== null && !active.hidden) {
    loadConfigIntoForm(active);
    return;
  }
  const selected = selectedConfiguration.value;
  const fallback = selected && !selected.hidden ? selected : (visibleConfigurations.value[0] ?? null);
  if (fallback !== null) {
    activeConfigId.value = fallback.id;
    loadConfigIntoForm(fallback);
  }
}

/**
 * 选择一条配置并提交其不可变快照。
 *
 * @param config 用户点击的配置。
 */
function selectConfiguration(config: StatConfiguration): void {
  if (config.hidden) return;
  emit('update:modelValue', config.snapshot_profile_id);
}

/** 打开配置管理工作区，并默认选中当前正在使用的配置。 */
function openManager(): void {
  manageOpen.value = true;
  managerMode.value = 'view';
  const selected = selectedConfiguration.value;
  const fallback = selected && !selected.hidden ? selected : (visibleConfigurations.value[0] ?? null);
  if (fallback !== null) {
    activeConfigId.value = fallback.id;
    loadConfigIntoForm(fallback);
  } else {
    openEditor();
  }
}

/** 关闭配置管理工作区，并取消未完成的拖拽状态。 */
function closeManager(): void {
  manageOpen.value = false;
  clearDragState();
}

/**
 * 在左侧栏切换配置，同时让右侧主区载入该配置的 EV、性格与 IV。
 *
 * @param config 用户点击的可见配置。
 */
function activateConfiguration(config: StatConfiguration): void {
  if (config.hidden) return;
  managerMode.value = 'view';
  activeConfigId.value = config.id;
  loadConfigIntoForm(config);
  selectConfiguration(config);
}

/**
 * 打开新建或编辑表单。
 *
 * @param config 被编辑的自定义配置；省略表示新建。
 */
function openEditor(config?: StatConfiguration): void {
  showIvs.value = false;
  const source = config ?? null;
  managerMode.value = source === null ? 'create' : 'view';
  activeConfigId.value = source?.id ?? null;
  form.name = source?.name ?? `${props.pokemonName ?? '通用'}配置`;
  form.nature_id = source?.nature_id ?? 'hardy';
  form.evs = { ...(source?.evs ?? EMPTY_EVS) };
  form.ivs = { ...(source?.ivs ?? PERFECT_IVS) };
  form.role = source?.role ?? props.role;
  form.binding_kind = source?.binding_kind ?? 'global';
  form.pokemon_id = source?.binding_kind === 'pokemon' ? source.pokemon_id : null;
}

/**
 * 把配置快照载入右侧主区表单；内置预设也使用同一表单，只是控件被禁用。
 *
 * @param config 后端返回的配置视图。
 */
function loadConfigIntoForm(config: StatConfiguration): void {
  showIvs.value = false;
  form.name = config.name;
  form.nature_id = config.nature_id;
  form.evs = { ...config.evs };
  form.ivs = { ...config.ivs };
  form.role = config.role;
  form.binding_kind = config.binding_kind;
  form.pokemon_id = config.binding_kind === 'pokemon' ? config.pokemon_id : null;
}

/** 保存新建或编辑配置，成功后刷新列表并选中新快照。 */
async function saveEditor(): Promise<void> {
  if (!canSave.value || !activeCanEdit.value) return;
  saving.value = true;
  error.value = null;
  const request: SaveStatConfigurationRequest = {
    name: form.name.trim(),
    nature_id: form.nature_id,
    evs: { ...form.evs },
    ivs: { ...form.ivs },
    role: form.role,
    binding_kind: form.binding_kind,
    pokemon_id: form.binding_kind === 'pokemon' ? props.pokemonId : null,
  };
  try {
    let saved: StatConfiguration;
    if (managerMode.value === 'create') {
      saved = await createStatConfiguration(request);
    } else {
      const targetKey = activeConfiguration.value?.key;
      if (targetKey === undefined) return;
      saved = await updateStatConfiguration(targetKey, request);
    }
    managerMode.value = 'view';
    await refreshConfigurations();
    activeConfigId.value = saved.id;
    loadConfigIntoForm(saved);
    emit('update:modelValue', saved.snapshot_profile_id);
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '配置保存失败';
  } finally {
    saving.value = false;
  }
}

/**
 * 设置某项 EV，拒绝越界或总和超限。
 *
 * @param field 被编辑的能力字段。
 * @param value 用户输入或滑块产生的整数值。
 * @returns 写入成功时返回 true；越界或总量超限时返回 false，调用方应恢复控件显示值。
 */
function setEv(field: keyof StatSpread, value: number): boolean {
  const normalized = Math.trunc(value);
  const otherTotal = evTotal.value - form.evs[field];
  if (!Number.isFinite(normalized) || normalized < 0 || normalized > 252) return false;
  if (otherTotal + normalized > 510) return false;
  form.evs[field] = normalized;
  return true;
}

/**
 * 处理 EV 输入控件变化，并在非法时回写旧值。
 *
 * @param field 被编辑的能力字段。
 * @param event range 或 number input 的原生事件。
 */
function handleEvInput(field: keyof StatSpread, event: Event): void {
  const target = event.target as HTMLInputElement;
  if (!setEv(field, Number(target.value))) {
    target.value = String(form.evs[field]);
  }
}

/** 设置某项 IV，拒绝 0..31 之外的值。 */
function setIv(field: keyof StatSpread, value: number): void {
  const normalized = Math.trunc(value);
  if (!Number.isFinite(normalized) || normalized < 0 || normalized > 31) return;
  form.ivs[field] = normalized;
}

/** 将个体值恢复为六项 31。 */
function resetIvs(): void {
  form.ivs = { ...PERFECT_IVS };
}

/**
 * 长按拖拽手柄后进入排序模式。
 *
 * @param config 被拖拽的配置。
 * @param index 该配置在可见列表中的当前位置。
 * @param event pointerdown 原生事件，用于阻止按钮点击。
 */
function beginDragPress(config: StatConfiguration, index: number, event: PointerEvent): void {
  if (config.hidden) return;
  event.preventDefault();
  window.clearTimeout(dragPressTimer);
  draggingConfigId.value = null;
  draggingDirty.value = false;
  draggingIndex.value = index;
  dragPressTimer = window.setTimeout(() => {
    draggingConfigId.value = config.id;
  }, 280);
}

/**
 * 拖拽经过另一条配置时即时调整本地顺序。
 *
 * @param targetIndex 鼠标当前经过的可见配置位置。
 */
function enterDragTarget(targetIndex: number): void {
  if (draggingConfigId.value === null || draggingIndex.value === null) return;
  if (targetIndex === draggingIndex.value) return;
  reorderVisibleConfigurations(draggingIndex.value, targetIndex);
  draggingIndex.value = targetIndex;
  draggingDirty.value = true;
}

/** 鼠标释放后保存拖拽排序；短按释放只会取消计时器。 */
async function finishDrag(): Promise<void> {
  window.clearTimeout(dragPressTimer);
  if (draggingConfigId.value !== null && draggingDirty.value) {
    try {
      await saveCurrentVisibleOrder();
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : '排序保存失败';
    }
  }
  clearDragState();
}

/** 清空拖拽相关状态。 */
function clearDragState(): void {
  window.clearTimeout(dragPressTimer);
  draggingConfigId.value = null;
  draggingDirty.value = false;
  draggingIndex.value = null;
}

/**
 * 在保持不可见配置原位的前提下调整可见配置顺序。
 *
 * @param fromIndex 拖拽源在可见配置列表里的索引。
 * @param toIndex 目标在可见配置列表里的索引。
 */
function reorderVisibleConfigurations(fromIndex: number, toIndex: number): void {
  const visible = [...visibleConfigurations.value];
  const [moved] = visible.splice(fromIndex, 1);
  if (moved === undefined) return;
  visible.splice(toIndex, 0, moved);
  const visibleQueue = [...visible];
  configurations.value = configurations.value.map((config) => {
    if (config.hidden) return config;
    return visibleQueue.shift() ?? config;
  });
}

/** 保存当前左侧可见配置的顺序。 */
async function saveCurrentVisibleOrder(): Promise<void> {
  await saveStatConfigurationOrder({
    role: props.role,
    references: visibleConfigurations.value.map((item) => ({ source: item.source, key: item.key })),
  });
  await refreshConfigurations();
}

/** 软删除已确认的自定义配置。 */
async function confirmDelete(): Promise<void> {
  if (deleteTarget.value === null) return;
  const target = deleteTarget.value;
  try {
    await deleteStatConfiguration(target.key);
    deleteTarget.value = null;
    await refreshConfigurations();
    ensureActiveManagerSelection();
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '删除配置失败';
  }
}

/** 返回性格的能力修正文案。 */
function natureLabel(natureId: string): string {
  const nature = natures.value.find((item) => item.identifier === natureId);
  if (!nature) return natureId;
  if (nature.increased_stat === null || nature.decreased_stat === null) {
    return `${nature.label} · 中性`;
  }
  return `${nature.label} · +${FIELD_LABELS[nature.increased_stat as keyof StatSpread]} / -${FIELD_LABELS[nature.decreased_stat as keyof StatSpread]}`;
}

/** 返回 EV/IV 简短摘要。 */
function spreadSummary(spread: StatSpread): string {
  return STAT_FIELDS
    .filter((field) => spread[field] > 0)
    .map((field) => `${FIELD_LABELS[field]} ${spread[field]}`)
    .join(' / ') || '0 投入';
}
</script>

<template>
  <section class="panel-block stat-config-picker">
    <div class="stat-config-picker__heading">
      <div>
        <div class="field-title">{{ title }}</div>
        <p v-if="selectedConfiguration" class="stat-config-picker__selected">
          当前：{{ selectedConfiguration.name }} · {{ natureLabel(selectedConfiguration.nature_id) }}
        </p>
      </div>
      <button type="button" class="secondary-button" :disabled="pokemonId === null" @click="openManager">
        管理配置
      </button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-else-if="loading" class="muted">配置加载中…</p>
    <div class="stat-config-picker__grid">
      <button
        v-for="config in topConfigurations"
        :key="config.id"
        type="button"
        class="preset-button"
        :class="{ active: config.snapshot_profile_id === modelValue }"
        @click="selectConfiguration(config)"
      >
        <span>{{ config.name }}</span>
        <small>{{ config.source === 'builtin' ? '内置' : '自定义' }} · {{ spreadSummary(config.evs) }}</small>
      </button>
    </div>

    <div v-if="manageOpen" class="stat-config-modal" role="dialog" aria-modal="true" @pointerup="finishDrag">
      <div class="stat-config-modal__panel stat-config-workbench">
        <header>
          <h3>{{ title }}管理</h3>
          <button type="button" class="icon-button" @click="closeManager">×</button>
        </header>

        <div class="stat-config-workbench__body">
          <aside class="stat-config-sidebar" aria-label="配置列表">
            <button
              type="button"
              class="stat-config-add-button"
              :disabled="pokemonId === null"
              aria-label="新增配置"
              title="新增配置"
              @click="openEditor()"
            >
              +
            </button>

            <button
              v-for="(config, index) in visibleConfigurations"
              :key="config.id"
              type="button"
              class="stat-config-sidebar-item"
              :class="{
                active: managerMode === 'view' && config.id === activeConfigId,
                dragging: config.id === draggingConfigId,
              }"
              @click="activateConfiguration(config)"
              @pointerenter="enterDragTarget(index)"
            >
              <span
                class="stat-config-drag-handle"
                aria-label="长按拖拽排序"
                title="长按拖拽排序"
                @click.stop
                @pointerdown.stop="beginDragPress(config, index, $event)"
              >
                ☰
              </span>
              <span class="stat-config-sidebar-item__copy">
                <strong>{{ config.name }}</strong>
                <small>{{ config.source === 'builtin' ? '预设' : '自定义' }} · {{ spreadSummary(config.evs) }}</small>
              </span>
            </button>
          </aside>

          <form class="stat-config-editor" @submit.prevent="saveEditor">
            <div class="stat-config-editor__heading">
              <div>
                <h4>{{ managerMode === 'create' ? '新增配置' : form.name }}</h4>
                <p v-if="managerMode !== 'create'" class="muted">
                  {{ activeConfiguration?.source === 'builtin' ? '预设配置，只能查看。' : '自定义配置，可直接修改后保存。' }}
                </p>
              </div>
              <div class="stat-config-editor__tools">
                <button
                  v-if="activeConfiguration?.deletable && managerMode === 'view'"
                  type="button"
                  class="secondary-button"
                  @click="deleteTarget = activeConfiguration"
                >
                  删除
                </button>
              </div>
            </div>

        <label>
          <span>配置名称</span>
          <input v-model="form.name" maxlength="48" :disabled="!activeCanEdit" />
        </label>
        <div class="stat-config-form-grid">
          <label>
            <span>适用 Pokémon</span>
            <select v-model="form.binding_kind" :disabled="!activeCanEdit">
              <option value="global">全部 Pokémon</option>
              <option value="pokemon" :disabled="pokemonId === null">当前 Pokémon</option>
            </select>
          </label>
          <label>
            <span>适用位置</span>
            <select v-model="form.role" :disabled="!activeCanEdit">
              <option value="attacker">仅攻方</option>
              <option value="defender">仅防守方</option>
              <option value="both">攻防双方</option>
            </select>
          </label>
          <label>
            <span>性格</span>
            <select v-model="form.nature_id" :disabled="!activeCanEdit">
              <option v-for="nature in natures" :key="nature.identifier" :value="nature.identifier">
                {{ natureLabel(nature.identifier) }}
              </option>
            </select>
          </label>
        </div>

        <section>
          <div class="stat-config-budget">
            <strong>EV {{ evTotal }} / 510</strong>
            <span>剩余 {{ evRemaining }}</span>
          </div>
          <label v-for="field in STAT_FIELDS" :key="field" class="stat-config-stat-row">
            <span>{{ FIELD_LABELS[field] }}</span>
            <input
              type="range"
              min="0"
              max="252"
              :value="form.evs[field]"
              :disabled="!activeCanEdit"
              @input="handleEvInput(field, $event)"
            />
            <input
              type="number"
              min="0"
              max="252"
              :value="form.evs[field]"
              :disabled="!activeCanEdit"
              @change="handleEvInput(field, $event)"
            />
          </label>
        </section>

        <section class="stat-config-iv-section">
          <button type="button" class="secondary-button" @click="showIvs = !showIvs">
            {{ showIvs ? '收起个体值' : '显示个体值' }}
          </button>
          <button v-if="showIvs && activeCanEdit" type="button" class="secondary-button" @click="resetIvs">恢复全部 31</button>
          <div v-if="showIvs" class="stat-config-form-grid">
            <label v-for="field in STAT_FIELDS" :key="field">
              <span>{{ FIELD_LABELS[field] }} IV</span>
              <input
                type="number"
                min="0"
                max="31"
                :value="form.ivs[field]"
                :disabled="!activeCanEdit"
                @change="setIv(field, Number(($event.target as HTMLInputElement).value))"
              />
            </label>
          </div>
        </section>
        <ul v-if="formErrors.length" class="battle-validation-list">
          <li v-for="message in formErrors" :key="message">{{ message }}</li>
        </ul>
        <footer>
          <button v-if="managerMode === 'create'" type="button" class="secondary-button" @click="ensureActiveManagerSelection">取消</button>
          <button v-if="activeCanEdit" type="submit" class="primary-button" :disabled="!canSave">
            {{ saving ? '保存中' : '保存配置' }}
          </button>
        </footer>
      </form>
        </div>
      </div>
    </div>

    <div v-if="deleteTarget" class="stat-config-modal" role="dialog" aria-modal="true">
      <article class="stat-config-modal__panel">
        <header><h3>删除配置</h3></header>
        <p>删除“{{ deleteTarget.name }}”后，当前页面会回退到第一条可见配置。历史任务已保存快照，不会丢失解释。</p>
        <footer>
          <button type="button" class="secondary-button" @click="deleteTarget = null">取消</button>
          <button type="button" class="primary-button" @click="confirmDelete">确认删除</button>
        </footer>
      </article>
    </div>
  </section>
</template>

<style scoped>
.stat-config-picker { display: grid; gap: 10px; }
.stat-config-picker__heading,
.stat-config-modal__panel header,
.stat-config-modal__panel footer,
.stat-config-budget,
.stat-config-editor__heading,
.stat-config-editor__tools {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: space-between;
}
.stat-config-picker__selected { margin: 4px 0 0; }
.stat-config-picker__grid { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(132px, 1fr)); }
.stat-config-modal {
  align-items: center;
  background: rgba(12, 18, 32, 0.42);
  display: flex;
  inset: 0;
  justify-content: center;
  padding: 16px;
  position: fixed;
  z-index: 20;
}
.stat-config-modal__panel {
  background: #fff;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  display: grid;
  gap: 14px;
  max-height: min(86vh, 760px);
  overflow: auto;
  padding: 16px;
  width: min(760px, 100%);
}
.stat-config-workbench {
  width: min(980px, 100%);
}
.stat-config-modal__panel h3 { margin: 0; }
.stat-config-workbench__body {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: 16px;
  min-height: min(620px, calc(86vh - 88px));
}
.stat-config-sidebar {
  align-content: start;
  display: grid;
  gap: 8px;
}
.stat-config-add-button,
.stat-config-sidebar-item {
  width: 100%;
  border: 1px solid #dce4d8;
  border-radius: 6px;
  background: #fff;
  color: #17201b;
}
.stat-config-add-button {
  display: grid;
  place-items: center;
  min-height: 46px;
  color: #286b52;
  font-size: 26px;
  font-weight: 800;
  line-height: 1;
}
.stat-config-sidebar-item {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-height: 58px;
  padding: 8px;
  text-align: left;
}
.stat-config-sidebar-item.active {
  border-color: #286b52;
  background: #e6f1eb;
}
.stat-config-sidebar-item.dragging {
  border-style: dashed;
  box-shadow: 0 6px 16px rgba(23, 32, 27, 0.12);
}
.stat-config-drag-handle {
  display: grid;
  place-items: center;
  width: 28px;
  height: 36px;
  border: 1px solid #bdc9c0;
  border-radius: 6px;
  color: #325545;
  cursor: grab;
  user-select: none;
}
.stat-config-sidebar-item__copy {
  display: grid;
  min-width: 0;
  gap: 3px;
}
.stat-config-sidebar-item__copy strong,
.stat-config-sidebar-item__copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stat-config-sidebar-item__copy small {
  color: #65736b;
}
.stat-config-editor {
  align-content: start;
  display: grid;
  gap: 14px;
  min-width: 0;
}
.stat-config-editor__heading {
  align-items: flex-start;
}
.stat-config-editor__heading h4,
.stat-config-editor__heading p {
  margin: 0;
}
.stat-config-editor__heading p {
  margin-top: 4px;
}
.stat-config-editor__tools {
  justify-content: flex-end;
}
.stat-config-form-grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
.stat-config-modal label { display: grid; gap: 5px; }
.stat-config-modal input,
.stat-config-modal select { min-height: 34px; }
.stat-config-stat-row { align-items: center; grid-template-columns: 76px minmax(240px, 1fr) 76px; }
.stat-config-stat-row input[type="range"] { width: 100%; }
.stat-config-iv-section { display: grid; gap: 10px; }
@media (max-width: 760px) {
  .stat-config-workbench__body { grid-template-columns: 1fr; }
  .stat-config-sidebar { grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
}
@media (max-width: 560px) {
  .stat-config-stat-row { grid-template-columns: 1fr; }
}
</style>
