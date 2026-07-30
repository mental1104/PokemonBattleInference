<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  createStatConfiguration,
  deleteStatConfiguration,
  listNatures,
  listStatConfigurations,
  saveStatConfigurationOrder,
  setStatConfigurationHidden,
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
const editorOpen = ref(false);
const detailConfig = ref<StatConfiguration | null>(null);
const deleteTarget = ref<StatConfiguration | null>(null);
const editingConfig = ref<StatConfiguration | null>(null);
const showIvs = ref(false);

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
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '配置列表加载失败';
  } finally {
    loading.value = false;
  }
}

/** 当前选择隐藏、删除或因 Pokémon 切换失效时回退到第一条可见配置。 */
function ensureValidSelection(): void {
  const current = configurations.value.find(
    (item) => item.snapshot_profile_id === props.modelValue && !item.hidden,
  );
  if (current !== undefined) return;
  const fallback = visibleConfigurations.value[0] ?? null;
  if (fallback !== null) emit('update:modelValue', fallback.snapshot_profile_id);
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

/**
 * 打开新建或编辑表单。
 *
 * @param config 被编辑的自定义配置；省略表示新建。
 */
function openEditor(config?: StatConfiguration): void {
  editingConfig.value = config ?? null;
  showIvs.value = false;
  const source = config ?? null;
  form.name = source?.name ?? `${props.pokemonName ?? '通用'}配置`;
  form.nature_id = source?.nature_id ?? 'hardy';
  form.evs = { ...(source?.evs ?? EMPTY_EVS) };
  form.ivs = { ...(source?.ivs ?? PERFECT_IVS) };
  form.role = source?.role ?? props.role;
  form.binding_kind = source?.binding_kind ?? 'global';
  form.pokemon_id = source?.binding_kind === 'pokemon' ? source.pokemon_id : null;
  editorOpen.value = true;
}

/** 保存新建或编辑配置，成功后刷新列表并选中新快照。 */
async function saveEditor(): Promise<void> {
  if (!canSave.value) return;
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
    const saved = editingConfig.value === null
      ? await createStatConfiguration(request)
      : await updateStatConfiguration(editingConfig.value.key, request);
    editorOpen.value = false;
    await refreshConfigurations();
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

/** 隐藏或恢复配置，并在当前选择失效后回退。 */
async function toggleHidden(config: StatConfiguration, hidden: boolean): Promise<void> {
  error.value = null;
  try {
    await setStatConfigurationHidden({
      role: props.role,
      source: config.source,
      key: config.key,
      hidden,
    });
    await refreshConfigurations();
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '显示偏好保存失败';
  }
}

/** 上移或下移配置并批量保存排序。 */
async function moveConfig(config: StatConfiguration, direction: -1 | 1): Promise<void> {
  const list = [...visibleConfigurations.value];
  const index = list.findIndex((item) => item.id === config.id);
  const nextIndex = index + direction;
  if (index < 0 || nextIndex < 0 || nextIndex >= list.length) return;
  [list[index], list[nextIndex]] = [list[nextIndex], list[index]];
  try {
    await saveStatConfigurationOrder({
      role: props.role,
      references: list.map((item) => ({ source: item.source, key: item.key })),
    });
    await refreshConfigurations();
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : '排序保存失败';
  }
}

/** 软删除已确认的自定义配置。 */
async function confirmDelete(): Promise<void> {
  if (deleteTarget.value === null) return;
  const target = deleteTarget.value;
  try {
    await deleteStatConfiguration(target.key);
    deleteTarget.value = null;
    await refreshConfigurations();
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
      <button type="button" class="secondary-button" :disabled="pokemonId === null" @click="manageOpen = true">
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
      <button type="button" class="preset-button" :disabled="pokemonId === null" @click="openEditor()">
        <span>新建配置</span>
        <small>{{ role === 'attacker' ? '默认攻击方' : '默认防守方' }}</small>
      </button>
    </div>

    <div v-if="manageOpen" class="stat-config-modal" role="dialog" aria-modal="true">
      <div class="stat-config-modal__panel">
        <header>
          <h3>{{ title }}管理</h3>
          <button type="button" class="icon-button" @click="manageOpen = false">×</button>
        </header>
        <div class="stat-config-modal__actions">
          <button type="button" class="secondary-button" @click="openEditor()">新建配置</button>
        </div>
        <article v-for="config in configurations" :key="config.id" class="stat-config-row" :class="{ hidden: config.hidden }">
          <button type="button" class="stat-config-row__main" @click="selectConfiguration(config)">
            <strong>{{ config.name }}</strong>
            <span>{{ config.source === 'builtin' ? '系统内置' : '租户自定义' }} · {{ natureLabel(config.nature_id) }}</span>
            <small>{{ config.binding_kind === 'global' ? '全部 Pokémon' : `仅 ${pokemonName ?? config.pokemon_id}` }} · {{ spreadSummary(config.evs) }}</small>
          </button>
          <div class="stat-config-row__tools">
            <button type="button" @click="detailConfig = config">详情</button>
            <button type="button" :disabled="config.hidden" @click="moveConfig(config, -1)">上移</button>
            <button type="button" :disabled="config.hidden" @click="moveConfig(config, 1)">下移</button>
            <button v-if="config.hideable && !config.hidden" type="button" @click="toggleHidden(config, true)">隐藏</button>
            <button v-if="config.hideable && config.hidden" type="button" @click="toggleHidden(config, false)">恢复</button>
            <button v-if="config.editable" type="button" @click="openEditor(config)">编辑</button>
            <button v-if="config.deletable" type="button" @click="deleteTarget = config">删除</button>
          </div>
        </article>
      </div>
    </div>

    <div v-if="editorOpen" class="stat-config-modal" role="dialog" aria-modal="true">
      <form class="stat-config-modal__panel" @submit.prevent="saveEditor">
        <header>
          <h3>{{ editingConfig ? '编辑配置' : '新建配置' }}</h3>
          <button type="button" class="icon-button" @click="editorOpen = false">×</button>
        </header>
        <label>
          <span>配置名称</span>
          <input v-model="form.name" maxlength="48" />
        </label>
        <div class="stat-config-form-grid">
          <label>
            <span>适用 Pokémon</span>
            <select v-model="form.binding_kind">
              <option value="global">全部 Pokémon</option>
              <option value="pokemon" :disabled="pokemonId === null">当前 Pokémon</option>
            </select>
          </label>
          <label>
            <span>适用位置</span>
            <select v-model="form.role">
              <option value="attacker">仅攻方</option>
              <option value="defender">仅防守方</option>
              <option value="both">攻防双方</option>
            </select>
          </label>
          <label>
            <span>性格</span>
            <select v-model="form.nature_id">
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
              @input="handleEvInput(field, $event)"
            />
            <input
              type="number"
              min="0"
              max="252"
              :value="form.evs[field]"
              @change="handleEvInput(field, $event)"
            />
          </label>
        </section>

        <section class="stat-config-iv-section">
          <button type="button" class="secondary-button" @click="showIvs = !showIvs">
            {{ showIvs ? '收起个体值' : '高级设置 / 调整个体值' }}
          </button>
          <button v-if="showIvs" type="button" class="secondary-button" @click="resetIvs">恢复全部 31</button>
          <div v-if="showIvs" class="stat-config-form-grid">
            <label v-for="field in STAT_FIELDS" :key="field">
              <span>{{ FIELD_LABELS[field] }} IV</span>
              <input
                type="number"
                min="0"
                max="31"
                :value="form.ivs[field]"
                @change="setIv(field, Number(($event.target as HTMLInputElement).value))"
              />
            </label>
          </div>
        </section>
        <ul v-if="formErrors.length" class="battle-validation-list">
          <li v-for="message in formErrors" :key="message">{{ message }}</li>
        </ul>
        <footer>
          <button type="button" class="secondary-button" @click="editorOpen = false">取消</button>
          <button type="submit" class="primary-button" :disabled="!canSave">{{ saving ? '保存中' : '保存' }}</button>
        </footer>
      </form>
    </div>

    <div v-if="detailConfig" class="stat-config-modal" role="dialog" aria-modal="true">
      <article class="stat-config-modal__panel">
        <header>
          <h3>{{ detailConfig.name }}</h3>
          <button type="button" class="icon-button" @click="detailConfig = null">×</button>
        </header>
        <dl class="stat-config-detail">
          <dt>来源</dt><dd>{{ detailConfig.source === 'builtin' ? '系统内置' : '租户自定义' }}</dd>
          <dt>适用范围</dt><dd>{{ detailConfig.binding_kind === 'global' ? '全部 Pokémon' : `当前 Pokémon #${detailConfig.pokemon_id}` }}</dd>
          <dt>适用位置</dt><dd>{{ detailConfig.role }}</dd>
          <dt>性格</dt><dd>{{ natureLabel(detailConfig.nature_id) }}</dd>
          <dt>EV</dt><dd>{{ spreadSummary(detailConfig.evs) }}</dd>
          <dt>IV</dt><dd>{{ spreadSummary(detailConfig.ivs) }}</dd>
          <dt>说明</dt><dd>{{ detailConfig.description }}</dd>
        </dl>
      </article>
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
.stat-config-modal__actions,
.stat-config-budget,
.stat-config-row__tools {
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
.stat-config-modal__panel h3 { margin: 0; }
.stat-config-form-grid { display: grid; gap: 10px; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
.stat-config-modal label { display: grid; gap: 5px; }
.stat-config-modal input,
.stat-config-modal select { min-height: 34px; }
.stat-config-stat-row { align-items: center; grid-template-columns: 76px minmax(240px, 1fr) 76px; }
.stat-config-stat-row input[type="range"] { width: 100%; }
.stat-config-row {
  border: 1px solid #d8dee8;
  border-radius: 8px;
  display: grid;
  gap: 8px;
  padding: 10px;
}
.stat-config-row.hidden { opacity: 0.64; }
.stat-config-row__main {
  background: transparent;
  border: 0;
  display: grid;
  gap: 3px;
  padding: 0;
  text-align: left;
}
.stat-config-row__tools { justify-content: flex-start; }
.stat-config-detail { display: grid; gap: 8px; grid-template-columns: 110px 1fr; }
.stat-config-iv-section { display: grid; gap: 10px; }
@media (max-width: 560px) {
  .stat-config-stat-row { grid-template-columns: 1fr; }
  .stat-config-detail { grid-template-columns: 1fr; }
}
</style>
