<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import type { PokemonSearchItem } from '../api/calculator';
import PokemonSelector from './PokemonSelector.vue';
import PokemonSummaryCard from './PokemonSummaryCard.vue';
import StatConfigurationPicker from './StatConfigurationPicker.vue';
import {
  useConfigurationSolver,
  type EditableSpeedGoal,
} from '../composables/useConfigurationSolver';
import { useRecentPokemon } from '../composables/useRecentPokemon';

const solver = useConfigurationSolver();
const { items: recentPokemon, remember: rememberPokemon } = useRecentPokemon();
const teleportReady = ref(false);
const dialogOpen = ref(false);
const dialogMode = ref<'create' | 'edit'>('create');
const dialogDraft = ref<EditableSpeedGoal | null>(null);

const dialogCanSave = computed(() => (
  dialogDraft.value !== null
  && solver.isSpeedGoalComplete(dialogDraft.value)
  && !dialogDraft.value.targetLoading
));

const dialogTitle = computed(() => (
  dialogMode.value === 'create' ? '添加速度目标' : '编辑速度目标'
));

/** 确认主求解页面已经渲染目标网格后再启用 Teleport。 */
onMounted(() => {
  teleportReady.value = document.querySelector('.goal-columns') !== null;
});

/** 打开一条与已选列表隔离的新速度目标草稿。 */
function openCreateDialog(): void {
  dialogMode.value = 'create';
  dialogDraft.value = solver.createSpeedGoalDraft();
  dialogOpen.value = true;
}

/**
 * 打开已保存速度目标的编辑副本。
 *
 * @param goal 用户准备查看或修改的目标快照。
 */
function openEditDialog(goal: EditableSpeedGoal): void {
  dialogMode.value = 'edit';
  dialogDraft.value = solver.cloneSpeedGoal(goal);
  dialogOpen.value = true;
}

/** 关闭弹窗并丢弃尚未保存的速度目标草稿。 */
function closeDialog(): void {
  dialogOpen.value = false;
  dialogDraft.value = null;
}

/**
 * 为当前草稿加载作为速度线参照的 Pokémon。
 *
 * @param pokemon 用户从搜索结果选择的目标 Pokémon。
 */
async function selectTarget(pokemon: PokemonSearchItem): Promise<void> {
  const draft = dialogDraft.value;
  if (draft === null) return;
  const loaded = await solver.selectSpeedGoalTarget(draft, pokemon);
  if (loaded) rememberPokemon(pokemon);
}

/**
 * 更新参照 Pokémon 使用的配置快照。
 *
 * @param presetId 配置选择器返回的不可变 snapshot profile id。
 */
function selectTargetPreset(presetId: string): void {
  if (dialogDraft.value !== null) dialogDraft.value.targetPreset = presetId;
}

/** 保存完整草稿，并在成功后关闭弹窗。 */
function confirmDialog(): void {
  const draft = dialogDraft.value;
  if (draft === null || !solver.saveSpeedGoalDraft(draft)) return;
  closeDialog();
}

/**
 * 返回紧凑速度目标卡片使用的配置名称。
 *
 * @param goal 已保存的速度目标。
 * @returns 能匹配旧模板时返回本地化名称，否则返回“自定义配置”。
 */
function presetName(goal: EditableSpeedGoal): string {
  return solver.statPresets.value.find((preset) => preset.key === goal.targetPreset)?.label
    ?? (goal.targetPreset.startsWith('preset-snapshot:') ? '自定义配置' : goal.targetPreset);
}
</script>

<template>
  <Teleport v-if="teleportReady" to=".goal-columns">
    <section class="goal-column speed-goal-column" aria-labelledby="speed-goals-title">
      <header class="goal-column__heading">
        <div>
          <h3 id="speed-goals-title">速度目标</h3>
          <small>待配置 Pokémon 的实际 Speed 严格超过目标配置</small>
        </div>
        <button
          type="button"
          class="secondary-button"
          data-testid="open-speed-goal-dialog"
          @click="openCreateDialog"
        >
          添加速度目标
        </button>
      </header>

      <p v-if="solver.speedGoals.value.length === 0" class="goal-empty">
        暂无速度目标，可按需添加。
      </p>

      <article
        v-for="goal in solver.speedGoals.value"
        :key="goal.id"
        class="goal-summary-row"
        data-testid="speed-goal-summary-row"
      >
        <button
          type="button"
          class="goal-summary-row__main"
          :aria-label="`查看并编辑速度目标 ${goal.target?.display_name ?? ''}`"
          @click="openEditDialog(goal)"
        >
          <img
            v-if="goal.target?.sprite_url"
            class="goal-summary-row__sprite"
            :src="goal.target.sprite_url"
            :alt="goal.target.display_name"
          />
          <span class="goal-summary-row__body">
            <span class="goal-summary-row__title">
              {{ goal.target?.display_name }}
              <small>{{ goal.target?.identifier }}</small>
            </span>
            <span class="goal-summary-row__primary">严格超过目标速度</span>
            <span class="goal-summary-row__meta">{{ presetName(goal) }}</span>
          </span>
          <span class="goal-summary-row__edit">查看 / 编辑</span>
        </button>
        <button
          type="button"
          class="icon-button goal-summary-row__delete"
          aria-label="删除速度目标"
          @click="solver.removeSpeedGoal(goal.id)"
        >
          ×
        </button>
      </article>

      <div v-if="solver.visibleSpeedEvidence.value.length > 0" class="speed-evidence-list">
        <article
          v-for="goal in solver.visibleSpeedEvidence.value"
          :key="goal.goal_id"
          class="speed-evidence-row"
          :class="{ failed: !goal.satisfied }"
        >
          <strong>{{ goal.satisfied ? '满足' : '未满足' }} · {{ goal.target.display_name }}</strong>
          <span>己方 Speed {{ goal.subject_speed }} / 目标 Speed {{ goal.target_speed }}</span>
          <small>
            {{ goal.speed_margin > 0 ? `快 ${goal.speed_margin} 点` : `差 ${Math.abs(goal.speed_margin) + 1} 点才能严格超过` }}
          </small>
        </article>
      </div>
    </section>
  </Teleport>

  <Teleport v-if="dialogOpen && dialogDraft" to="body">
    <div
      class="speed-goal-dialog-backdrop"
      data-testid="speed-goal-dialog-backdrop"
      @click.self="closeDialog"
    >
      <section
        class="speed-goal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="speed-goal-dialog-title"
        tabindex="-1"
        @keydown.esc.prevent="closeDialog"
      >
        <header class="speed-goal-dialog__header">
          <div>
            <h2 id="speed-goal-dialog-title">{{ dialogTitle }}</h2>
            <p>选择参照 Pokémon 和它的配置；同速不算超过。</p>
          </div>
          <button type="button" class="icon-button" aria-label="关闭速度目标弹窗" @click="closeDialog">
            ×
          </button>
        </header>

        <div class="speed-goal-dialog__content">
          <section>
            <PokemonSelector
              title="选择速度参照 Pokémon"
              :ruleset-id="solver.rulesetId.value"
              :selected="dialogDraft.target"
              :recent-pokemon="recentPokemon"
              @select="selectTarget"
            />
            <p v-if="dialogDraft.targetLoading" class="muted">正在加载 Pokémon 资料</p>
            <PokemonSummaryCard :pokemon="dialogDraft.target" />
          </section>

          <StatConfigurationPicker
            title="目标速度配置"
            role="attacker"
            :pokemon-id="dialogDraft.target?.pokemon_id ?? null"
            :pokemon-name="dialogDraft.target?.display_name ?? null"
            :model-value="dialogDraft.targetPreset"
            @update:model-value="selectTargetPreset"
          />
        </div>

        <p class="speed-goal-dialog__note">
          当前比较等级与页面一致，只比较配置计算出的实际 Speed；暂不计入速度等级、天气、特性或道具速度修正。
        </p>
        <p v-if="solver.error.value" class="error">{{ solver.error.value }}</p>

        <footer class="speed-goal-dialog__footer">
          <span class="muted">
            {{ dialogCanSave ? '参数已完整，可以保存。' : '请选择参照 Pokémon 和配置。' }}
          </span>
          <div>
            <button type="button" class="secondary-button" @click="closeDialog">取消</button>
            <button
              type="button"
              class="primary-button"
              data-testid="confirm-speed-goal-dialog"
              :disabled="!dialogCanSave"
              @click="confirmDialog"
            >
              {{ dialogMode === 'create' ? '添加目标' : '保存修改' }}
            </button>
          </div>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style>
.goal-columns {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.speed-goal-column .goal-summary-row__primary {
  color: #315c49;
  font-weight: 700;
}

.speed-evidence-list {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.speed-evidence-row {
  border: 1px solid #cbd8cf;
  border-radius: 8px;
  display: grid;
  gap: 3px;
  padding: 10px;
}

.speed-evidence-row.failed {
  border-color: #b42318;
}

.speed-evidence-row span,
.speed-evidence-row small {
  color: #5f6d64;
}

.speed-goal-dialog-backdrop {
  align-items: center;
  background: rgba(23, 32, 27, 0.55);
  display: flex;
  inset: 0;
  justify-content: center;
  padding: 20px;
  position: fixed;
  z-index: 80;
}

.speed-goal-dialog {
  background: #fff;
  border: 1px solid #bdc9c0;
  border-radius: 14px;
  box-shadow: 0 24px 72px rgba(23, 32, 27, 0.3);
  max-height: calc(100vh - 40px);
  overflow: auto;
  padding: 18px;
  width: min(860px, 100%);
}

.speed-goal-dialog__header,
.speed-goal-dialog__footer,
.speed-goal-dialog__footer > div {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.speed-goal-dialog__header {
  border-bottom: 1px solid #e2e8e2;
  padding-bottom: 14px;
}

.speed-goal-dialog__header h2,
.speed-goal-dialog__header p {
  margin: 0;
}

.speed-goal-dialog__header p {
  color: #5f6d64;
  margin-top: 4px;
}

.speed-goal-dialog__content {
  align-items: start;
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
  margin-top: 16px;
}

.speed-goal-dialog__content > section {
  display: grid;
  gap: 12px;
}

.speed-goal-dialog__note {
  background: #f3f8f4;
  border-radius: 8px;
  color: #5f6d64;
  margin: 14px 0 0;
  padding: 10px 12px;
}

.speed-goal-dialog__footer {
  border-top: 1px solid #e2e8e2;
  margin-top: 16px;
  padding-top: 14px;
}

@media (max-width: 1180px) {
  .goal-columns,
  .speed-goal-dialog__content {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .speed-goal-dialog-backdrop {
    padding: 10px;
  }

  .speed-goal-dialog {
    max-height: calc(100vh - 20px);
    padding: 12px;
  }

  .speed-goal-dialog__footer {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
