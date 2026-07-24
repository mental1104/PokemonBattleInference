<script setup lang="ts">
import type {
  PokemonDetail,
  PokemonSearchItem,
  StatPreset,
} from '../../api/calculator';
import PokemonSelector from '../PokemonSelector.vue';
import PokemonSummaryCard from '../PokemonSummaryCard.vue';
import StatPresetSelector from '../StatPresetSelector.vue';
import CandidateMovePoolSelector from './CandidateMovePoolSelector.vue';
import type { CandidateMoveOption } from '../../types/battleConfigurationSpace';
import './BattleSideConfigurationPanel.css';

const props = defineProps<{
  side: 'attacker' | 'defender';
  title: string;
  rulesetId: string;
  pokemon: PokemonDetail | null;
  recentPokemon: readonly PokemonSearchItem[];
  presets: StatPreset[];
  statPreset: string;
  formId: number | null;
  level: number;
  abilityIdentifier: string;
  itemIdentifier: string;
  candidateMoves: readonly CandidateMoveOption[];
  selectedMoveIds: readonly number[];
  movesLoading: boolean;
  remainingGlobalSlots: number;
}>();

const emit = defineEmits<{
  'select-pokemon': [pokemon: PokemonSearchItem];
  'update-stat-preset': [value: string];
  'update-form-id': [value: number | null];
  'update-level': [value: number];
  'update-ability-identifier': [value: string];
  'update-item-identifier': [value: string];
  'update-selected-move-ids': [moveIds: number[]];
}>();

/**
 * 将 level 输入收敛到 Pokémon 合法区间后发送给页面状态。
 *
 * @param event 原生 number input 的 change 事件。
 */
function updateLevel(event: Event): void {
  const target = event.target as HTMLInputElement;
  const parsed = Number(target.value);
  const normalized = Number.isFinite(parsed)
    ? Math.min(100, Math.max(1, Math.trunc(parsed)))
    : props.level;
  target.value = String(normalized);
  emit('update-level', normalized);
}

/**
 * 将可选 form ID 规范化为正整数或 null。
 *
 * @param event 原生 number input 的 change 事件。
 */
function updateFormId(event: Event): void {
  const target = event.target as HTMLInputElement;
  if (target.value.trim() === '') {
    emit('update-form-id', null);
    return;
  }
  const parsed = Number(target.value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    target.value = props.formId === null ? '' : String(props.formId);
    return;
  }
  emit('update-form-id', parsed);
}

/**
 * 读取文本输入并转发稳定 identifier。
 *
 * @param event 原生文本输入事件。
 * @returns 去除首尾空白后的 identifier。
 */
function inputValue(event: Event): string {
  return (event.target as HTMLInputElement).value.trim();
}
</script>

<template>
  <article class="battle-side-panel" :data-side="side">
    <header class="battle-side-panel__header">
      <span>{{ side === 'attacker' ? 'A' : 'B' }}</span>
      <div>
        <p>{{ side === 'attacker' ? 'ATTACKER' : 'DEFENDER' }}</p>
        <h2>{{ title }}</h2>
      </div>
    </header>

    <PokemonSelector
      :title="`${title} Pokémon`"
      :ruleset-id="rulesetId"
      :selected="pokemon"
      :recent-pokemon="recentPokemon"
      @select="emit('select-pokemon', $event)"
    />
    <PokemonSummaryCard :pokemon="pokemon" />

    <section class="panel-block battle-fixed-fields" :aria-label="`${title}固定配置`">
      <div class="field-title">固定战斗参数</div>
      <p class="battle-fixed-fields__hint">首版这些字段只取一个固定值，不参与配置枚举。</p>
      <div class="battle-fixed-fields__grid">
        <label>
          <span>form_id</span>
          <input
            :value="formId ?? ''"
            :data-testid="`${side}-form-id`"
            type="number"
            min="1"
            placeholder="null（默认形态）"
            @change="updateFormId"
          />
        </label>
        <label>
          <span>level</span>
          <input
            :value="level"
            :data-testid="`${side}-level`"
            type="number"
            min="1"
            max="100"
            @change="updateLevel"
          />
        </label>
        <label>
          <span>ability_identifier</span>
          <input
            :value="abilityIdentifier"
            :data-testid="`${side}-ability-identifier`"
            type="text"
            placeholder="none"
            @change="emit('update-ability-identifier', inputValue($event))"
          />
        </label>
        <label>
          <span>item_identifier</span>
          <input
            :value="itemIdentifier"
            :data-testid="`${side}-item-identifier`"
            type="text"
            placeholder="空白表示 null"
            @change="emit('update-item-identifier', inputValue($event))"
          />
        </label>
      </div>
    </section>

    <StatPresetSelector
      :model-value="statPreset"
      :data-testid="`${side}-stat-preset`"
      :title="`${title}能力值预设`"
      :presets="presets"
      @update:model-value="emit('update-stat-preset', $event)"
    />

    <CandidateMovePoolSelector
      :side="side"
      :title="`${title}候选技能池`"
      :moves="candidateMoves"
      :model-value="selectedMoveIds"
      :loading="movesLoading"
      :disabled="pokemon === null"
      :remaining-global-slots="remainingGlobalSlots"
      @update:model-value="emit('update-selected-move-ids', $event)"
    />
  </article>
</template>
