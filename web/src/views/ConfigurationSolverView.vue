<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import type {
  BattleAbilityOption,
  BattleItemOption,
  MoveSearchItem,
  PokemonSearchItem,
} from '../api/calculator';
import type { ConfigurationGoalKind, DamageRollPolicy } from '../api/configurationSolver';
import AbilitySelector from '../components/AbilitySelector.vue';
import ItemSelector from '../components/ItemSelector.vue';
import MoveSelector from '../components/MoveSelector.vue';
import PokemonSelector from '../components/PokemonSelector.vue';
import PokemonSummaryCard from '../components/PokemonSummaryCard.vue';
import StatConfigurationPicker from '../components/StatConfigurationPicker.vue';
import { useConfigurationSolver, type EditableSolverGoal } from '../composables/useConfigurationSolver';
import { useRecentPokemon } from '../composables/useRecentPokemon';

type GoalDialogMode = 'create' | 'edit';

const solver = useConfigurationSolver();
const { items: recentPokemon, remember: rememberPokemon } = useRecentPokemon();
const attackGoals = computed(() => solver.goals.value.filter((goal) => goal.kind === 'attack'));
const defenseGoals = computed(() => solver.goals.value.filter((goal) => goal.kind === 'defense'));
const goalDialogOpen = ref(false);
const goalDialogMode = ref<GoalDialogMode>('create');
const goalDialogDraft = ref<EditableSolverGoal | null>(null);

const goalDialogTitle = computed(() => {
  const draft = goalDialogDraft.value;
  if (draft === null) return '配置目标';
  const action = goalDialogMode.value === 'create' ? '添加' : '编辑';
  return `${action}${draft.kind === 'attack' ? '攻目标' : '防目标'}`;
});
const goalDialogPokemonTitle = computed(() => (
  goalDialogDraft.value?.kind === 'attack' ? '选择防守目标' : '选择攻击来源'
));
const goalDialogConfigTitle = computed(() => (
  goalDialogDraft.value?.kind === 'attack' ? '目标耐久配置' : '攻击来源配置'
));
const goalDialogRole = computed<'attacker' | 'defender'>(() => (
  goalDialogDraft.value?.kind === 'attack' ? 'defender' : 'attacker'
));
const goalDialogItemTitle = computed(() => (
  goalDialogDraft.value?.kind === 'attack' ? '防守方道具' : '攻击来源道具'
));
const goalDialogAbilityTitle = computed(() => (
  goalDialogDraft.value?.kind === 'attack' ? '防守方特性' : '攻击来源特性'
));
const goalDialogMovePokemonId = computed<number | null>(() => {
  const draft = goalDialogDraft.value;
  if (draft === null) return null;
  if (draft.kind === 'attack') return solver.subject.value?.pokemon_id ?? null;
  return draft.target?.pokemon_id ?? null;
});
const goalDialogMoveDisabled = computed(() => goalDialogMovePokemonId.value === null);
const goalDialogCanSave = computed(() => {
  const draft = goalDialogDraft.value;
  return Boolean(
    draft
      && solver.isGoalComplete(draft)
      && !draft.targetAbilitiesLoading,
  );
});

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
 * 打开新增目标弹窗，并创建与列表隔离的完整目标草稿。
 *
 * @param kind attack 表示待配置 Pokémon 主动攻击，defense 表示待配置 Pokémon 承受攻击。
 */
function openAddGoalDialog(kind: ConfigurationGoalKind): void {
  goalDialogMode.value = 'create';
  goalDialogDraft.value = solver.createGoalDraft(kind);
  goalDialogOpen.value = true;
}

/**
 * 打开目标详情编辑弹窗，复制当前已保存参数，取消时不会污染列表。
 *
 * @param goal 用户准备查看或修改的已选目标。
 */
function openEditGoalDialog(goal: EditableSolverGoal): void {
  goalDialogMode.value = 'edit';
  goalDialogDraft.value = solver.cloneGoal(goal);
  goalDialogOpen.value = true;
}

/** 关闭目标配置弹窗，并丢弃尚未保存的完整草稿。 */
function closeGoalDialog(): void {
  goalDialogOpen.value = false;
  goalDialogDraft.value = null;
}

/**
 * 在弹窗草稿中加载 Pokémon 详情与合法特性，不立即写入已选列表。
 *
 * @param pokemon 用户在弹窗中选择的 Pokémon。
 */
async function selectGoalDialogPokemon(pokemon: PokemonSearchItem): Promise<void> {
  const draft = goalDialogDraft.value;
  if (draft === null) return;
  await solver.selectGoalTarget(draft, pokemon);
}

/**
 * 保存弹窗中的完整目标参数，并在成功后关闭弹窗。
 *
 * 新增与编辑都通过同一原子保存入口提交；列表只接收完整目标快照。
 */
function confirmGoalDialog(): void {
  const draft = goalDialogDraft.value;
  if (draft === null || !solver.saveGoalDraft(draft)) return;
  if (draft.target !== null) rememberPokemon(draft.target);
  closeGoalDialog();
}

/**
 * 更新弹窗草稿中的道具 identifier。
 *
 * @param item 用户选择的道具目录项。
 */
function selectDialogItem(item: BattleItemOption): void {
  if (goalDialogDraft.value !== null) {
    goalDialogDraft.value.targetItemIdentifier = item.identifier;
  }
}

/**
 * 更新弹窗草稿中的特性 identifier。
 *
 * @param ability 用户选择的当前 Pokémon 合法特性。
 */
function selectDialogAbility(ability: BattleAbilityOption): void {
  if (goalDialogDraft.value !== null) {
    goalDialogDraft.value.targetAbilityIdentifier = ability.identifier;
  }
}

/**
 * 更新弹窗草稿中的目标配置快照标识。
 *
 * @param presetId 配置选择器返回的稳定 snapshot profile id。
 */
function selectDialogPreset(presetId: string): void {
  if (goalDialogDraft.value !== null) {
    goalDialogDraft.value.targetPreset = presetId;
  }
}

/**
 * 更新弹窗草稿中的招式。
 *
 * @param move 当前攻击方可学习并可计算的招式。
 */
function selectDialogMove(move: MoveSearchItem): void {
  if (goalDialogDraft.value !== null) {
    goalDialogDraft.value.move = move;
  }
}

/** 清空弹窗草稿中的招式，避免筛选变化后保留失效 move_id。 */
function clearDialogMove(): void {
  if (goalDialogDraft.value !== null) {
    goalDialogDraft.value.move = null;
  }
}

/**
 * 更新目标要求的攻击次数或承受次数。
 *
 * @param event number input 的原生输入事件。
 */
function updateDialogRepetitions(event: Event): void {
  const draft = goalDialogDraft.value;
  if (draft === null) return;
  const value = Number((event.target as HTMLInputElement).value);
  draft.repetitions = Number.isInteger(value) ? Math.min(10, Math.max(1, value)) : 1;
}

/**
 * 更新目标采用的随机伤害档策略。
 *
 * @param event select 的原生变化事件。
 */
function updateDialogRollPolicy(event: Event): void {
  const draft = goalDialogDraft.value;
  if (draft === null) return;
  draft.rollPolicy = (event.target as HTMLSelectElement).value as DamageRollPolicy;
}

/** 返回紧凑列表中展示的特性名称。 */
function abilityName(goal: EditableSolverGoal): string {
  return goal.targetAbilityOptions.find(
    (ability) => ability.identifier === goal.targetAbilityIdentifier,
  )?.display_name ?? goal.targetAbilityIdentifier;
}

/** 返回紧凑列表中展示的道具名称。 */
function itemName(goal: EditableSolverGoal): string {
  return solver.itemOptions.value.find(
    (item) => item.identifier === goal.targetItemIdentifier,
  )?.display_name ?? (goal.targetItemIdentifier === 'none' ? '不携带道具' : goal.targetItemIdentifier);
}

/** 返回紧凑列表中展示的配置名称。 */
function presetName(goal: EditableSolverGoal): string {
  return solver.statPresets.value.find(
    (preset) => preset.key === goal.targetPreset,
  )?.label ?? goal.targetPreset;
}

/** 返回紧凑列表中展示的随机伤害档文本。 */
function rollPolicyName(policy: DamageRollPolicy): string {
  return policy === 'max' ? '最高伤害档' : '最低伤害档';
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
              <p class="muted">列表只保留每个目标的一条摘要；全部详细参数在弹窗中查看和编辑。</p>
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

              <article
                v-for="goal in attackGoals"
                :key="goal.id"
                class="goal-summary-row"
                data-testid="goal-summary-row"
              >
                <button
                  type="button"
                  class="goal-summary-row__main"
                  :aria-label="`查看并编辑攻目标 ${goal.target?.display_name ?? ''}`"
                  @click="openEditGoalDialog(goal)"
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
                    <span class="goal-summary-row__primary">
                      {{ goal.move?.display_name }} · {{ goal.repetitions }} 次 · {{ rollPolicyName(goal.rollPolicy) }}
                    </span>
                    <span class="goal-summary-row__meta">
                      {{ presetName(goal) }} · {{ abilityName(goal) }} · {{ itemName(goal) }}
                    </span>
                  </span>
                  <span class="goal-summary-row__edit">查看 / 编辑</span>
                </button>
                <button
                  type="button"
                  class="icon-button goal-summary-row__delete"
                  aria-label="删除攻目标"
                  @click="solver.removeGoal(goal.id)"
                >
                  ×
                </button>
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

              <article
                v-for="goal in defenseGoals"
                :key="goal.id"
                class="goal-summary-row"
                data-testid="goal-summary-row"
              >
                <button
                  type="button"
                  class="goal-summary-row__main"
                  :aria-label="`查看并编辑防目标 ${goal.target?.display_name ?? ''}`"
                  @click="openEditGoalDialog(goal)"
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
                    <span class="goal-summary-row__primary">
                      {{ goal.move?.display_name }} · {{ goal.repetitions }} 次 · {{ rollPolicyName(goal.rollPolicy) }}
                    </span>
                    <span class="goal-summary-row__meta">
                      {{ presetName(goal) }} · {{ abilityName(goal) }} · {{ itemName(goal) }}
                    </span>
                  </span>
                  <span class="goal-summary-row__edit">查看 / 编辑</span>
                </button>
                <button
                  type="button"
                  class="icon-button goal-summary-row__delete"
                  aria-label="删除防目标"
                  @click="solver.removeGoal(goal.id)"
                >
                  ×
                </button>
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
      v-if="goalDialogOpen && goalDialogDraft"
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
            <p class="muted">在这里完成 Pokémon、配置、道具、特性、招式和目标条件。</p>
          </div>
          <button
            type="button"
            class="icon-button"
            aria-label="关闭目标配置弹窗"
            @click="closeGoalDialog"
          >
            ×
          </button>
        </header>

        <div class="goal-dialog__content">
          <section class="goal-dialog__identity">
            <PokemonSelector
              :title="goalDialogPokemonTitle"
              :ruleset-id="solver.rulesetId.value"
              :selected="goalDialogDraft.target"
              :recent-pokemon="recentPokemon"
              @select="selectGoalDialogPokemon"
            />
            <div v-if="goalDialogDraft.targetAbilitiesLoading" class="muted row-message">
              正在加载 Pokémon 资料与特性
            </div>
            <PokemonSummaryCard :pokemon="goalDialogDraft.target" />

            <div class="goal-condition-panel">
              <label>
                <span>{{ goalDialogDraft.kind === 'attack' ? '击倒次数' : '承受次数' }}</span>
                <input
                  :value="goalDialogDraft.repetitions"
                  type="number"
                  min="1"
                  max="10"
                  @input="updateDialogRepetitions"
                />
              </label>
              <label>
                <span>随机伤害档</span>
                <select :value="goalDialogDraft.rollPolicy" @change="updateDialogRollPolicy">
                  <option value="min">最低伤害档</option>
                  <option value="max">最高伤害档</option>
                </select>
              </label>
            </div>
          </section>

          <section class="goal-dialog__details">
            <div class="goal-dialog__mechanics">
              <ItemSelector
                :title="goalDialogItemTitle"
                :items="solver.itemOptions.value"
                :selected-identifier="goalDialogDraft.targetItemIdentifier"
                :disabled="!goalDialogDraft.target"
                :loading="solver.itemsLoading.value"
                @select="selectDialogItem"
              />
              <AbilitySelector
                :title="goalDialogAbilityTitle"
                :abilities="goalDialogDraft.targetAbilityOptions"
                :selected-identifier="goalDialogDraft.targetAbilityIdentifier"
                :disabled="!goalDialogDraft.target"
                :loading="goalDialogDraft.targetAbilitiesLoading"
                @select="selectDialogAbility"
              />
            </div>

            <StatConfigurationPicker
              :title="goalDialogConfigTitle"
              :role="goalDialogRole"
              :pokemon-id="goalDialogDraft.target?.pokemon_id ?? null"
              :pokemon-name="goalDialogDraft.target?.display_name ?? null"
              :model-value="goalDialogDraft.targetPreset"
              @update:model-value="selectDialogPreset"
            />

            <div class="goal-dialog__move-selector">
              <MoveSelector
                :pokemon-id="goalDialogMovePokemonId"
                :ruleset-id="solver.rulesetId.value"
                :selected="goalDialogDraft.move"
                :disabled="goalDialogMoveDisabled"
                @select="selectDialogMove"
                @clear-selection="clearDialogMove"
              />
            </div>
          </section>
        </div>

        <p v-if="solver.error.value" class="error goal-dialog__error">{{ solver.error.value }}</p>

        <footer class="goal-dialog__footer">
          <span class="muted">
            {{ goalDialogCanSave ? '参数已完整，可以保存。' : '请完成全部必填参数。' }}
          </span>
          <div class="goal-dialog__actions">
            <button type="button" class="secondary-button" @click="closeGoalDialog">
              取消
            </button>
            <button
              type="button"
              class="primary-button"
              data-testid="confirm-goal-dialog"
              :disabled="!goalDialogCanSave"
              @click="confirmGoalDialog"
            >
              {{ goalDialogMode === 'create' ? '添加目标' : '保存修改' }}
            </button>
          </div>
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
.goal-column__heading {
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

.goal-summary-row {
  align-items: stretch;
  background: #fff;
  border: 1px solid #d8dee8;
  border-radius: 10px;
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(0, 1fr) 36px;
  margin-top: 10px;
  padding: 8px;
}

.goal-summary-row__main {
  align-items: center;
  background: transparent;
  border: 0;
  display: grid;
  gap: 10px;
  grid-template-columns: 52px minmax(0, 1fr) auto;
  min-width: 0;
  padding: 4px;
  text-align: left;
}

.goal-summary-row__main:hover {
  background: #f4f8f4;
  border-radius: 8px;
}

.goal-summary-row__sprite {
  height: 48px;
  object-fit: contain;
  width: 48px;
}

.goal-summary-row__body,
.goal-summary-row__title,
.goal-summary-row__primary,
.goal-summary-row__meta {
  display: block;
  min-width: 0;
}

.goal-summary-row__title {
  color: #17201b;
  font-weight: 800;
}

.goal-summary-row__title small {
  color: #6b776f;
  font-weight: 500;
  margin-left: 5px;
}

.goal-summary-row__primary,
.goal-summary-row__meta {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.goal-summary-row__primary {
  color: #34463c;
  margin-top: 3px;
}

.goal-summary-row__meta {
  color: #6b776f;
  font-size: 12px;
  margin-top: 3px;
}

.goal-summary-row__edit {
  color: #315c49;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.goal-summary-row__delete {
  align-self: center;
}

.goal-dialog-backdrop {
  align-items: center;
  background: rgba(23, 32, 27, 0.55);
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
  border-radius: 14px;
  box-shadow: 0 24px 72px rgba(23, 32, 27, 0.3);
  max-height: calc(100vh - 40px);
  overflow: auto;
  padding: 18px;
  width: min(1080px, 100%);
}

.goal-dialog__header,
.goal-dialog__footer,
.goal-dialog__actions {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.goal-dialog__header {
  border-bottom: 1px solid #e2e8e2;
  padding-bottom: 14px;
}

.goal-dialog__header h2,
.goal-dialog__header p {
  margin: 0;
}

.goal-dialog__header p {
  margin-top: 4px;
}

.goal-dialog__content {
  align-items: start;
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
  margin-top: 16px;
}

.goal-dialog__identity,
.goal-dialog__details,
.goal-dialog__mechanics {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.goal-dialog__mechanics {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.goal-condition-panel {
  background: #f7faf7;
  border: 1px solid #dce5dc;
  border-radius: 8px;
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  padding: 12px;
}

.goal-condition-panel label {
  display: grid;
  gap: 5px;
}

.goal-condition-panel span {
  color: #516157;
  font-size: 12px;
  font-weight: 700;
}

.goal-condition-panel input,
.goal-condition-panel select {
  min-height: 36px;
  width: 100%;
}

.goal-dialog__move-selector {
  min-width: 0;
}

.goal-dialog__move-selector :deep(.move-selector) {
  min-height: 420px;
}

.goal-dialog__error {
  margin: 12px 0 0;
}

.goal-dialog__footer {
  border-top: 1px solid #e2e8e2;
  margin-top: 16px;
  padding-top: 14px;
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
  .goal-columns,
  .goal-dialog__content {
    grid-template-columns: 1fr;
  }

  .goal-dialog__mechanics {
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

  .goal-dialog__footer {
    align-items: stretch;
    flex-direction: column;
  }

  .goal-dialog__actions {
    justify-content: flex-end;
    width: 100%;
  }

  .goal-summary-row__main {
    grid-template-columns: 44px minmax(0, 1fr);
  }

  .goal-summary-row__sprite {
    height: 40px;
    width: 40px;
  }

  .goal-summary-row__edit {
    display: none;
  }
}
</style>
