<script setup lang="ts">
import { computed, onMounted } from 'vue';
import type { PokemonSearchItem } from '../api/calculator';
import AbilitySelector from '../components/AbilitySelector.vue';
import ItemSelector from '../components/ItemSelector.vue';
import MoveSelector from '../components/MoveSelector.vue';
import PokemonSelector from '../components/PokemonSelector.vue';
import PokemonSummaryCard from '../components/PokemonSummaryCard.vue';
import StatConfigurationPicker from '../components/StatConfigurationPicker.vue';
import { useConfigurationSolver, type EditableSolverGoal } from '../composables/useConfigurationSolver';
import { useRecentPokemon } from '../composables/useRecentPokemon';

const solver = useConfigurationSolver();
const { items: recentPokemon, remember: rememberPokemon } = useRecentPokemon();
const attackGoals = computed(() => solver.goals.value.filter((goal) => goal.kind === 'attack'));
const defenseGoals = computed(() => solver.goals.value.filter((goal) => goal.kind === 'defense'));

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
 * 选择目标 Pokémon，并写入最近选择。
 *
 * @param goal 被更新的目标。
 * @param pokemon 用户选中的 Pokémon。
 */
async function selectTarget(goal: EditableSolverGoal, pokemon: PokemonSearchItem): Promise<void> {
  rememberPokemon(pokemon);
  await solver.selectGoalTarget(goal, pokemon);
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
              <p class="muted">每条目标独立选择 Pokémon、配置、道具、特性与招式。</p>
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
                  @click="solver.addGoal('attack')"
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
                    :disabled="solver.goals.value.length === 1"
                    aria-label="删除攻目标"
                    @click="solver.removeGoal(goal.id)"
                  >
                    ×
                  </button>
                </div>

                <PokemonSelector
                  title="防守目标"
                  :ruleset-id="solver.rulesetId.value"
                  :selected="goal.target"
                  :recent-pokemon="recentPokemon"
                  @select="selectTarget(goal, $event)"
                />
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
                  @click="solver.addGoal('defense')"
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
                    :disabled="solver.goals.value.length === 1"
                    aria-label="删除防目标"
                    @click="solver.removeGoal(goal.id)"
                  >
                    ×
                  </button>
                </div>

                <PokemonSelector
                  title="攻击来源"
                  :ruleset-id="solver.rulesetId.value"
                  :selected="goal.target"
                  :recent-pokemon="recentPokemon"
                  @select="selectTarget(goal, $event)"
                />
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
</style>
