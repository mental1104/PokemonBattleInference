<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import type { PokemonSearchItem } from '../api/calculator';
import type { ConfigurationGoalKind } from '../api/configurationSolver';
import AbilitySelector from '../components/AbilitySelector.vue';
import ItemSelector from '../components/ItemSelector.vue';
import MoveSelector from '../components/MoveSelector.vue';
import PokemonSelector from '../components/PokemonSelector.vue';
import PokemonSummaryCard from '../components/PokemonSummaryCard.vue';
import StatConfigurationPicker from '../components/StatConfigurationPicker.vue';
import { useConfigurationSolver, type EditableSolverGoal } from '../composables/useConfigurationSolver';
import { useRecentPokemon } from '../composables/useRecentPokemon';

type GoalDialogMode = 'create' | 'replace';

const solver = useConfigurationSolver();
const { items: recentPokemon, remember: rememberPokemon } = useRecentPokemon();
const attackGoals = computed(() => solver.goals.value.filter((goal) => goal.kind === 'attack'));
const defenseGoals = computed(() => solver.goals.value.filter((goal) => goal.kind === 'defense'));
const goalDialogOpen = ref(false);
const goalDialogMode = ref<GoalDialogMode>('create');
const goalDialogKind = ref<ConfigurationGoalKind>('attack');
const goalDialogGoalId = ref<string | null>(null);
const goalDialogPokemon = ref<PokemonSearchItem | null>(null);
const goalDialogSubmitting = ref(false);

const goalDialogTitle = computed(() => {
  const action = goalDialogMode.value === 'create' ? '添加' : '更换';
  return `${action}${goalDialogKind.value === 'attack' ? '攻目标' : '防目标'}`;
});
const goalDialogPokemonTitle = computed(() => (
  goalDialogKind.value === 'attack' ? '选择防守目标' : '选择攻击来源'
));

/** 初始化配置模板与战斗道具目录。 */
onMounted(() => {
  void Promise.all([solver.loadPresets(), solver.loadItems()]);
});

/**
 * 选择待配置 Pokémon，并写入最近选择。
 *
 * @param pokemon 用户选中的 Pokémon。
 */
async function selectSubject(pokemon: PokemonSearchItem): Promise<void> {
  rememberPokemon(pokemon);
  await solver.selectSubject(pokemon);
}

/**
 * 打开新增目标弹窗；已选目标列表在确认前保持不变。
 *
 * @param kind attack 表示新增防守对象，defense 表示新增攻击来源。
 */
function openAddGoalDialog(kind: ConfigurationGoalKind): void {
  goalDialogMode.value = 'create';
  goalDialogKind.value = kind;
  goalDialogGoalId.value = null;
  goalDialogPokemon.value = null;
  goalDialogOpen.value = true;
}

/**
 * 打开更换目标弹窗，并以当前 Pokémon 作为初始选择。
 *
 * @param goal 用户准备更换 Pokémon 的已选目标。
 */
function openReplaceGoalDialog(goal: EditableSolverGoal): void {
  goalDialogMode.value = 'replace';
  goalDialogKind.value = goal.kind;
  goalDialogGoalId.value = goal.id;
  goalDialogPokemon.value = goal.target;
  goalDialogOpen.value = true;
}

/**
 * 保存弹窗中的临时 Pokémon 选择，不立即修改已选目标列表。
 *
 * @param pokemon 用户在新增或更换弹窗中点选的 Pokémon。
 */
function selectGoalDialogPokemon(pokemon: PokemonSearchItem): void {
  goalDialogPokemon.value = pokemon;
}

/** 关闭目标选择弹窗，并丢弃尚未确认的临时选择。 */
function closeGoalDialog(): void {
  if (goalDialogSubmitting.value) return;
  goalDialogOpen.value = false;
  goalDialogGoalId.value = null;
  goalDialogPokemon.value = null;
}

/**
 * 确认弹窗选择，并在资料加载成功后新增或更换目标。
 *
 * 新增模式只有在目标详情和合法特性加载完成后才写入列表；更换模式则更新对应已选目标，
 * 从而让列表始终只展示已经确认的对象。
 */
async function confirmGoalDialog(): Promise<void> {
  const pokemon = goalDialogPokemon.value;
  if (!pokemon || goalDialogSubmitting.value) return;

  goalDialogSubmitting.value = true;
  try {
    if (goalDialogMode.value === 'create') {
      const created = await solver.addGoalWithTarget(goalDialogKind.value, pokemon);
      if (created === null) return;
    } else {
      const goal = solver.goals.value.find((item) => item.id === goalDialogGoalId.value);
      if (!goal || !(await solver.selectGoalTarget(goal, pokemon))) return;
    }

    rememberPokemon(pokemon);
    goalDialogOpen.value = false;
    goalDialogGoalId.value = null;
    goalDialogPokemon.value = null;
  } finally {
    goalDialogSubmitting.value = false;
  }
}
</script>

<template>
  <main class="app-shell solver-shell">
    <header class="topbar">
      <div>
        <h1>配置反向求解</h1>
        <p>Champion · 多目标 · Lv.{{ solver.level.value }}</p>
      </div>
      <div class="state-pill">{{ solver.result.value?.reachable ? 'REACHABLE' : 'TARGETS' }}</div>
    </header>

    <section class="solver-layout">
      <aside class="solver-side">
        <PokemonSelector
          title="待配置 Pokémon"
          :ruleset-id="solver.rulesetId.value"
          :selected="solver.subject.value"
          :recent-pokemon="recentPokemon"
          @select="selectSubject"
        />
        <PokemonSummaryCard :pokemon="solver.subject.value" />

        <ItemSelector
          title="待配置 Pokémon 道具"
          :items="solver.itemOptions.value"
          :selected-identifier="solver.subjectItemIdentifier.value"
          :disabled="!solver.subject.value"
          :loading="solver.itemsLoading.value"
          @select="solver.subjectItemIdentifier.value = $event.identifier"
        />
        <AbilitySelector
          title="待配置 Pokémon 特性"
          :abilities="solver.subjectAbilityOptions.value"
          :selected-identifier="solver.subjectAbilityIdentifier.value"
          :disabled="!solver.subject.value"
          :loading="solver.subjectAbilitiesLoading.value"
          @select="solver.subjectAbilityIdentifier.value = $event.identifier"
        />

        <StatConfigurationPicker
          title="搜索配置"
          role="attacker"
          :pokemon-id="solver.subject.value?.pokemon_id ?? null"
          :pokemon-name="solver.subject.value?.display_name ?? null"
          :model-value="solver.selectedPresetKeys.value[0] ?? ''"
          @update:model-value="solver.selectedPresetKeys.value = [$event]"
        />
      </aside>

      <section class="solver-main">
        <div class="solver-panel">
          <div class="panel-heading">
            <div>
              <h2>攻防目标</h2>
              <p class="muted">新增时先在弹窗中选择 Pokémon，列表只展示已经确认的目标。</p>
            </div>
          </div>

          <div class="goal-columns">
            <section class="goal-column" aria-labelledby="attack-goals-title">
              <header class="goal-column__heading">
                <div>
                  <h3 id="attack-goals-title">攻目标</h3>
                  <small>待配置 Pokémon 在指定次数内击倒目标</small>
                </div>
                <button
                  type="button"
                  class="secondary-button"
                  data-testid="open-attack-goal-dialog"
                  @click="openAddGoalDialog('attack')"
                >
                  添加攻目标
                </button>
              </header>

              <p v-if="attackGoals.length === 0" class="goal-empty">
                暂无攻目标，可按需添加。
              </p>

              <article v-for="goal in attackGoals" :key="goal.id" class="goal-editor">
                <div class="goal-toolbar">
                  <select v-model="goal.rollPolicy" aria-label="随机伤害档">
                    <option value="min">最低伤害档</option>
                    <option value="max">最高伤害档</option>
                  </select>
                  <label>
                    次数
                    <input v-model.number="goal.repetitions" type="number" min="1" max="10" />
                  </label>
                  <button
                    type="button"
                    class="icon-button"
                    aria-label="删除攻目标"
                    @click="solver.removeGoal(goal.id)"
                  >
                    ×
                  </button>
                </div>

                <div class="goal-target-heading">
                  <strong>防守目标</strong>
                  <button
                    type="button"
                    class="text-button"
                    @click="openReplaceGoalDialog(goal)"
                  >
                    更换
                  </button>
                </div>
                <PokemonSummaryCard :pokemon="goal.target" />

                <div class="goal-mechanics">
                  <ItemSelector
                    title="防守方道具"
                    :items="solver.itemOptions.value"
                    :selected-identifier="goal.targetItemIdentifier"
                    :disabled="!goal.target"
                    :loading="solver.itemsLoading.value"
                    @select="goal.targetItemIdentifier = $event.identifier"
                  />
                  <AbilitySelector
                    title="防守方特性"
                    :abilities="goal.targetAbilityOptions"
                    :selected-identifier="goal.targetAbilityIdentifier"
                    :disabled="!goal.target"
                    :loading="goal.targetAbilitiesLoading"
                    @select="goal.targetAbilityIdentifier = $event.identifier"
                  />
                </div>

                <StatConfigurationPicker
                  title="目标耐久配置"
                  role="defender"
                  :pokemon-id="goal.target?.pokemon_id ?? null"
                  :pokemon-name="goal.target?.display_name ?? null"
                  :model-value="goal.targetPreset"
                  @update:model-value="goal.targetPreset = $event"
                />

                <div class="goal-move-selector">
                  <MoveSelector
                    :pokemon-id="solver.subject.value?.pokemon_id ?? null"
                    :ruleset-id="solver.rulesetId.value"
                    :selected="goal.move"
                    :disabled="!solver.subject.value"
                    @select="goal.move = $event"
                    @clear-selection="goal.move = null"
                  />
                </div>
              </article>
            </section>

            <section class="goal-column" aria-labelledby="defense-goals-title">
              <header class="goal-column__heading">
                <div>
                  <h3 id="defense-goals-title">防目标</h3>
                  <small>待配置 Pokémon 承受指定次数攻击后存活</small>
                </div>
                <button
                  type="button"
                  class="secondary-button"
                  data-testid="open-defense-goal-dialog"
                  @click="openAddGoalDialog('defense')"
                >
                  添加防目标
                </button>
              </header>

              <p v-if="defenseGoals.length === 0" class="goal-empty">
                暂无防目标，可按需添加。
              </p>

              <article v-for="goal in defenseGoals" :key="goal.id" class="goal-editor">
                <div class="goal-toolbar">
                  <select v-model="goal.rollPolicy" aria-label="随机伤害档">
                    <option value="max">最高伤害档</option>
                    <option value="min">最低伤害档</option>
                  </select>
                  <label>
                    次数
                    <input v-model.number="goal.repetitions" type="number" min="1" max="10" />
                  </label>
                  <button
                    type="button"
                    class="icon-button"
                    aria-label="删除防目标"
                    @click="solver.removeGoal(goal.id)"
                  >
                    ×
                  </button>
                </div>

                <div class="goal-target-heading">
                  <strong>攻击来源</strong>
                  <button
                    type="button"
                    class="text-button"
                    @click="openReplaceGoalDialog(goal)"
                  >
                    更换
                  </button>
                </div>
                <PokemonSummaryCard :pokemon="goal.target" />

                <div class="goal-mechanics">
                  <ItemSelector
                    title="攻击来源道具"
                    :items="solver.itemOptions.value"
                    :selected-identifier="goal.targetItemIdentifier"
                    :disabled="!goal.target"
                    :loading="solver.itemsLoading.value"
                    @select="goal.targetItemIdentifier = $event.identifier"
                  />
                  <AbilitySelector
                    title="攻击来源特性"
                    :abilities="goal.targetAbilityOptions"
                    :selected-identifier="goal.targetAbilityIdentifier"
                    :disabled="!goal.target"
                    :loading="goal.targetAbilitiesLoading"
                    @select="goal.targetAbilityIdentifier = $event.identifier"
                  />
                </div>

                <StatConfigurationPicker
                  title="攻击来源配置"
                  role="attacker"
                  :pokemon-id="goal.target?.pokemon_id ?? null"
                  :pokemon-name="goal.target?.display_name ?? null"
                  :model-value="goal.targetPreset"
                  @update:model-value="goal.targetPreset = $event"
                />

                <div class="goal-move-selector">
                  <MoveSelector
                    :pokemon-id="goal.target?.pokemon_id ?? null"
                    :ruleset-id="solver.rulesetId.value"
                    :selected="goal.move"
                    :disabled="!goal.target"
                    @select="goal.move = $event"
                    @clear-selection="goal.move = null"
                  />
                </div>
              </article>
            </section>
          </div>
        </div>

        <section class="action-band">
          <button
            class="primary-button"
            type="button"
            :disabled="!solver.canSubmit.value"
            @click="solver.submit"
          >
            {{ solver.loading.value ? '求解中' : '开始求解' }}
          </button>
          <p v-if="solver.error.value" class="error">{{ solver.error.value }}</p>
        </section>

        <section v-if="solver.result.value" class="solver-panel result-panel">
          <div class="panel-heading">
            <h2>{{ solver.result.value.reachable ? '可达配置' : '当前不可达' }}</h2>
            <span>{{ solver.result.value.ruleset_name }}</span>
          </div>

          <div v-if="solver.result.value.reachable" class="candidate-list">
            <article
              v-for="candidate in solver.result.value.candidates"
              :key="candidate.stat_preset"
              class="candidate-card"
            >
              <h3>{{ candidate.stat_preset_label }}</h3>
              <p>{{ candidate.stat_preset_assumption }}</p>
              <dl class="stats-grid">
                <template v-for="(value, key) in candidate.stats" :key="key">
                  <dt>{{ key }}</dt>
                  <dd>{{ value }}</dd>
                </template>
              </dl>
            </article>
          </div>

          <div class="evidence-list">
            <article
              v-for="goal in solver.visibleEvidence.value"
              :key="goal.goal_id"
              class="evidence-row"
              :class="{ failed: !goal.satisfied }"
            >
              <strong>{{ goal.satisfied ? '满足' : '未满足' }} · {{ goal.move.display_name }}</strong>
              <span>
                {{ goal.repetitions }} 次 × {{ goal.selected_damage }}
                = {{ goal.total_damage }} / HP {{ goal.hp_threshold }}
              </span>
              <small>{{ goal.roll_policy === 'max' ? '最高伤害档' : '最低伤害档' }} · 剩余 HP {{ goal.remaining_hp }}</small>
            </article>
          </div>

          <ul class="scope-list">
            <li v-for="item in solver.result.value.scope" :key="item">{{ item }}</li>
          </ul>
          <p v-for="warning in solver.result.value.warnings" :key="warning" class="muted">{{ warning }}</p>
        </section>
      </section>
    </section>

    <div
      v-if="goalDialogOpen"
      class="goal-dialog-backdrop"
      data-testid="goal-dialog-backdrop"
      @click.self="closeGoalDialog"
    >
      <section
        class="goal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="goal-dialog-title"
        tabindex="-1"
        @keydown.esc.prevent="closeGoalDialog"
      >
        <header class="goal-dialog__header">
          <div>
            <h2 id="goal-dialog-title">{{ goalDialogTitle }}</h2>
            <p class="muted">先选择 Pokémon，确认后才会写入已选目标列表。</p>
          </div>
          <button
            type="button"
            class="icon-button"
            aria-label="关闭目标选择弹窗"
            :disabled="goalDialogSubmitting"
            @click="closeGoalDialog"
          >
            ×
          </button>
        </header>

        <PokemonSelector
          :title="goalDialogPokemonTitle"
          :ruleset-id="solver.rulesetId.value"
          :selected="goalDialogPokemon"
          :recent-pokemon="recentPokemon"
          @select="selectGoalDialogPokemon"
        />

        <footer class="goal-dialog__footer">
          <button
            type="button"
            class="secondary-button"
            :disabled="goalDialogSubmitting"
            @click="closeGoalDialog"
          >
            取消
          </button>
          <button
            type="button"
            class="primary-button"
            data-testid="confirm-goal-dialog"
            :disabled="!goalDialogPokemon || goalDialogSubmitting"
            @click="confirmGoalDialog"
          >
            {{ goalDialogSubmitting ? '加载中' : goalDialogTitle }}
          </button>
        </footer>
      </section>
    </div>
  </main>
</template>

<style scoped>
.solver-layout {
  align-items: start;
  display: grid;
  gap: 18px;
  grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
}

.solver-side,
.solver-main {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.solver-panel {
  background: #ffffff;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  padding: 16px;
}

.solver-panel h2,
.solver-panel h3,
.candidate-card h3 {
  margin: 0;
}

.panel-heading,
.goal-toolbar,
.goal-column__heading,
.goal-target-heading {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: space-between;
}

.panel-heading p {
  margin: 5px 0 0;
}

.goal-columns {
  align-items: start;
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 14px;
}

.goal-column {
  background: #f8faf8;
  border: 1px solid #dfe6dc;
  border-radius: 10px;
  min-width: 0;
  padding: 12px;
}

.goal-column__heading {
  align-items: flex-start;
}

.goal-column__heading small {
  color: #65736b;
  display: block;
  margin-top: 4px;
}

.goal-empty {
  border: 1px dashed #cbd6cc;
  border-radius: 8px;
  color: #65736b;
  margin: 12px 0 0;
  padding: 18px 12px;
  text-align: center;
}

.goal-editor {
  background: #fff;
  border: 1px solid #d8dee8;
  border-radius: 10px;
  display: grid;
  gap: 12px;
  margin-top: 12px;
  min-width: 0;
  padding: 12px;
}

.goal-toolbar {
  justify-content: flex-start;
}

.goal-toolbar label {
  align-items: center;
  display: inline-flex;
  gap: 6px;
}

.goal-toolbar input,
.goal-toolbar select {
  min-height: 36px;
}

.goal-toolbar input {
  width: 64px;
}

.goal-toolbar .icon-button {
  margin-left: auto;
}

.goal-target-heading {
  border-bottom: 1px solid #e5e9e4;
  padding-bottom: 8px;
}

.goal-mechanics {
  display: grid;
  gap: 10px;
}

.goal-move-selector {
  min-width: 0;
}

.goal-move-selector :deep(.move-selector) {
  column-gap: 0;
  grid-template-columns: 1fr;
  grid-template-rows: auto auto auto auto minmax(0, 1fr) auto;
  min-height: 0;
  overflow: visible;
}

.goal-move-selector :deep(.move-selector)::before,
.goal-move-selector :deep(.move-selector)::after {
  display: none;
}

.goal-move-selector :deep(.move-selector > .field-title) {
  font-size: 16px;
  grid-column: 1;
  grid-row: 1;
  padding-right: 0;
}

.goal-move-selector :deep(.move-selector > .field-title)::after {
  content: none;
}

.goal-move-selector :deep(.move-filter-group) {
  grid-column: 1;
  grid-row: 2;
  padding-right: 0;
}

.goal-move-selector :deep(.move-type-filter) {
  grid-column: 1;
  grid-row: 3;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  padding-right: 0;
}

.goal-move-selector :deep(.move-selector > .search-input) {
  grid-column: 1;
  grid-row: 4;
}

.goal-move-selector :deep(.move-selector > .row-message),
.goal-move-selector :deep(.move-selector > .option-list.compact) {
  grid-column: 1;
  grid-row: 5;
}

.goal-move-selector :deep(.move-selector > .move-more-button) {
  grid-column: 1;
  grid-row: 6;
}

.goal-dialog-backdrop {
  align-items: center;
  background: rgba(23, 32, 27, 0.52);
  display: flex;
  inset: 0;
  justify-content: center;
  padding: 20px;
  position: fixed;
  z-index: 70;
}

.goal-dialog {
  background: #fff;
  border: 1px solid #bdc9c0;
  border-radius: 12px;
  box-shadow: 0 20px 64px rgba(23, 32, 27, 0.28);
  max-height: calc(100vh - 40px);
  overflow: auto;
  padding: 16px;
  width: min(640px, 100%);
}

.goal-dialog__header,
.goal-dialog__footer {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.goal-dialog__header {
  margin-bottom: 14px;
}

.goal-dialog__header h2,
.goal-dialog__header p {
  margin: 0;
}

.goal-dialog__header p {
  margin-top: 4px;
}

.goal-dialog__footer {
  justify-content: flex-end;
  margin-top: 14px;
}

.goal-dialog :deep(.panel-block) {
  max-height: min(560px, calc(100vh - 190px));
  overflow: auto;
}

.preset-grid,
.candidate-list,
.evidence-list {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.preset-grid button,
.candidate-card,
.evidence-row {
  border: 1px solid #d8dee8;
  border-radius: 8px;
  padding: 12px;
  text-align: left;
}

.preset-grid button.selected {
  border-color: #2454d6;
  box-shadow: inset 0 0 0 1px #2454d6;
}

.preset-grid span,
.evidence-row span,
.evidence-row small {
  display: block;
  margin-top: 4px;
}

.icon-button {
  min-height: 36px;
  width: 36px;
}

.secondary-button {
  min-height: 36px;
}

.stats-grid {
  display: grid;
  gap: 6px 12px;
  grid-template-columns: repeat(2, auto);
  margin: 12px 0 0;
}

.stats-grid dt {
  color: #657186;
}

.stats-grid dd {
  margin: 0;
  text-align: right;
}

.evidence-row.failed {
  border-color: #b42318;
}

.scope-list {
  color: #43506a;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  list-style: none;
  margin: 14px 0 0;
  padding: 0;
}

.scope-list li {
  background: #eef3ff;
  border-radius: 999px;
  padding: 4px 9px;
}

@media (max-width: 1180px) {
  .goal-columns {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .solver-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .goal-dialog-backdrop {
    padding: 10px;
  }

  .goal-dialog {
    max-height: calc(100vh - 20px);
    padding: 12px;
  }
}
</style>
