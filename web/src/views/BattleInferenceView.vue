<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import type { PokemonSearchItem } from '../api/calculator';
import { SUPPORTED_VERSION_GROUPS } from '../api/configurationSpace';
import {
  enumerateMoveSetCombinations,
  inferFixedBattleJourney,
} from '../api/fixedBattle';
import type {
  BattleExplorationResult,
  BattleGraphExplorationResult,
} from '../api/inference';
import BattleSideConfigurationPanel from '../components/inference/BattleSideConfigurationPanel.vue';
import BattleGraphExplorer from '../components/inference/BattleGraphExplorer.vue';
import BattleReportPanel from '../components/inference/BattleReportPanel.vue';
import BattleGraphTreeScreen from '../components/inference/BattleGraphTreeScreen.vue';
import {
  useBattleInferenceConfiguration,
  type BattleSideConfigurationState,
} from '../composables/useBattleInferenceConfiguration';
import { useRecentPokemon } from '../composables/useRecentPokemon';
import { createBattleReportPresenterContext } from '../presenters/battleEventPresenter';
import type {
  FixedBattleSideInput,
  FixedBattleSummaryResult,
  MoveSetCombinationsResult,
  MoveSetOptionResult,
} from '../types/fixedBattle';
import './BattleInferenceView.css';

const configuration = useBattleInferenceConfiguration();
const {
  rulesetId,
  versionGroupId,
  calculationRevision,
  attacker,
  defender,
  attackerPresets,
  defenderPresets,
  selectionNotice,
  budget,
  remainingGlobalSlots,
  validationMessages,
  canSubmit,
  loadPresets,
  selectPokemon: selectConfigurationPokemon,
  updateSelectedMoveIds,
  applyDragoniteVsWeavilePreset,
} = configuration;
const { items: recentPokemon, remember: rememberPokemon } = useRecentPokemon();
const countFormatter = new Intl.NumberFormat('zh-CN');

const combinationLoading = ref(false);
const inferenceLoading = ref(false);
const workflowError = ref<string | null>(null);
const combinations = ref<MoveSetCombinationsResult | null>(null);
const selectedAttackerMoveSetId = ref<string | null>(null);
const selectedDefenderMoveSetId = ref<string | null>(null);
const summary = ref<FixedBattleSummaryResult | null>(null);
const graphHandle = ref<BattleExplorationResult | null>(null);
const activeExploration = ref<BattleGraphExplorationResult | null>(null);
const treeScreenOpen = ref(false);

/** 初始化能力值模板；候选池会在选择 Pokémon 后按侧加载。 */
onMounted(() => {
  void loadPresets();
});

/**
 * 记录一侧 Pokémon 选择并加载详情与候选池。
 *
 * @param sideName 攻击方或防守方。
 * @param pokemon 复用选择器返回的轻量 Pokémon 搜索项。
 */
async function selectPokemon(
  sideName: 'attacker' | 'defender',
  pokemon: PokemonSearchItem,
): Promise<void> {
  rememberPokemon(pokemon);
  await selectConfigurationPokemon(sideName, pokemon);
}

/**
 * 格式化候选数、组合数和图规模。
 *
 * @param value 非负整数计数。
 * @returns 使用中文千分位分隔的展示文本。
 */
function formatCount(value: number): string {
  return countFormatter.format(value);
}

/**
 * 将页面一侧响应式状态冻结为 API 输入。
 *
 * @param side 已完成页面必填校验的一侧配置。
 * @returns 不引用响应式数组的固定配置 DTO。
 */
function fixedSideInput(side: BattleSideConfigurationState): FixedBattleSideInput {
  if (side.pokemon === null) {
    throw new Error('请选择双方 Pokémon 后再生成技能组合。');
  }
  return {
    pokemon_id: side.pokemon.pokemon_id,
    form_id: side.formId,
    level: side.level,
    stat_profile_id: side.statPreset,
    ability_identifier: side.abilityIdentifier,
    item_identifier: side.itemIdentifier === '' ? null : side.itemIdentifier,
  };
}

/** 返回当前组合结果中指定的一组技能。 */
function selectedMoveSet(
  side: 'attacker' | 'defender',
): MoveSetOptionResult | null {
  const result = combinations.value;
  if (result === null) return null;
  const selectedId =
    side === 'attacker'
      ? selectedAttackerMoveSetId.value
      : selectedDefenderMoveSetId.value;
  return result[side].move_sets.find((item) => item.move_set_id === selectedId) ?? null;
}

/** 调用服务端严格准入并生成左右独立技能组列表。 */
async function generateCombinations(): Promise<void> {
  if (!canSubmit.value) return;
  combinationLoading.value = true;
  workflowError.value = null;
  summary.value = null;
  try {
    const result = await enumerateMoveSetCombinations({
      ruleset_id: rulesetId.value,
      version_group_id: versionGroupId.value,
      calculation_revision: calculationRevision.value,
      attacker: {
        ...fixedSideInput(attacker),
        candidate_move_ids: [...attacker.selectedMoveIds],
      },
      defender: {
        ...fixedSideInput(defender),
        candidate_move_ids: [...defender.selectedMoveIds],
      },
    });
    combinations.value = result;
    selectedAttackerMoveSetId.value = result.attacker.move_sets[0]?.move_set_id ?? null;
    selectedDefenderMoveSetId.value = result.defender.move_sets[0]?.move_set_id ?? null;
  } catch (caught) {
    combinations.value = null;
    workflowError.value = caught instanceof Error ? caught.message : '技能组合生成失败';
  } finally {
    combinationLoading.value = false;
  }
}

/** 对当前选中的唯一双方技能组执行精确求解并保存可探索完整图。 */
async function runFixedInference(): Promise<void> {
  const attackerMoveSet = selectedMoveSet('attacker');
  const defenderMoveSet = selectedMoveSet('defender');
  if (attackerMoveSet === null || defenderMoveSet === null) return;

  inferenceLoading.value = true;
  workflowError.value = null;
  summary.value = null;
  try {
    const result = await inferFixedBattleJourney({
      ruleset_id: rulesetId.value,
      version_group_id: versionGroupId.value,
      attacker: {
        ...fixedSideInput(attacker),
        move_ids: [...attackerMoveSet.move_ids],
      },
      defender: {
        ...fixedSideInput(defender),
        move_ids: [...defenderMoveSet.move_ids],
      },
      attacker_policy: 'uniform-random',
      defender_policy: 'uniform-random',
      limits: {
        max_nodes: 50_000,
        max_edges: 300_000,
        max_turns: 20,
      },
    });
    summary.value = result.summary;
    graphHandle.value = result.exploration;
    activeExploration.value = null;
    treeScreenOpen.value = false;
  } catch (caught) {
    workflowError.value = caught instanceof Error ? caught.message : '固定配置推演失败';
  } finally {
    inferenceLoading.value = false;
  }
}

/** 把精确概率格式化为百分比，并保留分数作为 title。 */
function probabilityLabel(value: { percent: number }): string {
  return `${value.percent.toFixed(2)}%`;
}

const selectionFingerprint = computed(() =>
  JSON.stringify({
    ruleset_id: rulesetId.value,
    version_group_id: versionGroupId.value,
    calculation_revision: calculationRevision.value,
    attacker: {
      pokemon_id: attacker.pokemon?.pokemon_id ?? null,
      form_id: attacker.formId,
      level: attacker.level,
      stat_profile_id: attacker.statPreset,
      ability_identifier: attacker.abilityIdentifier,
      item_identifier: attacker.itemIdentifier,
      move_ids: attacker.selectedMoveIds,
    },
    defender: {
      pokemon_id: defender.pokemon?.pokemon_id ?? null,
      form_id: defender.formId,
      level: defender.level,
      stat_profile_id: defender.statPreset,
      ability_identifier: defender.abilityIdentifier,
      item_identifier: defender.itemIdentifier,
      move_ids: defender.selectedMoveIds,
    },
  }),
);

const reportContext = computed(() =>
  summary.value === null
    ? null
    : createBattleReportPresenterContext(summary.value),
);

/**
 * 保存图浏览器当前 cursor 对应的探索 DTO，供右侧战报面板同步展示。
 *
 * @param exploration 服务端返回的当前节点、分支组和结构化战报；null 表示图尚未加载。
 */
function updateActiveExploration(
  exploration: BattleGraphExplorationResult | null,
): void {
  activeExploration.value = exploration;
}

/**
 * 使用当前固定技能组重新求解完整图，刷新 graph TTL 和探索根节点。
 */
function rerunCurrentFixedInference(): void {
  void runFixedInference();
}

/** 打开占满视口的从左到右树状探索模式。 */
function openTreeScreen(): void {
  treeScreenOpen.value = true;
}

/** 关闭大屏树状探索模式，保留当前固定配置摘要和小窗探索入口。 */
function closeTreeScreen(): void {
  treeScreenOpen.value = false;
}

watch(selectionFingerprint, () => {
  // 任一固定字段或候选池变化后，旧组合和旧概率已不再对应当前快照，必须显式失效。
  combinations.value = null;
  selectedAttackerMoveSetId.value = null;
  selectedDefenderMoveSetId.value = null;
  summary.value = null;
  graphHandle.value = null;
  activeExploration.value = null;
  treeScreenOpen.value = false;
});
</script>

<template>
  <main class="app-shell battle-configuration-view">
    <header class="battle-configuration-hero">
      <div>
        <p class="battle-configuration-eyebrow">FIXED 1V1 INFERENCE</p>
        <h1>固定配置精确推演</h1>
        <p>
          先从候选池生成规范化四技能组合，再由你为双方各选择一组；系统只精确求解这一个固定配置快照。
        </p>
      </div>
      <div class="battle-configuration-hero__badge">
        <span>当前主线</span>
        <strong>组合枚举 · 单配置求解</strong>
        <small>批量配置空间暂不作为默认产品入口</small>
      </div>
    </header>

    <section class="battle-context-panel" aria-label="推演规则上下文">
      <div class="battle-context-field">
        <span>ruleset_id</span>
        <strong>{{ rulesetId }}</strong>
      </div>
      <label class="battle-context-field">
        <span>version_group_id</span>
        <select v-model.number="versionGroupId">
          <option
            v-for="supportedVersionGroupId in SUPPORTED_VERSION_GROUPS"
            :key="supportedVersionGroupId"
            :value="supportedVersionGroupId"
          >
            {{ supportedVersionGroupId }}
          </option>
        </select>
      </label>
      <div class="battle-context-field battle-context-field--revision">
        <span>calculation_revision</span>
        <strong>{{ calculationRevision }}</strong>
      </div>
      <button
        class="battle-example-button"
        type="button"
        @click="applyDragoniteVsWeavilePreset"
      >
        载入快龙 vs 玛纽拉示例
      </button>
    </section>

    <p v-if="selectionNotice" class="battle-configuration-notice" role="status">
      {{ selectionNotice }}
    </p>

    <section class="battle-side-grid">
      <BattleSideConfigurationPanel
        side="attacker"
        title="攻击方"
        :ruleset-id="rulesetId"
        :pokemon="attacker.pokemon"
        :recent-pokemon="recentPokemon"
        :presets="attackerPresets"
        :stat-preset="attacker.statPreset"
        :form-id="attacker.formId"
        :level="attacker.level"
        :ability-identifier="attacker.abilityIdentifier"
        :item-identifier="attacker.itemIdentifier"
        :candidate-moves="attacker.candidateMoves"
        :selected-move-ids="attacker.selectedMoveIds"
        :moves-loading="attacker.movesLoading"
        :remaining-global-slots="remainingGlobalSlots"
        @select-pokemon="selectPokemon('attacker', $event)"
        @update-stat-preset="attacker.statPreset = $event"
        @update-form-id="attacker.formId = $event"
        @update-level="attacker.level = $event"
        @update-ability-identifier="attacker.abilityIdentifier = $event"
        @update-item-identifier="attacker.itemIdentifier = $event"
        @update-selected-move-ids="updateSelectedMoveIds('attacker', $event)"
      />

      <BattleSideConfigurationPanel
        side="defender"
        title="防守方"
        :ruleset-id="rulesetId"
        :pokemon="defender.pokemon"
        :recent-pokemon="recentPokemon"
        :presets="defenderPresets"
        :stat-preset="defender.statPreset"
        :form-id="defender.formId"
        :level="defender.level"
        :ability-identifier="defender.abilityIdentifier"
        :item-identifier="defender.itemIdentifier"
        :candidate-moves="defender.candidateMoves"
        :selected-move-ids="defender.selectedMoveIds"
        :moves-loading="defender.movesLoading"
        :remaining-global-slots="remainingGlobalSlots"
        @select-pokemon="selectPokemon('defender', $event)"
        @update-stat-preset="defender.statPreset = $event"
        @update-form-id="defender.formId = $event"
        @update-level="defender.level = $event"
        @update-ability-identifier="defender.abilityIdentifier = $event"
        @update-item-identifier="defender.itemIdentifier = $event"
        @update-selected-move-ids="updateSelectedMoveIds('defender', $event)"
      />
    </section>

    <p v-if="attacker.error" class="error">攻击方：{{ attacker.error }}</p>
    <p v-if="defender.error" class="error">防守方：{{ defender.error }}</p>

    <section class="battle-budget-panel" aria-label="候选技能组合预算">
      <div class="battle-budget-panel__heading">
        <div>
          <p class="battle-configuration-eyebrow">MOVE SET COMBINATIONS</p>
          <h2>先枚举，不自动执行</h2>
        </div>
        <button
          class="primary-button"
          type="button"
          :disabled="!canSubmit || combinationLoading"
          @click="generateCombinations"
        >
          {{ combinationLoading ? '正在校验并生成' : '生成技能组合' }}
        </button>
      </div>
      <div class="battle-budget-grid">
        <article>
          <span>攻击方候选</span>
          <strong>{{ formatCount(budget.attacker_candidate_count) }}</strong>
          <small>{{ formatCount(budget.attacker_move_set_count) }} 个技能组</small>
        </article>
        <article>
          <span>防守方候选</span>
          <strong>{{ formatCount(budget.defender_candidate_count) }}</strong>
          <small>{{ formatCount(budget.defender_move_set_count) }} 个技能组</small>
        </article>
        <article class="battle-budget-grid__primary">
          <span>理论配置对</span>
          <strong>{{ formatCount(budget.configuration_pair_count) }}</strong>
          <small>这里只计数，不会创建同等数量的 worker case</small>
        </article>
      </div>
      <ul v-if="validationMessages.length" class="battle-validation-list">
        <li v-for="message in validationMessages" :key="message">{{ message }}</li>
      </ul>
    </section>

    <section v-if="combinations" class="move-set-selection" aria-label="技能组合选择">
      <div class="move-set-selection__heading">
        <div>
          <p class="battle-configuration-eyebrow">SELECT ONE SNAPSHOT</p>
          <h2>双方各选择一个固定技能组</h2>
        </div>
        <span class="state-pill">
          {{ combinations.attacker.move_set_count }} ×
          {{ combinations.defender.move_set_count }} =
          {{ combinations.configuration_pair_count }}
        </span>
      </div>

      <div class="move-set-selection__grid">
        <fieldset class="move-set-list">
          <legend>攻击方 · {{ combinations.attacker.pokemon_name }}</legend>
          <label
            v-for="moveSet in combinations.attacker.move_sets"
            :key="moveSet.move_set_id"
            class="move-set-option"
          >
            <input
              v-model="selectedAttackerMoveSetId"
              type="radio"
              name="attacker-move-set"
              :value="moveSet.move_set_id"
            />
            <span>{{ moveSet.move_names.join(' / ') }}</span>
            <small>{{ moveSet.move_ids.join(', ') }}</small>
          </label>
        </fieldset>

        <fieldset class="move-set-list">
          <legend>防守方 · {{ combinations.defender.pokemon_name }}</legend>
          <label
            v-for="moveSet in combinations.defender.move_sets"
            :key="moveSet.move_set_id"
            class="move-set-option"
          >
            <input
              v-model="selectedDefenderMoveSetId"
              type="radio"
              name="defender-move-set"
              :value="moveSet.move_set_id"
            />
            <span>{{ moveSet.move_names.join(' / ') }}</span>
            <small>{{ moveSet.move_ids.join(', ') }}</small>
          </label>
        </fieldset>
      </div>

      <div class="fixed-inference-action">
        <div>
          <strong>行动策略：uniform-random / uniform-random</strong>
          <small>胜率表示双方每回合在当前全部合法行动中等概率选择。</small>
        </div>
        <button
          class="primary-button"
          type="button"
          :disabled="
            selectedAttackerMoveSetId === null ||
            selectedDefenderMoveSetId === null ||
            inferenceLoading
          "
          @click="runFixedInference"
        >
          {{ inferenceLoading ? '正在精确求解并保存图' : '运行这个固定配置' }}
        </button>
      </div>
    </section>

    <p v-if="workflowError" class="error fixed-workflow-error" role="alert">
      {{ workflowError }}
    </p>

    <section v-if="summary" class="fixed-summary" aria-label="固定配置精确结果">
      <div class="fixed-summary__heading">
        <div>
          <p class="battle-configuration-eyebrow">EXACT SUMMARY</p>
          <h2>{{ summary.attacker.name }} vs {{ summary.defender.name }}</h2>
        </div>
        <span class="state-pill">{{ summary.completeness.solver_status }}</span>
      </div>

      <div class="fixed-summary__probabilities">
        <article>
          <span>攻击方胜</span>
          <strong>{{ probabilityLabel(summary.win_probability) }}</strong>
          <small>
            {{ summary.win_probability.numerator }} /
            {{ summary.win_probability.denominator }}
          </small>
        </article>
        <article>
          <span>防守方胜</span>
          <strong>{{ probabilityLabel(summary.loss_probability) }}</strong>
          <small>
            {{ summary.loss_probability.numerator }} /
            {{ summary.loss_probability.denominator }}
          </small>
        </article>
        <article>
          <span>平局</span>
          <strong>{{ probabilityLabel(summary.draw_probability) }}</strong>
          <small>
            {{ summary.draw_probability.numerator }} /
            {{ summary.draw_probability.denominator }}
          </small>
        </article>
        <article>
          <span>期望回合</span>
          <strong>
            {{ summary.expected_turns.decimal?.toFixed(2) ?? '不可用' }}
          </strong>
          <small>{{ summary.attacker_policy }} / {{ summary.defender_policy }}</small>
        </article>
      </div>

      <dl class="fixed-summary__metadata">
        <div>
          <dt>图规模</dt>
          <dd>
            {{ formatCount(summary.graph.unique_state_count) }} nodes ·
            {{ formatCount(summary.graph.edge_count) }} edges
          </dd>
        </div>
        <div>
          <dt>双方技能</dt>
          <dd>
            {{ summary.attacker.move_names.join(' / ') }}<br />
            {{ summary.defender.move_names.join(' / ') }}
          </dd>
        </div>
        <div>
          <dt>完整性</dt>
          <dd>
            {{ summary.completeness.graph_complete ? '完整精确解' : '未完成' }}
          </dd>
        </div>
      </dl>
    </section>

    <section
      v-if="graphHandle && reportContext"
      class="fixed-exploration-layout"
      aria-label="固定配置树状探索与逐回合战报"
    >
      <div class="fixed-exploration-pane">
        <div class="fixed-exploration-pane__toolbar">
          <div>
            <p class="battle-configuration-eyebrow">GRAPH EXPLORATION</p>
            <strong>当前页内小窗</strong>
          </div>
          <button type="button" class="secondary-button" @click="openTreeScreen">
            打开大屏树状图
          </button>
        </div>
        <BattleGraphExplorer
          :key="graphHandle.graph_id"
          :handle="graphHandle"
          @rerun="rerunCurrentFixedInference"
          @exploration-change="updateActiveExploration"
        />
      </div>
      <BattleReportPanel
        :report="activeExploration?.battle_report ?? null"
        :context="reportContext"
      />
    </section>

    <BattleGraphTreeScreen
      v-if="treeScreenOpen && graphHandle && reportContext"
      :handle="graphHandle"
      :context="reportContext"
      @close="closeTreeScreen"
      @rerun="rerunCurrentFixedInference"
    />
  </main>
</template>

<style scoped>
.move-set-selection,
.fixed-summary {
  background: var(--surface, #fff);
  border: 1px solid var(--border, #d9dee8);
  border-radius: 18px;
  margin-top: 24px;
  padding: 24px;
}

.move-set-selection__heading,
.fixed-summary__heading,
.fixed-inference-action {
  align-items: center;
  display: flex;
  gap: 16px;
  justify-content: space-between;
}

.move-set-selection__grid {
  display: grid;
  gap: 18px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 18px;
}

.move-set-list {
  border: 1px solid var(--border, #d9dee8);
  border-radius: 14px;
  display: grid;
  gap: 8px;
  max-height: 360px;
  min-width: 0;
  overflow: auto;
  padding: 12px;
}

.move-set-list legend {
  font-weight: 700;
  padding: 0 6px;
}

.move-set-option {
  align-items: start;
  border: 1px solid transparent;
  border-radius: 10px;
  cursor: pointer;
  display: grid;
  gap: 3px 8px;
  grid-template-columns: auto minmax(0, 1fr);
  padding: 10px;
}

.move-set-option:has(input:checked) {
  background: #eef5ff;
  border-color: #6b9be8;
}

.move-set-option input {
  grid-row: 1 / span 2;
  margin-top: 3px;
}

.move-set-option small,
.fixed-inference-action small {
  color: #667085;
}

.fixed-inference-action {
  border-top: 1px solid var(--border, #d9dee8);
  margin-top: 18px;
  padding-top: 18px;
}

.fixed-inference-action > div {
  display: grid;
  gap: 4px;
}

.fixed-workflow-error {
  margin-top: 18px;
}

.fixed-summary__probabilities {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 18px;
}

.fixed-summary__probabilities article {
  border: 1px solid var(--border, #d9dee8);
  border-radius: 12px;
  display: grid;
  gap: 6px;
  padding: 16px;
}

.fixed-summary__probabilities strong {
  font-size: 1.6rem;
}

.fixed-summary__metadata {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin: 18px 0 0;
}

.fixed-summary__metadata div {
  background: #f7f8fa;
  border-radius: 10px;
  padding: 12px;
}

.fixed-summary__metadata dt {
  color: #667085;
  font-size: 0.8rem;
  margin-bottom: 5px;
}

.fixed-summary__metadata dd {
  margin: 0;
}

.fixed-exploration-layout {
  align-items: start;
  display: grid;
  gap: 18px;
  grid-template-columns: minmax(0, 1.4fr) minmax(320px, 0.9fr);
  margin-top: 24px;
}

.fixed-exploration-pane {
  min-width: 0;
}

.fixed-exploration-pane__toolbar {
  align-items: center;
  display: flex;
  gap: 16px;
  justify-content: space-between;
  margin-bottom: 12px;
}

.fixed-exploration-pane__toolbar p {
  margin: 0 0 4px;
}

.secondary-button {
  background: #fff;
  border: 1px solid #cbd7d0;
  border-radius: 10px;
  color: #183d31;
  cursor: pointer;
  font-weight: 800;
  padding: 10px 14px;
}

.secondary-button:hover {
  border-color: #86a895;
  background: #f3f8f5;
}

.fixed-exploration-layout :deep(.battle-graph-explorer) {
  margin-top: 0;
}

@media (max-width: 760px) {
  .move-set-selection__grid,
  .fixed-summary__probabilities,
  .fixed-summary__metadata,
  .fixed-exploration-layout {
    grid-template-columns: 1fr;
  }

  .move-set-selection__heading,
  .fixed-summary__heading,
  .fixed-inference-action {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
