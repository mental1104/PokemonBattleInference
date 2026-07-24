<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import {
  advanceBattleExploration,
  backtrackBattleExploration,
  exploreBattleGraph,
  inferDragoniteVsWeavile,
  loadTransitionGroupOutcomes,
  type BattleGraphExplorationResult,
  type BattleGraphRequestContext,
  type BattleJourneyResult,
  type DragoniteAbility,
  type RepresentativePathResult,
  type TransitionGroupResult,
  type WeavilePlan,
} from '../api/inference';
import BattlePathExplorer from '../components/inference/BattlePathExplorer.vue';
import BattleReportPanel from '../components/inference/BattleReportPanel.vue';
import {
  createBattleReportPresenterContext,
  type BattleReportPresenterContext,
} from '../presenters/battleEventPresenter';

const dragoniteAbility = ref<DragoniteAbility>('multiscale');
const weavilePlan = ref<WeavilePlan>('ice-punch');
const loading = ref(false);
const explorationLoading = ref(false);
const errorMessage = ref('');
const explorationError = ref('');
const result = ref<BattleJourneyResult | null>(null);
const exploration = ref<BattleGraphExplorationResult | null>(null);
const expandedGroups = ref<Record<string, TransitionGroupResult>>({});
const showExplorer = ref(true);
let requestGeneration = 0;

const summary = computed(() => result.value?.summary ?? null);
const presenterContext = computed<BattleReportPresenterContext | null>(() =>
  summary.value === null
    ? null
    : createBattleReportPresenterContext(summary.value),
);
const moveNames = computed<Readonly<Record<number, string>>>(
  () => presenterContext.value?.moveNames ?? {},
);

const scenarioSummary = computed(() => {
  const ability = dragoniteAbility.value === 'multiscale' ? '多重鳞片' : '精神力';
  const plan =
    weavilePlan.value === 'ice-punch'
      ? '玛纽拉固定使用冰冻拳'
      : '玛纽拉在击掌奇袭与冰冻拳间等概率选择';
  return `快龙采用${ability}，${plan}`;
});

/**
 * 清空上一组配置的 summary、cursor、展开分支和逐回合战报。
 *
 * 该状态归父视图所有；左侧 explorer 组件即使卸载，也不会单独销毁右侧 report。
 */
function clearSolvedState(): void {
  requestGeneration += 1;
  result.value = null;
  exploration.value = null;
  expandedGroups.value = {};
  errorMessage.value = '';
  explorationError.value = '';
  showExplorer.value = true;
}

/**
 * 把首次推演 handle 或当前 exploration 组合成下一次 API 请求上下文。
 *
 * @param journey 当前已保存图的首次推演结果。
 * @param current 当前服务端校验过的 exploration；根加载前为 null。
 * @returns 图 ID、计算版本和真实 edge cursor；缺少 journey 时返回 null。
 */
function graphContext(
  journey: BattleJourneyResult | null,
  current: BattleGraphExplorationResult | null,
): BattleGraphRequestContext | null {
  if (journey === null) {
    return null;
  }
  return {
    graphId: journey.exploration.graph_id,
    calculationRevision: journey.exploration.calculation_revision,
    cursor: current?.cursor ?? journey.exploration.cursor,
  };
}

/**
 * 为并发保护生成不包含 BattleState 的稳定 cursor key。
 *
 * @param current 当前真实 edge 序列。
 * @returns 可用于比较请求前后 cursor 是否仍一致的 JSON 字符串。
 */
function cursorKey(current: BattleGraphExplorationResult | null): string {
  return JSON.stringify(current?.cursor.steps ?? []);
}

/**
 * 提交当前受控场景，并在成功后立即加载根节点与空 cursor 战报。
 */
async function runInference(): Promise<void> {
  const generation = requestGeneration + 1;
  requestGeneration = generation;
  result.value = null;
  exploration.value = null;
  expandedGroups.value = {};
  errorMessage.value = '';
  explorationError.value = '';
  showExplorer.value = true;
  loading.value = true;

  try {
    const journey = await inferDragoniteVsWeavile({
      dragonite_ability: dragoniteAbility.value,
      weavile_plan: weavilePlan.value,
      dragonite_stat_preset: 'max_atk_plus',
      weavile_stat_preset: 'max_atk_plus',
    });
    if (generation !== requestGeneration) {
      return;
    }
    result.value = journey;

    const context = graphContext(journey, null);
    if (context === null) {
      return;
    }
    explorationLoading.value = true;
    try {
      const root = await exploreBattleGraph(context);
      if (generation === requestGeneration) {
        exploration.value = root;
      }
    } catch (error) {
      if (generation === requestGeneration) {
        explorationError.value =
          error instanceof Error ? error.message : '根节点探索请求失败';
      }
    } finally {
      if (generation === requestGeneration) {
        explorationLoading.value = false;
      }
    }
  } catch (error) {
    if (generation === requestGeneration) {
      result.value = null;
      errorMessage.value =
        error instanceof Error ? error.message : '推演请求失败';
    }
  } finally {
    if (generation === requestGeneration) {
      loading.value = false;
    }
  }
}

/**
 * 按需加载当前节点一个 group 的正式 outcomes。
 *
 * @param groupId 当前 exploration 返回的稳定分支组 ID。
 */
async function expandTransitionGroup(groupId: string): Promise<void> {
  const context = graphContext(result.value, exploration.value);
  if (context === null || expandedGroups.value[groupId] !== undefined) {
    return;
  }

  const beforeCursor = cursorKey(exploration.value);
  explorationLoading.value = true;
  explorationError.value = '';
  try {
    const response = await loadTransitionGroupOutcomes(context, groupId);
    // 当前 cursor 已被其他操作替换时丢弃旧 group 响应，避免跨节点污染。
    if (beforeCursor !== cursorKey(exploration.value)) {
      return;
    }
    expandedGroups.value = {
      ...expandedGroups.value,
      [groupId]: response.transition_group,
    };
  } catch (error) {
    explorationError.value =
      error instanceof Error ? error.message : '分支展开失败';
  } finally {
    explorationLoading.value = false;
  }
}

/**
 * 沿用户选择的正式 edge 前进，并整体替换 cursor、节点、groups 和 battle report。
 *
 * @param edgeId 当前 group outcome 返回的正式 edge ID。
 */
async function advancePath(edgeId: number): Promise<void> {
  const context = graphContext(result.value, exploration.value);
  if (context === null) {
    return;
  }

  explorationLoading.value = true;
  explorationError.value = '';
  try {
    exploration.value = await advanceBattleExploration(context, edgeId);
    expandedGroups.value = {};
  } catch (error) {
    explorationError.value =
      error instanceof Error ? error.message : '路径前进失败';
  } finally {
    explorationLoading.value = false;
  }
}

/**
 * 返回上一级，或截断到 breadcrumb 指定的祖先深度。
 *
 * @param depth 目标祖先深度；省略时返回上一级。
 */
async function backtrackPath(depth?: number): Promise<void> {
  const context = graphContext(result.value, exploration.value);
  if (context === null) {
    return;
  }

  explorationLoading.value = true;
  explorationError.value = '';
  try {
    exploration.value = await backtrackBattleExploration(context, depth);
    expandedGroups.value = {};
  } catch (error) {
    explorationError.value =
      error instanceof Error ? error.message : '路径回退失败';
  } finally {
    explorationLoading.value = false;
  }
}

/**
 * 把 API 百分比统一格式化为两位小数。
 *
 * @param value 后端返回的百分比数值。
 * @returns 带百分号的展示文本。
 */
function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`;
}

/**
 * 把英文机制标识转换为页面短标签。
 *
 * @param identifier 后端稳定 identifier。
 * @returns 用户可读的中文优先标签。
 */
function displayIdentifier(identifier: string): string {
  const normalized = identifier.replaceAll('-', '_');
  const labels: Record<string, string> = {
    multiscale: '多重鳞片',
    inner_focus: '精神力',
    pressure: '压迫感（中性假设）',
    none: '无道具',
    brick_break: '劈瓦',
    ice_punch: '冰冻拳',
    fake_out: '击掌奇袭',
  };
  return labels[normalized] ?? normalized.replaceAll('_', ' ');
}

/**
 * 返回代表路径终局的中文说明。
 *
 * @param path 后端重建的代表路径。
 * @returns 绝对战斗侧对应的终局标签。
 */
function pathOutcomeLabel(path: RepresentativePathResult): string {
  if (path.outcome === 'attacker-win') {
    return '快龙获胜路径';
  }
  if (path.outcome === 'defender-win') {
    return '玛纽拉获胜路径';
  }
  return '平局路径';
}

watch([dragoniteAbility, weavilePlan], () => {
  if (result.value !== null || loading.value) {
    clearSolvedState();
    loading.value = false;
    explorationLoading.value = false;
  }
});
</script>

<template>
  <main class="inference-shell">
    <header class="inference-hero">
      <div>
        <p class="eyebrow">1v1 MULTI-TURN INFERENCE</p>
        <h1>战斗推演实验室</h1>
        <p class="hero-copy">
          独立于单次伤害计算器，从 version-aware 配置开始，完整经过选招策略、回合推进、状态图去重与精确概率求解。
        </p>
      </div>
      <div class="scope-badge">
        <span>当前旅程</span>
        <strong>快龙 vs 玛纽拉</strong>
        <small>Champion · Lv.50 · 不换人</small>
      </div>
    </header>

    <section class="journey-grid">
      <article class="journey-card journey-card--dragonite">
        <div class="journey-step">01</div>
        <p class="eyebrow">DRAGONITE</p>
        <h2>选择快龙的关键特性</h2>
        <p>固定使用劈瓦，比较满血减伤与防畏缩对完整战斗路径的影响。</p>
        <label class="choice-tile" :class="{ 'choice-tile--active': dragoniteAbility === 'multiscale' }">
          <input v-model="dragoniteAbility" type="radio" value="multiscale" />
          <span>
            <strong>多重鳞片</strong>
            <small>满 HP 时降低受到的伤害，观察能否扛住冰冻拳后反击。</small>
          </span>
        </label>
        <label class="choice-tile" :class="{ 'choice-tile--active': dragoniteAbility === 'inner-focus' }">
          <input v-model="dragoniteAbility" type="radio" value="inner-focus" />
          <span>
            <strong>精神力</strong>
            <small>阻止击掌奇袭施加畏缩，观察同回合劈瓦反击路径。</small>
          </span>
        </label>
      </article>

      <article class="journey-card journey-card--weavile">
        <div class="journey-step">02</div>
        <p class="eyebrow">WEAVILE</p>
        <h2>选择玛纽拉的行动假设</h2>
        <p>策略概率与命中、伤害乱数分开建模，最终在状态图边上组合。</p>
        <label class="choice-tile" :class="{ 'choice-tile--active': weavilePlan === 'ice-punch' }">
          <input v-model="weavilePlan" type="radio" value="ice-punch" />
          <span>
            <strong>冰冻拳直攻</strong>
            <small>唯一合法招式，适合观察纯伤害与多重鳞片的胜负分支。</small>
          </span>
        </label>
        <label
          class="choice-tile"
          :class="{ 'choice-tile--active': weavilePlan === 'fake-out-pressure' }"
        >
          <input v-model="weavilePlan" type="radio" value="fake-out-pressure" />
          <span>
            <strong>击掌奇袭施压</strong>
            <small>击掌奇袭与冰冻拳等概率选择，形成畏缩、失败重试与终局路径。</small>
          </span>
        </label>
      </article>

      <article class="journey-card journey-card--run">
        <div class="journey-step">03</div>
        <p class="eyebrow">SOLVE</p>
        <h2>构建并求解状态图</h2>
        <p class="scenario-summary">{{ scenarioSummary }}</p>
        <ul class="assumption-list">
          <li>双方 Lv.50，极攻预设，满 HP / 满 PP 开局</li>
          <li>不换人，不启用太晶、Mega 或极巨化</li>
          <li>概率使用 Fraction 精确求解，不进行 Monte Carlo 抽样</li>
        </ul>
        <button class="inference-run-button" type="button" :disabled="loading" @click="runInference">
          {{ loading ? '正在展开状态图…' : '开始完整推演' }}
        </button>
        <p v-if="errorMessage" class="inference-error">{{ errorMessage }}</p>
      </article>
    </section>

    <template v-if="summary">
      <section class="result-heading">
        <div>
          <p class="eyebrow">SOLVED RESULT</p>
          <h2>固定配置概率结果</h2>
        </div>
        <span class="solver-chip" :class="{ 'solver-chip--complete': summary.graph.is_complete }">
          {{ summary.completeness.solver_status }} · 覆盖 {{ formatPercent(summary.configuration_coverage_percent) }}
        </span>
      </section>

      <section class="probability-grid">
        <article class="probability-card probability-card--win">
          <span>快龙胜率</span>
          <strong>{{ formatPercent(summary.win_probability.percent) }}</strong>
          <small>{{ summary.win_probability.numerator }} / {{ summary.win_probability.denominator }}</small>
          <div class="probability-track">
            <i :style="{ width: `${summary.win_probability.percent}%` }" />
          </div>
        </article>
        <article class="probability-card probability-card--loss">
          <span>玛纽拉胜率</span>
          <strong>{{ formatPercent(summary.loss_probability.percent) }}</strong>
          <small>{{ summary.loss_probability.numerator }} / {{ summary.loss_probability.denominator }}</small>
          <div class="probability-track">
            <i :style="{ width: `${summary.loss_probability.percent}%` }" />
          </div>
        </article>
        <article class="probability-card">
          <span>平局概率</span>
          <strong>{{ formatPercent(summary.draw_probability.percent) }}</strong>
          <small>{{ summary.draw_probability.numerator }} / {{ summary.draw_probability.denominator }}</small>
          <div class="probability-track">
            <i :style="{ width: `${summary.draw_probability.percent}%` }" />
          </div>
        </article>
        <article class="probability-card">
          <span>期望回合</span>
          <strong>{{ summary.expected_turns.decimal?.toFixed(2) ?? '∞ / 不可用' }}</strong>
          <small>策略与战斗随机共同决定</small>
        </article>
      </section>

      <section class="inference-detail-grid">
        <article class="configuration-panel">
          <div class="panel-title">
            <span>快龙</span>
            <small>观察方 · {{ summary.attacker_policy }}</small>
          </div>
          <dl>
            <div><dt>特性</dt><dd>{{ displayIdentifier(summary.attacker.ability_identifier) }}</dd></div>
            <div><dt>道具</dt><dd>{{ displayIdentifier(summary.attacker.item_identifier) }}</dd></div>
            <div><dt>招式</dt><dd>{{ summary.attacker.move_names.join(' / ') }}</dd></div>
            <div><dt>HP / 攻击 / 速度</dt><dd>{{ summary.attacker.stats.hp }} / {{ summary.attacker.stats.attack }} / {{ summary.attacker.stats.speed }}</dd></div>
          </dl>
        </article>
        <article class="configuration-panel">
          <div class="panel-title">
            <span>玛纽拉</span>
            <small>{{ summary.defender_policy }}</small>
          </div>
          <dl>
            <div><dt>特性</dt><dd>{{ displayIdentifier(summary.defender.ability_identifier) }}</dd></div>
            <div><dt>道具</dt><dd>{{ displayIdentifier(summary.defender.item_identifier) }}</dd></div>
            <div><dt>招式</dt><dd>{{ summary.defender.move_names.join(' / ') }}</dd></div>
            <div><dt>HP / 攻击 / 速度</dt><dd>{{ summary.defender.stats.hp }} / {{ summary.defender.stats.attack }} / {{ summary.defender.stats.speed }}</dd></div>
          </dl>
        </article>
        <article class="graph-panel">
          <div class="panel-title">
            <span>状态图</span>
            <small>{{ summary.graph.is_complete ? '完整' : '已截断' }}</small>
          </div>
          <div class="graph-metrics">
            <div><strong>{{ summary.graph.unique_state_count }}</strong><span>唯一状态</span></div>
            <div><strong>{{ summary.graph.edge_count }}</strong><span>概率边</span></div>
            <div><strong>{{ summary.graph.max_turn_number }}</strong><span>最大回合</span></div>
            <div><strong>{{ summary.graph.terminal_reachable_cycle_count }}</strong><span>可出循环</span></div>
          </div>
        </article>
      </section>

      <section class="battle-exploration-section">
        <div class="result-heading result-heading--compact">
          <div>
            <p class="eyebrow">LIVE EXPLORATION</p>
            <h2>沿概率路径查看真实战报</h2>
          </div>
          <button
            v-if="exploration"
            class="battle-explorer-visibility"
            type="button"
            data-toggle-explorer
            @click="showExplorer = !showExplorer"
          >
            {{ showExplorer ? '隐藏路径面板' : '显示路径面板' }}
          </button>
        </div>

        <p v-if="explorationLoading && !exploration" class="battle-exploration-loading">
          正在加载根节点与空 cursor…
        </p>
        <p v-if="explorationError && !exploration" class="battle-exploration-error">
          {{ explorationError }}
        </p>

        <div
          v-if="exploration && presenterContext"
          class="battle-exploration-grid"
          :class="{ 'battle-exploration-grid--report-only': !showExplorer }"
        >
          <BattlePathExplorer
            v-if="showExplorer"
            :exploration="exploration"
            :expanded-groups="expandedGroups"
            :loading="explorationLoading"
            :error="explorationError"
            :move-names="moveNames"
            @expand-group="expandTransitionGroup"
            @advance="advancePath"
            @backtrack="backtrackPath()"
            @truncate="backtrackPath"
          />
          <BattleReportPanel
            :report="exploration.battle_report"
            :context="presenterContext"
            :loading="explorationLoading"
            :error="explorationError"
          />
        </div>
      </section>

      <section class="path-section">
        <div class="result-heading result-heading--compact">
          <div>
            <p class="eyebrow">REPRESENTATIVE PATHS</p>
            <h2>代表性终局路径</h2>
          </div>
        </div>
        <div class="path-grid">
          <article v-for="path in summary.representative_paths" :key="path.reference" class="path-card">
            <div class="panel-title">
              <span>{{ pathOutcomeLabel(path) }}</span>
              <small>{{ path.steps.length }} 个状态节点</small>
            </div>
            <ol>
              <li v-for="step in path.steps" :key="step.node_id">
                <div>
                  <strong>Turn {{ step.turn_number }}</strong>
                  <span>快龙 {{ step.attacker_hp }} HP · 玛纽拉 {{ step.defender_hp }} HP</span>
                </div>
                <small>{{ step.events.join(' · ') || step.phase }}</small>
              </li>
            </ol>
          </article>
        </div>
      </section>

      <section class="coverage-panel">
        <div>
          <p class="eyebrow">MECHANISM COVERAGE</p>
          <h2>机制覆盖与解释边界</h2>
          <p>未支持能力不会被静默吞掉；结果只对已纳入机制和明确中性假设成立。</p>
        </div>
        <div class="coverage-columns">
          <div>
            <strong>已纳入</strong>
            <span v-for="item in summary.included_mechanisms" :key="item">{{ item }}</span>
          </div>
          <div>
            <strong>未纳入</strong>
            <span v-for="item in summary.excluded_mechanisms" :key="item">{{ item }}</span>
            <span v-if="summary.excluded_mechanisms.length === 0">无</span>
          </div>
        </div>
        <ul v-if="summary.completeness.warnings.length" class="warning-list">
          <li v-for="warning in summary.completeness.warnings" :key="warning">{{ warning }}</li>
        </ul>
      </section>
    </template>
  </main>
</template>

<style src="../battle-report.css"></style>
