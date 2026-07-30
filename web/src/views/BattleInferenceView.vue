<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import type { PokemonSearchItem } from '../api/calculator';
import { SUPPORTED_VERSION_GROUPS } from '../api/configurationSpace';
import {
  cancelInferenceJob,
  createFixedBattleJob,
  enumerateMoveSetCombinations,
  listFixedBattleJobs,
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
import type { BattleReportPresenterContext } from '../presenters/battleEventPresenter';
import type {
  FixedBattleSideInput,
  FixedBattleSummaryRequest,
  FixedBattleSummaryResult,
  InferenceJobSummary,
  MoveSetCombinationsResult,
  MoveSetOptionResult,
} from '../types/fixedBattle';
import './BattleInferenceView.css';

const emit = defineEmits<{
  /** 请求宿主页面打开稳定 URL 的任务详情。 */
  openJob: [jobId: string];
}>();

const configuration = useBattleInferenceConfiguration();
const {
  rulesetId,
  versionGroupId,
  calculationRevision,
  attacker,
  defender,
  selectionNotice,
  budget,
  remainingGlobalSlots,
  validationMessages,
  canSubmit,
  selectPokemon: selectConfigurationPokemon,
  updateSelectedMoveIds,
  applyDragoniteMirrorDragonClawPreset,
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
const snapshotRequest = ref<FixedBattleSummaryRequest | null>(null);
const activeExploration = ref<BattleGraphExplorationResult | null>(null);
const treeScreenOpen = ref(false);
const taskPanelOpen = ref(false);
const taskLoading = ref(false);
const taskMessage = ref<string | null>(null);
const taskError = ref<string | null>(null);
const fixedJobs = ref<InferenceJobSummary[]>([]);
let taskPollTimer: ReturnType<typeof setInterval> | null = null;
let taskRequestActive = false;

/** 初始化能力值模板；候选池会在选择 Pokémon 后按侧加载。 */
onMounted(() => {
  void refreshTaskPanel();
  startTaskPolling();
});

/** 离开固定推演页面时释放轮询 timer。 */
onUnmounted(() => {
  stopTaskPolling();
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

/** 对当前选中的唯一双方技能组提交异步后台任务。 */
async function runFixedInference(): Promise<void> {
  const request = currentFixedBattleRequest();
  if (request === null) return;

  inferenceLoading.value = true;
  workflowError.value = null;
  summary.value = null;
  taskMessage.value = null;
  taskError.value = null;
  try {
    snapshotRequest.value = request;
    const result = await createFixedBattleJob(request, fixedTaskIdempotencyKey());
    taskMessage.value = `已提交任务：${shortJobId(result.job_id)}`;
    taskPanelOpen.value = true;
    await refreshTaskPanel();
    activeExploration.value = null;
    treeScreenOpen.value = false;
  } catch (caught) {
    workflowError.value = caught instanceof Error ? caught.message : '固定配置任务提交失败';
  } finally {
    inferenceLoading.value = false;
  }
}

/** 根据当前双方技能组选择构造固定配置请求；选择不完整时返回 null。 */
function currentFixedBattleRequest(): FixedBattleSummaryRequest | null {
  const attackerMoveSet = selectedMoveSet('attacker');
  const defenderMoveSet = selectedMoveSet('defender');
  if (attackerMoveSet === null || defenderMoveSet === null) return null;
  return {
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
  };
}

/** 打开不依赖完整图的实时快照树状探索。 */
function openSnapshotTreeScreen(): void {
  const request = currentFixedBattleRequest();
  if (request === null) return;
  snapshotRequest.value = request;
  graphHandle.value = null;
  activeExploration.value = null;
  treeScreenOpen.value = true;
}

/** 把精确概率格式化为百分比，并保留分数作为 title。 */
function probabilityLabel(value: { percent: number }): string {
  return `${value.percent.toFixed(2)}%`;
}

/** 生成一次真实提交使用的幂等键；同一次点击不会复用旧任务。 */
function fixedTaskIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return `fixed-${crypto.randomUUID()}`;
  }
  return `fixed-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** 按固定上限刷新任务面板，不因一次失败清空已有任务。 */
async function refreshTaskPanel(): Promise<void> {
  if (taskRequestActive) return;
  taskRequestActive = true;
  taskLoading.value = fixedJobs.value.length === 0;
  try {
    const result = await listFixedBattleJobs({ limit: 20 });
    fixedJobs.value = result.items;
    taskError.value = null;
  } catch (caught) {
    taskError.value = caught instanceof Error ? caught.message : '任务列表刷新失败';
  } finally {
    taskRequestActive = false;
    taskLoading.value = false;
  }
}

/** 开始固定任务面板低频轮询。 */
function startTaskPolling(): void {
  if (taskPollTimer !== null) return;
  taskPollTimer = setInterval(() => {
    if (document.visibilityState === 'visible' && hasActiveJobs.value) {
      void refreshTaskPanel();
    }
  }, 2500);
}

/** 停止固定任务面板轮询。 */
function stopTaskPolling(): void {
  if (taskPollTimer !== null) {
    clearInterval(taskPollTimer);
    taskPollTimer = null;
  }
}

/** 请求取消指定任务并立即刷新列表。 */
async function cancelJob(job: InferenceJobSummary): Promise<void> {
  taskError.value = null;
  taskMessage.value = null;
  try {
    await cancelInferenceJob(job.job_id);
    taskMessage.value = `已请求取消：${shortJobId(job.job_id)}`;
    await refreshTaskPanel();
  } catch (caught) {
    taskError.value = caught instanceof Error ? caught.message : '取消任务失败';
  }
}

/** 返回短任务 ID，保留完整 ID 在 title 中查看。 */
function shortJobId(jobId: string): string {
  return jobId.length <= 14 ? jobId : `${jobId.slice(0, 10)}…${jobId.slice(-4)}`;
}

/** 格式化任务阶段为中文。 */
function phaseLabel(phase: string): string {
  const labels: Record<string, string> = {
    queued: '等待执行',
    preparing_battle: '准备配置',
    running: '运行中',
    building_graph: '构建状态图',
    expanding_actions: '展开动作组合',
    graph_built: '状态图完成',
    solving_probabilities: '概率求解',
    cancel_requested: '取消中',
    completed: '已完成',
    cancelled: '已取消',
    failed: '失败',
  };
  return labels[phase] ?? phase;
}

/** 格式化任务状态为中文。 */
function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: '等待执行',
    preparing: '准备中',
    running: '运行中',
    cancel_requested: '取消中',
    succeeded: '已完成',
    completed_with_failures: '部分完成',
    cancelled: '已取消',
    failed: '失败',
  };
  return labels[status] ?? status;
}

/** 格式化 ISO 时间为本地短时间。 */
function formatTime(value: string | null): string {
  if (value === null) return '—';
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value));
}

/** 返回运行时长展示文本。 */
function elapsedLabel(job: InferenceJobSummary): string {
  const seconds = job.progress.elapsed_seconds;
  if (seconds === null) return '尚未开始';
  return `${seconds.toFixed(1)} 秒`;
}

/** 返回任务卡片进度条使用的百分比。 */
function jobProgressPercent(job: InferenceJobSummary): number {
  if (job.progress.counts.total <= 0) return 0;
  const completedRatio =
    job.progress.counts.completed / job.progress.counts.total;
  const runningRatio =
    job.progress.running_case === null
      ? 0
      : job.progress.running_case.percent / 100 / job.progress.counts.total;
  return Math.min(100, Math.max(0, (completedRatio + runningRatio) * 100));
}

/** 返回任务卡片进度条旁的紧凑阶段文案。 */
function jobProgressLabel(job: InferenceJobSummary): string {
  const running = job.progress.running_case;
  if (running === null) {
    return `${job.progress.counts.completed} / ${job.progress.counts.total}`;
  }
  return `${phaseLabel(running.phase)} ${running.percent.toFixed(1)}%`;
}

/** 返回进度条 title，鼠标浮上去展示节点、边和构图队列细节。 */
function jobProgressTitle(job: InferenceJobSummary): string {
  const running = job.progress.running_case;
  if (running === null) {
    return `配置完成 ${job.progress.counts.completed} / ${job.progress.counts.total}`;
  }
  return [
    `当前 case：${shortJobId(running.configuration_id)}`,
    `阶段：${phaseLabel(running.phase)}`,
    `节点：${formatCount(running.observed_nodes)} / ${formatCount(running.node_limit)}`,
    `边：${formatCount(running.observed_edges)} / ${formatCount(running.edge_limit)}`,
    `已展开节点：${formatCount(running.expanded_nodes)}`,
    `待展开队列：${formatCount(running.frontier_nodes)}`,
    `动作组合：${formatCount(running.action_pairs_completed)} / ${formatCount(running.action_pairs_total)}`,
    `更新：${formatTime(running.updated_at)}`,
  ].join('\n');
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
    ? snapshotReportContext.value
    : createBattleReportPresenterContext(summary.value),
);

const snapshotReportContext = computed<BattleReportPresenterContext | null>(() => {
  const attackerMoveSet = selectedMoveSet('attacker');
  const defenderMoveSet = selectedMoveSet('defender');
  const result = combinations.value;
  if (attackerMoveSet === null || defenderMoveSet === null || result === null) {
    return null;
  }
  const moveNames: Record<number, string> = {};
  for (const moveSet of [attackerMoveSet, defenderMoveSet]) {
    moveSet.move_ids.forEach((moveId, index) => {
      moveNames[moveId] = moveSet.move_names[index] ?? `招式 #${moveId}`;
    });
  }
  return {
    rulesetId: rulesetId.value,
    sides: {
      attacker: {
        pokemonId: result.attacker.pokemon_id,
        name: result.attacker.pokemon_name,
        maxHp: 0,
      },
      defender: {
        pokemonId: result.defender.pokemon_id,
        name: result.defender.pokemon_name,
        maxHp: 0,
      },
    },
    moveNames,
  };
});

const activeJobCount = computed(
  () => fixedJobs.value.filter((job) => job.can_cancel).length,
);

const hasActiveJobs = computed(() => activeJobCount.value > 0);

const runningJobs = computed(() =>
  fixedJobs.value.filter((job) => ['preparing', 'running', 'cancel_requested'].includes(job.status)),
);

const queuedJobs = computed(() =>
  fixedJobs.value.filter((job) => job.status === 'pending'),
);

const terminalJobs = computed(() =>
  fixedJobs.value.filter((job) => !job.can_cancel),
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
  if (graphHandle.value !== null) {
    snapshotRequest.value = null;
  }
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
  snapshotRequest.value = null;
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
        @click="applyDragoniteMirrorDragonClawPreset"
      >
        载入双快龙龙爪示例
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
          {{ inferenceLoading ? '正在提交任务' : '提交精确推演任务' }}
        </button>
        <button
          class="secondary-button"
          type="button"
          :disabled="
            selectedAttackerMoveSetId === null ||
            selectedDefenderMoveSetId === null
          "
          @click="openSnapshotTreeScreen"
        >
          打开实时树状图
        </button>
      </div>
    </section>

    <p v-if="workflowError" class="error fixed-workflow-error" role="alert">
      {{ workflowError }}
    </p>
    <p v-if="taskMessage" class="battle-task-message" role="status">
      {{ taskMessage }}
    </p>

    <section class="battle-task-panel" aria-label="固定配置推演任务">
      <button
        class="battle-task-panel__summary"
        type="button"
        :aria-expanded="taskPanelOpen"
        @click="taskPanelOpen = !taskPanelOpen"
      >
        <span>推演任务（{{ activeJobCount }} 个运行中）</span>
        <small>{{ taskPanelOpen ? '收起' : '展开查看状态和进度' }}</small>
      </button>

      <div v-if="taskPanelOpen" class="battle-task-panel__body">
        <div class="battle-task-panel__toolbar">
          <p v-if="taskLoading">正在刷新任务列表…</p>
          <p v-else-if="taskError" class="error">{{ taskError }}</p>
          <p v-else>显示最近 {{ fixedJobs.length }} 个固定配置任务。</p>
          <button class="secondary-button" type="button" @click="refreshTaskPanel">
            刷新
          </button>
        </div>

        <template v-if="fixedJobs.length">
          <div
            v-for="group in [
              { title: '正在运行', items: runningJobs },
              { title: '等待执行', items: queuedJobs },
              { title: '最近完成 / 失败 / 取消', items: terminalJobs },
            ]"
            :key="group.title"
            class="battle-task-group"
          >
            <h3>{{ group.title }}</h3>
            <article
              v-for="job in group.items"
              :key="job.job_id"
              class="battle-task-item"
            >
              <div>
                <strong :title="job.job_id">{{ shortJobId(job.job_id) }}</strong>
                <span>{{ statusLabel(job.status) }} · {{ phaseLabel(job.phase) }}</span>
              </div>
              <div
                class="battle-task-progress"
                :title="jobProgressTitle(job)"
                :aria-label="`任务进度 ${jobProgressLabel(job)}`"
              >
                <div class="battle-task-progress__meta">
                  <span>{{ jobProgressLabel(job) }}</span>
                  <strong>{{ jobProgressPercent(job).toFixed(1) }}%</strong>
                </div>
                <div class="battle-task-progress__track">
                  <div
                    class="battle-task-progress__bar"
                    :style="{ width: `${jobProgressPercent(job)}%` }"
                  />
                </div>
              </div>
              <dl>
                <div>
                  <dt>配置</dt>
                  <dd>{{ job.progress.counts.completed }} / {{ job.progress.counts.total }}</dd>
                </div>
                <div>
                  <dt>节点</dt>
                  <dd>{{ formatCount(job.progress.state_nodes.used) }} / {{ formatCount(job.progress.state_nodes.limit) }}</dd>
                </div>
                <div>
                  <dt>边</dt>
                  <dd>{{ formatCount(job.progress.state_edges.used) }} / {{ formatCount(job.progress.state_edges.limit) }}</dd>
                </div>
                <div>
                  <dt>运行</dt>
                  <dd>{{ elapsedLabel(job) }}</dd>
                </div>
                <div>
                  <dt>更新</dt>
                  <dd>{{ formatTime(job.updated_at) }}</dd>
                </div>
              </dl>
              <div class="battle-task-item__actions">
                <button
                  class="secondary-button"
                  type="button"
                  :disabled="!job.can_cancel"
                  @click="cancelJob(job)"
                >
                  取消
                </button>
                <button
                  class="secondary-button"
                  type="button"
                  @click="emit('openJob', job.job_id)"
                >
                  查看详情
                </button>
              </div>
            </article>
          </div>
        </template>
        <p v-else class="battle-task-empty">暂无固定配置推演任务。</p>
      </div>
    </section>

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
        :node="activeExploration?.node ?? null"
      />
    </section>

    <BattleGraphTreeScreen
      v-if="treeScreenOpen && (graphHandle || snapshotRequest) && reportContext"
      :handle="graphHandle"
      :snapshot-request="snapshotRequest"
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

.battle-task-message {
  background: #eef7f2;
  border: 1px solid #bfd8ca;
  border-radius: 10px;
  color: #174232;
  font-weight: 700;
  margin: 18px 0 0;
  padding: 12px 14px;
}

.battle-task-panel {
  background: var(--surface, #fff);
  border: 1px solid var(--border, #d9dee8);
  border-radius: 14px;
  margin-top: 18px;
  overflow: hidden;
}

.battle-task-panel__summary {
  align-items: center;
  background: #fff;
  border: 0;
  cursor: pointer;
  display: flex;
  font: inherit;
  justify-content: space-between;
  padding: 16px 18px;
  width: 100%;
}

.battle-task-panel__summary span {
  color: #0b2b23;
  font-weight: 900;
}

.battle-task-panel__summary small,
.battle-task-panel__toolbar p,
.battle-task-item span,
.battle-task-item dt {
  color: #667085;
}

.battle-task-panel__body {
  border-top: 1px solid var(--border, #d9dee8);
  display: grid;
  gap: 14px;
  padding: 16px;
}

.battle-task-panel__toolbar,
.battle-task-item,
.battle-task-item__actions {
  align-items: center;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}

.battle-task-panel__toolbar p {
  margin: 0;
}

.battle-task-group {
  display: grid;
  gap: 8px;
}

.battle-task-group h3 {
  font-size: 0.95rem;
  margin: 4px 0;
}

.battle-task-item {
  border: 1px solid #dde7e1;
  border-radius: 10px;
  flex-wrap: wrap;
  padding: 12px;
}

.battle-task-item > div:first-child {
  display: grid;
  gap: 3px;
  min-width: 170px;
}

.battle-task-progress {
  display: grid;
  flex: 1 1 240px;
  gap: 6px;
  min-width: 220px;
}

.battle-task-progress__meta {
  align-items: center;
  display: flex;
  font-size: 0.8rem;
  justify-content: space-between;
}

.battle-task-progress__meta strong {
  font-size: 0.85rem;
}

.battle-task-progress__track {
  background: #e9f0ec;
  border-radius: 999px;
  height: 8px;
  overflow: hidden;
}

.battle-task-progress__bar {
  background: linear-gradient(90deg, #2f6f55, #b92b37);
  border-radius: inherit;
  height: 100%;
  transition: width 180ms ease;
}

.battle-task-item dl {
  display: grid;
  flex: 1 1 520px;
  gap: 8px;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin: 0;
}

.battle-task-item dl div {
  min-width: 0;
}

.battle-task-item dt {
  font-size: 0.75rem;
}

.battle-task-item dd {
  font-weight: 700;
  margin: 2px 0 0;
  overflow-wrap: anywhere;
}

.battle-task-empty {
  color: #667085;
  margin: 0;
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

  .battle-task-panel__toolbar,
  .battle-task-item {
    align-items: stretch;
    flex-direction: column;
  }

  .battle-task-item dl {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
