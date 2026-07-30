<script setup lang="ts">
import { onMounted } from 'vue';
import type { PokemonSearchItem } from '../api/calculator';
import MoveSelector from '../components/MoveSelector.vue';
import PokemonSelector from '../components/PokemonSelector.vue';
import PokemonSummaryCard from '../components/PokemonSummaryCard.vue';
import { useConfigurationSolver, type EditableSolverGoal } from '../composables/useConfigurationSolver';
import { useRecentPokemon } from '../composables/useRecentPokemon';

const solver = useConfigurationSolver();
const { items: recentPokemon, remember: rememberPokemon } = useRecentPokemon();

/** 初始化配置模板。 */
onMounted(() => {
  void solver.loadPresets();
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

        <div class="solver-panel">
          <h2>搜索配置</h2>
          <div class="preset-grid">
            <button
              v-for="preset in solver.statPresets.value"
              :key="preset.key"
              type="button"
              :class="{ selected: solver.selectedPresetKeys.value.includes(preset.key) }"
              @click="solver.togglePreset(preset.key)"
            >
              <strong>{{ preset.label }}</strong>
              <span>{{ preset.assumption }}</span>
            </button>
          </div>
        </div>
      </aside>

      <section class="solver-main">
        <div class="solver-panel">
          <div class="panel-heading">
            <h2>攻防目标</h2>
            <button type="button" class="secondary-button" @click="solver.addGoal">添加目标</button>
          </div>

          <article v-for="goal in solver.goals.value" :key="goal.id" class="goal-editor">
            <div class="goal-toolbar">
              <select v-model="goal.kind" aria-label="目标类型">
                <option value="defense">防守：承受攻击后存活</option>
                <option value="attack">攻击：指定回合内击倒</option>
              </select>
              <select v-model="goal.rollPolicy" aria-label="随机伤害档">
                <option value="max">最高伤害档</option>
                <option value="min">最低伤害档</option>
              </select>
              <select v-model="goal.targetPreset" aria-label="对手配置">
                <option v-for="preset in solver.statPresets.value" :key="preset.key" :value="preset.key">
                  {{ preset.label }}
                </option>
              </select>
              <label>
                次数
                <input v-model.number="goal.repetitions" type="number" min="1" max="10" />
              </label>
              <button type="button" class="icon-button" @click="solver.removeGoal(goal.id)">×</button>
            </div>

            <div class="goal-grid">
              <PokemonSelector
                :title="goal.kind === 'attack' ? '击倒目标' : '攻击来源'"
                :ruleset-id="solver.rulesetId.value"
                :selected="goal.target"
                :recent-pokemon="recentPokemon"
                @select="selectTarget(goal, $event)"
              />
              <MoveSelector
                :pokemon-id="goal.kind === 'attack'
                  ? solver.subject.value?.pokemon_id ?? null
                  : goal.target?.pokemon_id ?? null"
                :ruleset-id="solver.rulesetId.value"
                :selected="goal.move"
                :disabled="goal.kind === 'attack' ? !solver.subject.value : !goal.target"
                @select="goal.move = $event"
                @clear-selection="goal.move = null"
              />
            </div>
          </article>
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
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
}

.solver-side,
.solver-main {
  display: grid;
  gap: 16px;
}

.solver-panel {
  background: #ffffff;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  padding: 16px;
}

.solver-panel h2,
.candidate-card h3 {
  margin: 0;
}

.panel-heading,
.goal-toolbar {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: space-between;
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

.goal-editor {
  border-top: 1px solid #e5e9f0;
  display: grid;
  gap: 12px;
  margin-top: 14px;
  padding-top: 14px;
}

.goal-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.goal-toolbar input,
.goal-toolbar select {
  min-height: 36px;
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

@media (max-width: 900px) {
  .solver-layout,
  .goal-grid {
    grid-template-columns: 1fr;
  }
}
</style>
