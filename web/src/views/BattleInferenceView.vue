<script setup lang="ts">
import { computed, ref } from 'vue';
import {
  inferDragoniteVsWeavile,
  type BattleGraphExplorationResult,
  type BattleJourneyResult,
  type DragoniteAbility,
  type RepresentativePathResult,
  type WeavilePlan,
} from '../api/inference';
import type { WinningPathWinner } from '../api/winningPaths';
import BattleGraphExplorer from '../components/inference/BattleGraphExplorer.vue';
import BattleReportPanel from '../components/inference/BattleReportPanel.vue';
import WinningPathGroupsPanel from '../components/inference/WinningPathGroupsPanel.vue';
import {
  createBattleReportPresenterContext,
  type BattleReportPresenterContext,
} from '../presenters/battleEventPresenter';

const dragoniteAbility = ref<DragoniteAbility>('multiscale');
const weavilePlan = ref<WeavilePlan>('ice-punch');
const loading = ref(false);
const errorMessage = ref('');
const result = ref<BattleJourneyResult | null>(null);
const activeExploration = ref<BattleGraphExplorationResult | null>(null);
const showGraphExplorer = ref(true);
const selectedWinningPathSide = ref<WinningPathWinner | null>(null);

const summary = computed(() => result.value?.summary ?? null);
const presenterContext = computed<BattleReportPresenterContext | null>(() =>
  summary.value === null
    ? null
    : createBattleReportPresenterContext(summary.value),
);
const moveNames = computed<Record<number, string>>(() => {
  const current = summary.value;
  const names: Record<number, string> = {};
  if (current === null) {
    return names;
  }
  current.attacker.move_ids.forEach((moveId, index) => {
    names[moveId] = current.attacker.move_names[index] ?? `招式 #${moveId}`;
  });
  current.defender.move_ids.forEach((moveId, index) => {
    names[moveId] = current.defender.move_names[index] ?? `招式 #${moveId}`;
  });
  return names;
});

const scenarioSummary = computed(() => {
  const ability = dragoniteAbility.value === 'multiscale' ? '多重鳞片' : '精神力';
  const plan =
    weavilePlan.value === 'ice-punch'
      ? '玛纽拉固定使用冰冻拳'
      : '玛纽拉在击掌奇袭与冰冻拳间等概率选择';
  return `快龙采用${ability}，${plan}`;
});

/**
 * 提交当前受控场景，并用新的结果替换上一次推演。
 *
 * 请求开始前同时清空旧 graph、胜利路径选择和父页面保存的战报 DTO，避免不同推演生命周期串线。
 */
async function runInference(): Promise<void> {
  loading.value = true;
  errorMessage.value = '';
  result.value = null;
  activeExploration.value = null;
  showGraphExplorer.value = true;
  selectedWinningPathSide.value = null;
  try {
    result.value = await inferDragoniteVsWeavile({
      dragonite_ability: dragoniteAbility.value,
      weavile_plan: weavilePlan.value,
      dragonite_stat_preset: 'max_atk_plus',
      weavile_stat_preset: 'max_atk_plus',
    });
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '推演请求失败';
  } finally {
    loading.value = false;
  }
}

/**
 * 保存 GraphExplorer 上报的服务端 exploration DTO。
 *
 * @param exploration 当前 cursor 对应的完整探索响应；根节点尚未加载时为 null。
 */
function updateActiveExploration(
  exploration: BattleGraphExplorationResult | null,
): void {
  activeExploration.value = exploration;
}

/**
 * 打开或切换指定胜者的 Top-K 行动路径查询面板。
 *
 * @param winner 用户点击胜率卡片对应的绝对获胜侧。
 */
function selectWinningPathSide(winner: WinningPathWinner): void {
  selectedWinningPathSide.value =
    selectedWinningPathSide.value === winner ? null : winner;
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
  const labels: Record<string, string> = {
    multiscale: '多重鳞片',
    inner_focus: '精神力',
    pressure: '压迫感（中性假设）',
    none: '无道具',
    brick_break: '劈瓦',
    ice_punch: '冰冻拳',
    fake_out: '击掌奇袭',
  };
  return labels[identifier] ?? identifier.replaceAll('_', ' ');
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
        <button
          type="button"
          class="probability-card probability-card--win winning-path-trigger"
          :class="{ 'winning-path-trigger--active': selectedWinningPathSide === 'attacker' }"
          @click="selectWinningPathSide('attacker')"
        >
          <span>快龙胜率</span>
          <strong>{{ formatPercent(summary.win_probability.percent) }}</strong>
          <small>{{ summary.win_probability.numerator }} / {{ summary.win_probability.denominator }}</small>
          <div class="probability-track">
            <i :style="{ width: `${summary.win_probability.percent}%` }" />
          </div>
          <em>查看胜利路径 Top-K</em>
        </button>
        <button
          type="button"
          class="probability-card probability-card--loss winning-path-trigger"
          :class="{ 'winning-path-trigger--active': selectedWinningPathSide === 'defender' }"
          @click="selectWinningPathSide('defender')"
        >
          <span>玛纽拉胜率</span>
          <strong>{{ formatPercent(summary.loss_probability.percent) }}</strong>
          <small>{{ summary.loss_probability.numerator }} / {{ summary.loss_probability.denominator }}</small>
          <div class="probability-track">
            <i :style="{ width: `${summary.loss_probability.percent}%` }" />
          </div>
          <em>查看胜利路径 Top-K</em>
        </button>
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

      <WinningPathGroupsPanel
        v-if="selectedWinningPathSide && result?.exploration"
        :key="`${result.exploration.graph_id}:${selectedWinningPathSide}`"
        :handle="result.exploration"
        :winner="selectedWinningPathSide"
        :move-names="moveNames"
      />

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

      <section
        v-if="result?.exploration.expandable && presenterContext"
        class="battle-exploration-layout"
      >
        <div class="battle-exploration-layout__toolbar">
          <div>
            <p class="eyebrow">LIVE EXPLORATION</p>
            <h2>状态图与当前路径战报</h2>
          </div>
          <button
            type="button"
            class="battle-exploration-layout__toggle"
            data-toggle-graph-explorer
            @click="showGraphExplorer = !showGraphExplorer"
          >
            {{ showGraphExplorer ? '隐藏状态图' : '显示状态图' }}
          </button>
        </div>
        <div
          class="battle-exploration-layout__grid"
          :class="{ 'battle-exploration-layout__grid--report-only': !showGraphExplorer }"
        >
          <BattleGraphExplorer
            v-if="showGraphExplorer"
            :key="result.exploration.graph_id"
            :handle="result.exploration"
            @exploration-change="updateActiveExploration"
            @rerun="runInference"
          />
          <BattleReportPanel
            :report="activeExploration?.battle_report ?? null"
            :context="presenterContext"
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

<style scoped>
.winning-path-trigger {
  width: 100%;
  border: 0;
  text-align: left;
  font: inherit;
  cursor: pointer;
}

.winning-path-trigger em {
  color: #748078;
  font-size: 10px;
  font-style: normal;
  font-weight: 800;
}

.winning-path-trigger--active {
  outline: 3px solid rgba(157, 48, 57, 0.16);
}

.battle-exploration-layout {
  margin-top: 42px;
}

.battle-exploration-layout__toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.battle-exploration-layout__toolbar h2 {
  margin: 6px 0 0;
  color: #173d31;
  font-size: 27px;
}

.battle-exploration-layout__toggle {
  min-height: 38px;
  border: 1px solid #9bb8a9;
  border-radius: 10px;
  padding: 0 13px;
  background: #fff;
  color: #286b52;
  font-weight: 800;
}

.battle-exploration-layout__grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 0.85fr);
  align-items: start;
  gap: 14px;
}

.battle-exploration-layout__grid--report-only {
  grid-template-columns: minmax(0, 1fr);
}

.battle-exploration-layout :deep(.battle-graph-explorer) {
  margin-top: 0;
}

@media (max-width: 1080px) {
  .battle-exploration-layout__grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px) {
  .battle-exploration-layout__toolbar {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
