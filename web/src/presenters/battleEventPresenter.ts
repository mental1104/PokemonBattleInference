import type {
  BattleEventDetailResult,
  BattleInferenceSummaryResult,
  BattleReportResult,
  BattleReportStepResult,
} from '../api/inference';

/** 表示结构化事件中的绝对战斗侧。 */
export type BattleSide = 'attacker' | 'defender';

/** 控制战报事件行的视觉语义，不参与业务判断。 */
export type BattleReportEventTone =
  | 'neutral'
  | 'move'
  | 'success'
  | 'danger'
  | 'mechanism'
  | 'status'
  | 'unknown';

/** 保存一侧 Pokémon 的展示名称和最大 HP。 */
export interface BattleReportSideContext {
  name: string;
  maxHp: number;
}

/** 保存 presenter 解析双方与招式名称所需的纯展示上下文。 */
export interface BattleReportPresenterContext {
  sides: Record<BattleSide, BattleReportSideContext>;
  moveNames: Readonly<Record<number, string>>;
}

/** 保存一条已经从结构化事件投影出的稳定展示行。 */
export interface PresentedBattleEvent {
  id: string;
  turnNumber: number;
  kind: string;
  text: string;
  tone: BattleReportEventTone;
  debug: string | null;
}

/** 保存一个按真实事件顺序排列、可独立折叠的回合。 */
export interface PresentedBattleReportTurn {
  turnNumber: number;
  events: PresentedBattleEvent[];
  stepDepths: number[];
  alternativePathCount: number;
}

const POKEMON_NAMES: Readonly<Record<string, string>> = {
  dragonite: '快龙',
  weavile: '玛纽拉',
};

const MOVE_NAMES: Readonly<Record<number, string>> = {
  8: '冰冻拳',
  252: '击掌奇袭',
  280: '劈瓦',
};

const SOURCE_NAMES: Readonly<Record<string, string>> = {
  multiscale: '多重鳞片',
  inner_focus: '精神力',
  pressure: '压迫感',
  flinch: '畏缩',
  burn: '灼伤',
  paralysis: '麻痹',
  poison: '中毒',
  bad_poison: '剧毒',
  sleep: '睡眠',
  freeze: '冰冻',
  confusion: '混乱',
  infatuation: '着迷',
};

/**
 * 把服务端 Pokémon identifier 转换为当前首版已知的中文名称。
 *
 * @param identifier 配置摘要返回的 Pokémon 名称或 identifier。
 * @returns 已知 Pokémon 返回中文名；未知值保留规范化后的原文本。
 */
function pokemonDisplayName(identifier: string): string {
  const normalized = identifier.trim().toLowerCase().replaceAll('-', '_');
  return POKEMON_NAMES[normalized] ?? normalized.replaceAll('_', ' ');
}

/**
 * 把招式 ID 与配置摘要中的名称配对成只读查找表。
 *
 * @param summary 当前固定推演的双方配置摘要。
 * @returns 以 move ID 为 key 的展示名称字典。
 */
function buildMoveNameMap(
  summary: BattleInferenceSummaryResult,
): Readonly<Record<number, string>> {
  const pairs: Array<[number, string]> = [];
  for (const pokemon of [summary.attacker, summary.defender]) {
    pokemon.move_ids.forEach((moveId, index) => {
      const configuredName = pokemon.move_names[index];
      pairs.push([moveId, configuredName ?? MOVE_NAMES[moveId] ?? `招式 #${moveId}`]);
    });
  }
  return Object.freeze(Object.fromEntries(pairs) as Record<number, string>);
}

/**
 * 从固定推演 summary 构造与组件生命周期无关的 presenter 上下文。
 *
 * @param summary 当前推演返回的双方配置。
 * @returns 只包含字符串、数值和只读字典的展示上下文。
 */
export function createBattleReportPresenterContext(
  summary: BattleInferenceSummaryResult,
): BattleReportPresenterContext {
  return {
    sides: {
      attacker: {
        name: pokemonDisplayName(summary.attacker.name),
        maxHp: summary.attacker.stats.hp ?? 0,
      },
      defender: {
        name: pokemonDisplayName(summary.defender.name),
        maxHp: summary.defender.stats.hp ?? 0,
      },
    },
    moveNames: buildMoveNameMap(summary),
  };
}

/**
 * 把后端字符串侧别收窄为前端支持的绝对战斗侧。
 *
 * @param value 结构化事件中的 actor 或 target。
 * @returns attacker/defender 原值；未知或空值返回 null。
 */
function asBattleSide(value: string | null): BattleSide | null {
  return value === 'attacker' || value === 'defender' ? value : null;
}

/**
 * 解析事件主体或目标侧的 Pokémon 名称。
 *
 * @param value 结构化事件中的绝对战斗侧字符串。
 * @param context 当前 presenter 上下文。
 * @returns 对应 Pokémon 名称；缺失或未知侧别时返回通用称呼。
 */
function sideName(
  value: string | null,
  context: BattleReportPresenterContext,
): string {
  const side = asBattleSide(value);
  return side === null ? '该 Pokémon' : context.sides[side].name;
}

/**
 * 解析事件关联的招式名称。
 *
 * @param moveId 结构化事件关联的 move ID；无关联招式时为 null。
 * @param context 当前 presenter 上下文。
 * @returns 配置中名称优先，其次使用首版内建名称，最后返回稳定 ID fallback。
 */
function moveName(
  moveId: number | null,
  context: BattleReportPresenterContext,
): string {
  if (moveId === null) {
    return '未知招式';
  }
  return context.moveNames[moveId] ?? MOVE_NAMES[moveId] ?? `招式 #${moveId}`;
}

/**
 * 解析 ability、item 或 status 的稳定 source identifier。
 *
 * @param identifier 可能带 ability/item/status 前缀的来源。
 * @returns 已知机制中文名；未知来源返回规范化后的 identifier。
 */
function sourceName(identifier: string | null): string {
  if (identifier === null) {
    return '未知机制';
  }
  const normalized = identifier
    .trim()
    .toLowerCase()
    .replace(/^ability:/, '')
    .replace(/^item:/, '')
    .replace(/^status:/, '')
    .replaceAll('-', '_');
  return SOURCE_NAMES[normalized] ?? normalized.replaceAll('_', ' ');
}

/**
 * 生成开发期可观察、用户侧仍稳定可读的未知事件 fallback。
 *
 * @param event 当前 presenter 尚未识别的结构化事件。
 * @param id 当前路径内稳定生成的展示行 ID。
 * @returns 包含 kind/source 和完整 debug JSON 的未知事件展示行。
 */
function unknownEvent(
  event: BattleEventDetailResult,
  id: string,
): PresentedBattleEvent {
  const debug = JSON.stringify(event);
  console.warn('[battle-report] 未识别结构化事件', event);
  return {
    id,
    turnNumber: event.turn_number,
    kind: event.kind,
    text: `未识别事件：${event.kind}${event.source_identifier ? ` · ${event.source_identifier}` : ''}`,
    tone: 'unknown',
    debug,
  };
}

/**
 * 把一条结构化 BattleEvent 转换为 Showdown 风格展示行。
 *
 * @param event 服务端按真实状态变化产生的结构化事件。
 * @param context Pokémon、最大 HP 和招式名称上下文。
 * @param id 当前路径内稳定生成的展示行 ID。
 * @returns 可展示事件行；纯回合边界或内部编排事件返回 null。
 */
export function presentBattleEvent(
  event: BattleEventDetailResult,
  context: BattleReportPresenterContext,
  id: string,
): PresentedBattleEvent | null {
  const actor = sideName(event.actor, context);
  const target = sideName(event.target, context);
  const usedMove = moveName(event.move_id, context);
  const mechanism = sourceName(event.source_identifier);

  switch (event.kind) {
    case 'turn-started':
    case 'move-selected':
    case 'action-ordered':
    case 'turn-ended':
      return null;
    case 'move-used':
      return { id, turnNumber: event.turn_number, kind: event.kind, text: `${actor}使用了${usedMove}！`, tone: 'move', debug: null };
    case 'action-blocked':
      return {
        id,
        turnNumber: event.turn_number,
        kind: event.kind,
        text: event.source_identifier?.includes('flinch') === true
          ? `${actor}因畏缩无法行动！`
          : `${actor}的行动被${mechanism}阻止了。`,
        tone: 'status',
        debug: null,
      };
    case 'hit':
      return { id, turnNumber: event.turn_number, kind: event.kind, text: `${usedMove}命中了！`, tone: 'success', debug: null };
    case 'miss':
      return { id, turnNumber: event.turn_number, kind: event.kind, text: `${actor}的${usedMove}没有命中！`, tone: 'danger', debug: null };
    case 'damage':
      return { id, turnNumber: event.turn_number, kind: event.kind, text: `${target}失去了 ${Math.abs(event.value ?? 0)} 点 HP。`, tone: 'danger', debug: null };
    case 'hp-changed': {
      const after = event.after_value ?? 0;
      const targetSide = asBattleSide(event.target);
      const maxHp = targetSide === null
        ? Math.max(event.before_value ?? after, after)
        : context.sides[targetSide].maxHp;
      return {
        id,
        turnNumber: event.turn_number,
        kind: event.kind,
        text: `${target}剩余 ${after} / ${maxHp} HP。`,
        tone: after === 0 ? 'danger' : 'neutral',
        debug: null,
      };
    }
    case 'pp-changed':
      return {
        id,
        turnNumber: event.turn_number,
        kind: event.kind,
        text: `${actor}的${usedMove} PP：${event.before_value ?? '?'} → ${event.after_value ?? '?'}。`,
        tone: 'neutral',
        debug: null,
      };
    case 'ability-triggered':
      return { id, turnNumber: event.turn_number, kind: event.kind, text: `${actor}的${mechanism}触发了。`, tone: 'mechanism', debug: null };
    case 'item-triggered':
      return { id, turnNumber: event.turn_number, kind: event.kind, text: `${actor}的道具${mechanism}触发了。`, tone: 'mechanism', debug: null };
    case 'status-applied':
      return {
        id,
        turnNumber: event.turn_number,
        kind: event.kind,
        text: event.source_identifier?.includes('flinch') === true
          ? `${target}畏缩了。`
          : `${target}陷入了${mechanism}状态。`,
        tone: 'status',
        debug: null,
      };
    case 'status-prevented':
      return {
        id,
        turnNumber: event.turn_number,
        kind: event.kind,
        text: event.source_identifier?.includes('flinch') === true
          ? `${target}没有陷入畏缩。`
          : `${target}避免了${mechanism}状态。`,
        tone: 'mechanism',
        debug: null,
      };
    case 'fainted':
      return {
        id,
        turnNumber: event.turn_number,
        kind: event.kind,
        text: `${event.target === null ? actor : target}倒下了。`,
        tone: 'danger',
        debug: null,
      };
    default:
      return unknownEvent(event, id);
  }
}

/**
 * 从同一正式 edge 保留的替代 event paths 中选择稳定展示路径。
 *
 * @param step cursor 中一条实际选择边对应的战报步骤。
 * @returns 第一条事件路径；没有路径时返回空数组。
 */
function selectedEvents(step: BattleReportStepResult): BattleEventDetailResult[] {
  return step.event_paths[0]?.battle_events ?? [];
}

/**
 * 按 cursor step 顺序和路径内事件顺序生成逐回合战报。
 *
 * @param report 当前 exploration response 携带的完整结构化 battle report。
 * @param context Pokémon、最大 HP 和招式名称上下文。
 * @returns 按回合号升序排列、当前路径专属的展示 DTO。
 */
export function presentBattleReport(
  report: BattleReportResult,
  context: BattleReportPresenterContext,
): PresentedBattleReportTurn[] {
  const turns = new Map<number, PresentedBattleReportTurn>();

  for (const step of report.steps) {
    const events = selectedEvents(step);
    const eventTurnNumbers = new Set(events.map((event) => event.turn_number));
    for (const turnNumber of eventTurnNumbers) {
      const existing = turns.get(turnNumber) ?? {
        turnNumber,
        events: [],
        stepDepths: [],
        alternativePathCount: 1,
      };
      if (!existing.stepDepths.includes(step.depth)) {
        existing.stepDepths.push(step.depth);
      }
      existing.alternativePathCount = Math.max(existing.alternativePathCount, step.event_paths.length);

      events.forEach((event, eventIndex) => {
        if (event.turn_number !== turnNumber) {
          return;
        }
        const presented = presentBattleEvent(
          event,
          context,
          `step-${step.depth}:event-${eventIndex}:${event.kind}`,
        );
        if (presented !== null) {
          existing.events.push(presented);
        }
      });
      turns.set(turnNumber, existing);
    }
  }

  return [...turns.values()].sort((left, right) => left.turnNumber - right.turnNumber);
}
