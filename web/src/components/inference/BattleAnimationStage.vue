<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue';
import type {
  BattleEventDetailResult,
  BattleReportResult,
  BattleReportStepResult,
} from '../../api/inference';
import {
  presentBattleEvent,
  type BattleReportPresenterContext,
  type BattleSide,
} from '../../presenters/battleEventPresenter';

/** BattleAnimationStage 的只读输入。 */
interface Props {
  /** 当前 exploration cursor 对应的完整结构化战报；为空时显示待选择状态。 */
  report: BattleReportResult | null;
  /** Pokémon、最大 HP、规则集和招式名称的展示上下文。 */
  context: BattleReportPresenterContext;
}

const props = defineProps<Props>();

/** 一侧动画状态，直接由结构化事件驱动。 */
interface AnimatedSideState {
  /** 当前展示 HP。 */
  hp: number;
  /** 该侧是否正在执行招式前探。 */
  acting: boolean;
  /** 该侧是否正在受击闪烁。 */
  hit: boolean;
  /** 该侧是否正在播放特性触发光效。 */
  ability: boolean;
  /** HP 归零后是否进入倒下视觉状态。 */
  fainted: boolean;
  /** 当前图片槽位；背面图失败时会回退为 front_default。 */
  spriteSlot: 'front_default' | 'back_default';
}

const playbackVersion = ref(0);
const currentEventText = ref('选择一条路径后，动画会沿战报播放到当前节点。');
const appliedStepKeys = ref<string[]>([]);
const sides = reactive<Record<BattleSide, AnimatedSideState>>({
  attacker: {
    hp: props.context.sides.attacker.maxHp,
    acting: false,
    hit: false,
    ability: false,
    fainted: false,
    spriteSlot: 'back_default',
  },
  defender: {
    hp: props.context.sides.defender.maxHp,
    acting: false,
    hit: false,
    ability: false,
    fainted: false,
    spriteSlot: 'front_default',
  },
});

/**
 * 暂停指定毫秒数，并在播放版本变化后让调用方自然退出。
 *
 * @param milliseconds 等待时长，单位毫秒。
 * @returns timeout 完成后的 Promise。
 */
function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

/**
 * 把后端字符串侧别收窄为动画组件可处理的双方。
 *
 * @param value 结构化事件中的 actor 或 target。
 * @returns attacker/defender 原值；其他值返回 null。
 */
function asBattleSide(value: string | null): BattleSide | null {
  return value === 'attacker' || value === 'defender' ? value : null;
}

/**
 * 为 report step 生成可比较的路径前缀 key。
 *
 * @param step 当前 cursor 中的一条真实 edge。
 * @returns 同时包含 source、edge 和 target 的稳定路径片段。
 */
function reportStepKey(step: BattleReportStepResult): string {
  return `${step.source_node_id}:${step.edge_id}:${step.target_node_id}`;
}

/**
 * 从 report 中提取 cursor 路径前缀。
 *
 * @param report 当前路径战报；为空表示尚未选择精确 edge。
 * @returns 可与上一轮播放状态比较的 step key 列表。
 */
function reportStepKeys(report: BattleReportResult | null): string[] {
  if (report === null) {
    return [];
  }
  return report.steps.map(reportStepKey);
}

/**
 * 判断一个路径 key 列表是否是另一个路径的前缀。
 *
 * @param prefix 期望已播放到的旧路径。
 * @param next 最新 report 对应的新路径。
 * @returns 旧路径完整匹配新路径开头时返回 true。
 */
function isPathPrefix(prefix: string[], next: string[]): boolean {
  return prefix.every((key, index) => next[index] === key);
}

/**
 * 从 report 中选择指定 step 范围的首条事件解释，并保持 cursor 顺序。
 *
 * @param report 当前路径战报。
 * @param startIndex 起始 step 下标，包含。
 * @param endIndex 结束 step 下标，不包含。
 * @returns 可顺序播放或瞬时应用的结构化事件列表。
 */
function eventsForStepRange(
  report: BattleReportResult,
  startIndex: number,
  endIndex: number,
): BattleEventDetailResult[] {
  return report.steps
    .slice(startIndex, endIndex)
    .flatMap((step) => step.event_paths[0]?.battle_events ?? []);
}

/**
 * 计算一侧图片 URL，slot 由当前动画状态决定。
 *
 * @param side 需要渲染的战斗侧。
 * @returns 可直接用于 img src 的项目内 sprite URL。
 */
function spriteUrl(side: BattleSide): string {
  const sideContext = props.context.sides[side];
  const slot = side === 'attacker' ? sides.attacker.spriteSlot : 'front_default';
  const query = new URLSearchParams({
    ruleset_id: props.context.rulesetId,
    slot,
  });
  return `/api/v1/assets/pokemon/${sideContext.pokemonId}/sprite?${query.toString()}`;
}

/**
 * 图片槽位加载失败时回退到 front_default，避免背面图视图未刷新时战场空白。
 *
 * @param side 加载失败的战斗侧。
 */
function fallbackSprite(side: BattleSide): void {
  if (side === 'attacker') {
    sides.attacker.spriteSlot = 'front_default';
  }
}

/**
 * 返回 HP 百分比，最大 HP 缺失时保持 0，避免样式宽度 NaN。
 *
 * @param side 需要展示 HP 条的一侧。
 * @returns 0 到 100 之间的百分数。
 */
function hpPercent(side: BattleSide): number {
  const maximum = props.context.sides[side].maxHp;
  if (maximum <= 0) {
    return 0;
  }
  return Math.max(0, Math.min(100, (sides[side].hp / maximum) * 100));
}

/**
 * 重置战场到当前配置的起点状态。
 *
 * @param message 重置后显示的当前事件文本。
 */
function resetBattlefield(message: string): void {
  sides.attacker.hp = props.context.sides.attacker.maxHp;
  sides.defender.hp = props.context.sides.defender.maxHp;
  sides.attacker.acting = false;
  sides.defender.acting = false;
  sides.attacker.hit = false;
  sides.defender.hit = false;
  sides.attacker.ability = false;
  sides.defender.ability = false;
  sides.attacker.fainted = false;
  sides.defender.fainted = false;
  sides.attacker.spriteSlot = 'back_default';
  sides.defender.spriteSlot = 'front_default';
  currentEventText.value = message;
}

/**
 * 不播放视觉动作，直接把一条事件折叠进当前战场状态。
 *
 * @param event 服务端按真实顺序返回的战斗事件。
 */
function applyInstantEvent(event: BattleEventDetailResult): void {
  if (event.kind === 'hp-changed') {
    const target = asBattleSide(event.target);
    if (target !== null && typeof event.after_value === 'number') {
      sides[target].hp = Math.max(0, event.after_value);
      sides[target].fainted = sides[target].hp === 0;
    }
  }
  if (event.kind === 'fainted') {
    const target = asBattleSide(event.target) ?? asBattleSide(event.actor);
    if (target !== null) {
      sides[target].hp = 0;
      sides[target].fainted = true;
    }
  }
}

/**
 * 瞬时同步到 report 中指定 step 下标之前的最终状态。
 *
 * @param report 当前路径战报。
 * @param endIndex 需要应用到的 step 结束下标，不包含。
 */
function syncInstantlyToStep(report: BattleReportResult, endIndex: number): void {
  resetBattlefield('已同步到当前节点。');
  for (const event of eventsForStepRange(report, 0, endIndex)) {
    applyInstantEvent(event);
  }
}

/**
 * 应用一条结构化事件到动画状态。
 *
 * @param event 服务端按真实顺序返回的战斗事件。
 * @param version 当前播放版本；版本变化说明用户已经切换路径。
 */
async function applyAnimatedEvent(event: BattleEventDetailResult, version: number): Promise<void> {
  const presented = presentBattleEvent(event, props.context, `${version}:${event.kind}`);
  currentEventText.value = presented?.text ?? event.kind;

  if (event.kind === 'move-used') {
    const actor = asBattleSide(event.actor);
    if (actor !== null) {
      sides[actor].acting = true;
      await sleep(260);
      if (playbackVersion.value !== version) return;
      sides[actor].acting = false;
    }
  }

  if (event.kind === 'ability-triggered') {
    const actor = asBattleSide(event.actor);
    if (actor !== null) {
      sides[actor].ability = true;
      await sleep(320);
      if (playbackVersion.value !== version) return;
      sides[actor].ability = false;
    }
  }

  if (event.kind === 'damage' || event.kind === 'hp-changed') {
    const target = asBattleSide(event.target);
    if (target !== null) {
      sides[target].hit = true;
      if (event.kind === 'hp-changed' && typeof event.after_value === 'number') {
        sides[target].hp = Math.max(0, event.after_value);
        sides[target].fainted = sides[target].hp === 0;
      }
      await sleep(300);
      if (playbackVersion.value !== version) return;
      sides[target].hit = false;
    }
  }

  if (event.kind === 'fainted') {
    const target = asBattleSide(event.target) ?? asBattleSide(event.actor);
    if (target !== null) {
      sides[target].hp = 0;
      sides[target].fainted = true;
    }
  }
}

/**
 * 从当前已同步节点开始播放新增事件。
 *
 * @param report 当前路径战报。
 * @param startIndex 新增 step 的起始下标。
 * @param nextKeys 当前 report 的完整路径 key。
 */
async function playIncrementalReport(
  report: BattleReportResult,
  startIndex: number,
  nextKeys: string[],
): Promise<void> {
  playbackVersion.value += 1;
  const version = playbackVersion.value;
  syncInstantlyToStep(report, startIndex);
  const events = eventsForStepRange(report, startIndex, report.steps.length);
  currentEventText.value = events.length === 0 ? '已同步到当前节点。' : '正在播放新增节点事件…';

  for (const event of events) {
    if (playbackVersion.value !== version) return;
    await applyAnimatedEvent(event, version);
    await sleep(120);
  }

  if (playbackVersion.value === version) {
    currentEventText.value = events.length > 0 ? '已播放到当前节点。' : '已同步到当前节点。';
    appliedStepKeys.value = nextKeys;
  }
}

watch(
  () =>
    [
      props.report,
      props.context.sides.attacker.maxHp,
      props.context.sides.defender.maxHp,
    ] as const,
  ([report, attackerMaxHp, defenderMaxHp], previous) => {
    // snapshot mode 可能先渲染临时 maxHp=0，再由当前节点补齐真实最大 HP；此时必须重算整条已选路径。
    const hpBaselineChanged =
      previous !== undefined
      && (previous[1] !== attackerMaxHp || previous[2] !== defenderMaxHp);
    playbackVersion.value += 1;
    if (report === null || report.steps.length === 0) {
      appliedStepKeys.value = [];
      resetBattlefield('尚未选择任何精确路径。');
      return;
    }

    const nextKeys = reportStepKeys(report);
    if (!hpBaselineChanged && isPathPrefix(appliedStepKeys.value, nextKeys)) {
      void playIncrementalReport(report, appliedStepKeys.value.length, nextKeys);
      return;
    }

    syncInstantlyToStep(report, report.steps.length);
    appliedStepKeys.value = nextKeys;
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  playbackVersion.value += 1;
});
</script>

<template>
  <section class="battle-animation-stage" aria-label="当前路径动画战场">
    <div class="battle-animation-stage__field">
      <div
        class="battle-animation-side battle-animation-side--defender"
        :class="{
          'battle-animation-side--acting': sides.defender.acting,
          'battle-animation-side--hit': sides.defender.hit,
          'battle-animation-side--ability': sides.defender.ability,
          'battle-animation-side--fainted': sides.defender.fainted,
        }"
      >
        <div class="battle-animation-side__hp">
          <span>{{ context.sides.defender.name }}</span>
          <strong>{{ sides.defender.hp }} / {{ context.sides.defender.maxHp }}</strong>
          <i :style="{ width: `${hpPercent('defender')}%` }" />
        </div>
        <img
          :src="spriteUrl('defender')"
          :alt="context.sides.defender.name"
          @error="fallbackSprite('defender')"
        >
      </div>

      <div
        class="battle-animation-side battle-animation-side--attacker"
        :class="{
          'battle-animation-side--acting': sides.attacker.acting,
          'battle-animation-side--hit': sides.attacker.hit,
          'battle-animation-side--ability': sides.attacker.ability,
          'battle-animation-side--fainted': sides.attacker.fainted,
        }"
      >
        <div class="battle-animation-side__hp">
          <span>{{ context.sides.attacker.name }}</span>
          <strong>{{ sides.attacker.hp }} / {{ context.sides.attacker.maxHp }}</strong>
          <i :style="{ width: `${hpPercent('attacker')}%` }" />
        </div>
        <img
          :src="spriteUrl('attacker')"
          :alt="context.sides.attacker.name"
          @error="fallbackSprite('attacker')"
        >
      </div>
    </div>

    <p class="battle-animation-stage__caption">{{ currentEventText }}</p>
  </section>
</template>

<style scoped>
.battle-animation-stage {
  border-bottom: 1px solid #e0e7e2;
  background:
    linear-gradient(180deg, rgba(237, 246, 242, 0.96), rgba(252, 253, 252, 0.98));
}

.battle-animation-stage__field {
  position: relative;
  min-height: 360px;
  overflow: hidden;
  background:
    radial-gradient(ellipse at 72% 28%, rgba(246, 255, 238, 0.9), transparent 22%),
    radial-gradient(ellipse at 28% 76%, rgba(232, 241, 220, 0.95), transparent 28%),
    linear-gradient(180deg, #dceee8 0%, #f4faf7 52%, #e2eadf 53%, #cbdccf 100%);
}

.battle-animation-side {
  position: absolute;
  display: grid;
  gap: 8px;
  width: min(38%, 210px);
  transition:
    opacity 240ms ease,
    transform 240ms ease,
    filter 160ms ease;
}

.battle-animation-side--defender {
  top: 22px;
  right: 28px;
}

.battle-animation-side--attacker {
  left: 22px;
  bottom: 8px;
  width: min(46%, 250px);
}

.battle-animation-side--acting.battle-animation-side--attacker {
  transform: translate(24px, -14px);
}

.battle-animation-side--acting.battle-animation-side--defender {
  transform: translate(-20px, 12px);
}

.battle-animation-side--hit {
  filter: brightness(1.9) contrast(0.7);
  animation: battle-hit-shake 160ms linear 2;
}

.battle-animation-side--ability::after {
  position: absolute;
  inset: 48px 24px 0;
  border: 2px solid rgba(100, 120, 190, 0.8);
  border-radius: 50%;
  content: '';
  animation: battle-ability-ring 320ms ease-out;
}

.battle-animation-side--fainted {
  opacity: 0.42;
  transform: translateY(18px);
}

.battle-animation-side img {
  justify-self: center;
  width: 128px;
  height: 128px;
  object-fit: contain;
  image-rendering: pixelated;
}

.battle-animation-side--attacker img {
  width: 184px;
  height: 184px;
}

.battle-animation-side__hp {
  display: grid;
  gap: 3px;
  overflow: hidden;
  border: 1px solid #b8c8be;
  border-radius: 8px;
  background: #ffffff;
  padding: 7px 9px;
  box-shadow: 0 8px 18px rgba(38, 75, 57, 0.08);
}

.battle-animation-side__hp span,
.battle-animation-side__hp strong {
  display: flex;
  justify-content: space-between;
  color: #25483a;
  font-size: 11px;
  line-height: 1.2;
}

.battle-animation-side__hp strong {
  font-size: 10px;
}

.battle-animation-side__hp i {
  display: block;
  height: 7px;
  border-radius: 999px;
  background: linear-gradient(90deg, #5daf7e, #b2cf69);
  transition: width 260ms ease;
}

.battle-animation-stage__caption {
  min-height: 34px;
  margin: 0;
  padding: 9px 14px 11px;
  color: #41564c;
  font-size: 12px;
  line-height: 1.35;
}

@keyframes battle-hit-shake {
  0% {
    transform: translateX(0);
  }
  50% {
    transform: translateX(5px);
  }
  100% {
    transform: translateX(-5px);
  }
}

@keyframes battle-ability-ring {
  from {
    opacity: 0.9;
    transform: scale(0.7);
  }
  to {
    opacity: 0;
    transform: scale(1.35);
  }
}
</style>
