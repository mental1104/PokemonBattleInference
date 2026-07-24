<script setup lang="ts">
import { onMounted } from 'vue';
import type { PokemonSearchItem } from '../api/calculator';
import { SUPPORTED_VERSION_GROUPS } from '../api/configurationSpace';
import BattleSideConfigurationPanel from '../components/inference/BattleSideConfigurationPanel.vue';
import { useBattleInferenceConfiguration } from '../composables/useBattleInferenceConfiguration';
import { useRecentPokemon } from '../composables/useRecentPokemon';
import './BattleInferenceView.css';

const configuration = useBattleInferenceConfiguration();
const {
  rulesetId,
  versionGroupId,
  calculationRevision,
  dimensions,
  weightAssumption,
  attackerPolicy,
  defenderPolicy,
  mechanismAdmission,
  attacker,
  defender,
  attackerPresets,
  defenderPresets,
  selectionNotice,
  error,
  submitting,
  frozenSubmission,
  createdJob,
  budget,
  remainingGlobalSlots,
  validationMessages,
  canSubmit,
  loadPresets,
  selectPokemon: selectConfigurationPokemon,
  updateSelectedMoveIds,
  applyDragoniteVsWeavilePreset,
  submit,
} = configuration;
const { items: recentPokemon, remember: rememberPokemon } = useRecentPokemon();
const countFormatter = new Intl.NumberFormat('zh-CN');

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
 * 格式化候选数、组合数和配置对数量。
 *
 * @param value 非负整数计数。
 * @returns 使用中文千分位分隔的展示文本。
 */
function formatCount(value: number): string {
  return countFormatter.format(value);
}
</script>

<template>
  <main class="app-shell battle-configuration-view">
    <header class="battle-configuration-hero">
      <div>
        <p class="battle-configuration-eyebrow">GENERAL 1V1 CONFIGURATION SPACE</p>
        <h1>战斗推演配置实验室</h1>
        <p>
          固定双方形态、等级、能力值、特性与道具，只枚举规范化后的候选技能组；提交后由后台任务逐个求解配置对。
        </p>
      </div>
      <div class="battle-configuration-hero__badge">
        <span>首版硬预算</span>
        <strong>20 招式 · 44,100 配置对</strong>
        <small>客户端即时反馈，服务端准入仍为最终权威</small>
      </div>
    </header>

    <section class="battle-context-panel" aria-label="推演规则上下文">
      <div class="battle-context-field">
        <span>ruleset_id</span>
        <strong data-testid="ruleset-id">{{ rulesetId }}</strong>
      </div>
      <label class="battle-context-field">
        <span>version_group_id</span>
        <select
          v-model.number="versionGroupId"
          data-testid="version-group-id"
        >
          <option
            v-for="versionGroupId in SUPPORTED_VERSION_GROUPS"
            :key="versionGroupId"
            :value="versionGroupId"
          >
            {{ versionGroupId }}
          </option>
        </select>
      </label>
      <div class="battle-context-field battle-context-field--revision">
        <span>calculation_revision</span>
        <strong>{{ calculationRevision }}</strong>
      </div>
      <button
        class="battle-example-button"
        data-testid="dragonite-weavile-preset"
        type="button"
        @click="applyDragoniteVsWeavilePreset"
      >
        载入快龙 vs 玛纽拉示例
      </button>
    </section>

    <p
      v-if="selectionNotice"
      class="battle-configuration-notice"
      role="status"
    >
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

    <p v-if="attacker.error" class="error battle-side-error">
      攻击方：{{ attacker.error }}
    </p>
    <p v-if="defender.error" class="error battle-side-error">
      防守方：{{ defender.error }}
    </p>

    <section class="battle-budget-panel" aria-label="配置空间预算">
      <div class="battle-budget-panel__heading">
        <div>
          <p class="battle-configuration-eyebrow">CONFIGURATION BUDGET</p>
          <h2>候选池与配置对预算</h2>
        </div>
        <span
          class="battle-budget-status"
          :class="{
            'battle-budget-status--blocked':
              budget.exceeds_candidate_limit ||
              budget.exceeds_configuration_pair_limit,
          }"
          data-testid="budget-status"
        >
          {{
            budget.exceeds_candidate_limit ||
            budget.exceeds_configuration_pair_limit
              ? '超过硬上限'
              : '预算内'
          }}
        </span>
      </div>

      <div class="battle-budget-grid">
        <article>
          <span>攻击方候选</span>
          <strong data-testid="attacker-candidate-count">
            {{ formatCount(budget.attacker_candidate_count) }}
          </strong>
          <small>
            {{ formatCount(budget.attacker_move_set_count) }} 个实际技能组
          </small>
        </article>
        <article>
          <span>防守方候选</span>
          <strong data-testid="defender-candidate-count">
            {{ formatCount(budget.defender_candidate_count) }}
          </strong>
          <small>
            {{ formatCount(budget.defender_move_set_count) }} 个实际技能组
          </small>
        </article>
        <article>
          <span>双方候选总数</span>
          <strong data-testid="total-candidate-count">
            {{ formatCount(budget.total_candidate_count) }} / 20
          </strong>
          <small>每侧至少 1 个，仅可执行候选计入</small>
        </article>
        <article class="battle-budget-grid__primary">
          <span>配置对数量</span>
          <strong data-testid="configuration-pair-count">
            {{ formatCount(budget.configuration_pair_count) }}
          </strong>
          <small>
            攻击方技能组 × 防守方技能组，硬上限 {{ formatCount(44_100) }}
          </small>
        </article>
      </div>

      <p class="battle-budget-formula">
        组合规则：<code>n &lt; 4 → 1</code>；<code>n ≥ 4 → C(n, 4)</code>。同一组 move_id 的点击顺序不会产生新配置。
      </p>
    </section>

    <section class="battle-contract-panel" aria-label="冻结计算语义">
      <div>
        <span>配置权重</span>
        <strong>{{ weightAssumption }}</strong>
        <small>每个生成出的固定配置对等权。</small>
      </div>
      <div>
        <span>默认行动策略</span>
        <strong>{{ attackerPolicy }} / {{ defenderPolicy }}</strong>
        <small>双方在行动选择边界等概率选择当前合法行动，技能槽排列不改变策略。</small>
      </div>
      <div>
        <span>枚举维度</span>
        <strong>{{ dimensions.moves }} · {{ mechanismAdmission }}</strong>
        <small>form、level、stats、ability、item 固定；special_mechanics 禁用。</small>
      </div>
    </section>

    <section class="battle-submit-panel">
      <div>
        <h2>提交后台推演任务</h2>
        <p>提交前先冻结双方固定配置、规范化候选池、策略和预算；本页不在浏览器内执行 solver。</p>
        <ul v-if="validationMessages.length" class="battle-validation-list">
          <li v-for="message in validationMessages" :key="message">
            {{ message }}
          </li>
        </ul>
      </div>
      <button
        class="primary-button"
        data-testid="submit-configuration-job"
        type="button"
        :disabled="!canSubmit"
        @click="submit"
      >
        {{ submitting ? '正在创建任务' : '冻结输入并创建任务' }}
      </button>
      <p v-if="error" class="error" role="alert">
        {{ error }}
      </p>
    </section>

    <section
      v-if="frozenSubmission"
      class="battle-frozen-summary"
      data-testid="frozen-submission-summary"
    >
      <div class="battle-frozen-summary__heading">
        <div>
          <p class="battle-configuration-eyebrow">FROZEN INPUT</p>
          <h2>已冻结的任务输入摘要</h2>
        </div>
        <span v-if="createdJob" class="state-pill">
          {{ createdJob.status }} · {{ createdJob.job_id }}
        </span>
      </div>

      <div class="battle-frozen-summary__grid">
        <article>
          <span>攻击方</span>
          <strong>{{ frozenSubmission.attacker_name }}</strong>
          <small>{{ frozenSubmission.attacker_move_names.join(' / ') }}</small>
        </article>
        <article>
          <span>防守方</span>
          <strong>{{ frozenSubmission.defender_name }}</strong>
          <small>{{ frozenSubmission.defender_move_names.join(' / ') }}</small>
        </article>
        <article>
          <span>配置对</span>
          <strong>{{ formatCount(frozenSubmission.configuration_pair_count) }}</strong>
          <small>
            候选预算 {{ frozenSubmission.max_candidate_moves }}，
            配置对预算 {{ formatCount(frozenSubmission.max_configuration_pairs) }}
          </small>
        </article>
      </div>

      <dl class="battle-frozen-summary__metadata">
        <div>
          <dt>ruleset_id / version_group_id</dt>
          <dd>
            {{ frozenSubmission.request.ruleset_id }} /
            {{ frozenSubmission.request.version_group_id }}
          </dd>
        </div>
        <div>
          <dt>weight_assumption / mechanism_admission</dt>
          <dd>
            {{ frozenSubmission.request.weight_assumption }} /
            {{ frozenSubmission.request.mechanism_admission }}
          </dd>
        </div>
        <div>
          <dt>attacker_policy / defender_policy</dt>
          <dd>
            {{ frozenSubmission.request.attacker_policy }} /
            {{ frozenSubmission.request.defender_policy }}
          </dd>
        </div>
      </dl>
    </section>
  </main>
</template>
