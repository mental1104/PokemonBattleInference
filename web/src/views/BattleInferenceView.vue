<script setup lang="ts">
import { computed, ref } from 'vue';
import {
  inferDragoniteVsWeavile,
  type BattleJourneyResult,
  type DragoniteAbility,
  type RepresentativePathResult,
  type WeavilePlan,
} from '../api/inference';

const dragoniteAbility = ref<DragoniteAbility>('multiscale');
const weavilePlan = ref<WeavilePlan>('ice-punch');
const loading = ref(false);
const errorMessage = ref('');
const result = ref<BattleJourneyResult | null>(null);

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
 */
async function runInference(): Promise<void> {
  loading.value = true;
  errorMessage.value = '';
  try {
    result.value = await inferDragoniteVsWeavile({
      dragonite_ability: dragoniteAbility.value,
      weavile_plan: weavilePlan.value,
      dragonite_stat_preset: 'max_atk_plus',
      weavile_stat_preset: 'max_atk_plus',
    });
  } catch (error) {
    result.value = null;
    errorMessage.value = error instanceof Error ? error.message : '推演请求失败';
  } finally {
    loading.value = false;
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

    <template v-if="result">
      <section class="result-heading">
        <div>
          <p class="eyebrow">SOLVED RESULT</p>
          <h2>固定配置概率结果</h2>
        </div>
        <span class="solver-chip" :class="{ 'solver-chip--complete': result.graph.is_complete }">
          {{ result.solver_status }} · 覆盖 {{ formatPercent(result.configuration_coverage_percent) }}
        </span>
      </section>

      <section class="probability-grid">
        <article class="probability-card probability-card--win">
          <span>快龙胜率</span>
          <strong>{{ formatPercent(result.win_probability.percent) }}</strong>
          <small>{{ result.win_probability.numerator }} / {{ result.win_probability.denominator }}</small>
          <div class="probability-track">
            <i :style="{ width: `${result.win_probability.percent}%` }" />
          </div>
        </article>
        <article class="probability-card probability-card--loss">
          <span>玛纽拉胜率</span>
          <strong>{{ formatPercent(result.loss_probability.percent) }}</strong>
          <small>{{ result.loss_probability.numerator }} / {{ result.loss_probability.denominator }}</small>
          <div class="probability-track">
            <i :style="{ width: `${result.loss_probability.percent}%` }" />
          </div>
        </article>
        <article class="probability-card">
          <span>平局概率</span>
          <strong>{{ formatPercent(result.draw_probability.percent) }}</strong>
          <small>{{ result.draw_probability.numerator }} / {{ result.draw_probability.denominator }}</small>
          <div class="probability-track">
            <i :style="{ width: `${result.draw_probability.percent}%` }" />
          </div>
        </article>
        <article class="probability-card">
          <span>期望回合</span>
          <strong>{{ result.expected_turns.decimal?.toFixed(2) ?? '∞ / 不可用' }}</strong>
          <small>策略与战斗随机共同决定</small>
        </article>
      </section>

      <section class="inference-detail-grid">
        <article class="configuration-panel">
          <div class="panel-title">
            <span>快龙</span>
            <small>观察方 · {{ result.attacker_policy }}</small>
          </div>
          <dl>
            <div><dt>特性</dt><dd>{{ displayIdentifier(result.attacker.ability_identifier) }}</dd></div>
            <div><dt>道具</dt><dd>{{ displayIdentifier(result.attacker.item_identifier) }}</dd></div>
            <div><dt>招式</dt><dd>{{ result.attacker.move_names.join(' / ') }}</dd></div>
            <div><dt>HP / 攻击 / 速度</dt><dd>{{ result.attacker.stats.hp }} / {{ result.attacker.stats.attack }} / {{ result.attacker.stats.speed }}</dd></div>
          </dl>
        </article>
        <article class="configuration-panel">
          <div class="panel-title">
            <span>玛纽拉</span>
            <small>{{ result.defender_policy }}</small>
          </div>
          <dl>
            <div><dt>特性</dt><dd>{{ displayIdentifier(result.defender.ability_identifier) }}</dd></div>
            <div><dt>道具</dt><dd>{{ displayIdentifier(result.defender.item_identifier) }}</dd></div>
            <div><dt>招式</dt><dd>{{ result.defender.move_names.join(' / ') }}</dd></div>
            <div><dt>HP / 攻击 / 速度</dt><dd>{{ result.defender.stats.hp }} / {{ result.defender.stats.attack }} / {{ result.defender.stats.speed }}</dd></div>
          </dl>
        </article>
        <article class="graph-panel">
          <div class="panel-title">
            <span>状态图</span>
            <small>{{ result.graph.is_complete ? '完整' : '已截断' }}</small>
          </div>
          <div class="graph-metrics">
            <div><strong>{{ result.graph.unique_state_count }}</strong><span>唯一状态</span></div>
            <div><strong>{{ result.graph.edge_count }}</strong><span>概率边</span></div>
            <div><strong>{{ result.graph.max_turn_number }}</strong><span>最大回合</span></div>
            <div><strong>{{ result.graph.terminal_reachable_cycle_count }}</strong><span>可出循环</span></div>
          </div>
        </article>
      </section>

      <section class="path-section">
        <div class="result-heading result-heading--compact">
          <div>
            <p class="eyebrow">REPRESENTATIVE PATHS</p>
            <h2>代表性终局路径</h2>
          </div>
        </div>
        <div class="path-grid">
          <article v-for="path in result.representative_paths" :key="path.reference" class="path-card">
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
            <span v-for="item in result.included_mechanisms" :key="item">{{ item }}</span>
          </div>
          <div>
            <strong>未纳入</strong>
            <span v-for="item in result.excluded_mechanisms" :key="item">{{ item }}</span>
            <span v-if="result.excluded_mechanisms.length === 0">无</span>
          </div>
        </div>
        <ul v-if="result.warnings.length" class="warning-list">
          <li v-for="warning in result.warnings" :key="warning">{{ warning }}</li>
        </ul>
      </section>
    </template>
  </main>
</template>
