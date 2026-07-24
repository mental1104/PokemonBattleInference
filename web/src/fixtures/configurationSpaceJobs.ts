import type { BattleExplorationResult } from '../api/inference';
import type { BattleInferenceJobClient } from '../api/configurationSpaceJobs';
import type {
  ConfigurationIssueQuery,
  ConfigurationIssueResult,
  ConfigurationMoveSummary,
  ConfigurationRetryResult,
  ConfigurationRunStatus,
  ConfigurationSideSummary,
  ConfigurationSpaceJobSnapshot,
  CursorPage,
  TopConfigurationResult,
  TopConfigurationSort,
} from '../types/configurationSpaceJob';

const TOTAL_CONFIGURATION_PAIRS = 44_100;
const TOP_RESULT_LIMIT = 10;
const ISSUE_TOTAL = 1_180;

const MOVES: ConfigurationMoveSummary[] = [
  { move_id: 8, identifier: 'ice-punch', name: '冰冻拳' },
  { move_id: 19, identifier: 'fly', name: '飞翔' },
  { move_id: 21, identifier: 'slam', name: '摔打' },
  { move_id: 44, identifier: 'bite', name: '咬住' },
  { move_id: 53, identifier: 'flamethrower', name: '喷射火焰' },
  { move_id: 58, identifier: 'ice-beam', name: '冰冻光束' },
  { move_id: 85, identifier: 'thunderbolt', name: '十万伏特' },
  { move_id: 89, identifier: 'earthquake', name: '地震' },
  { move_id: 126, identifier: 'fire-blast', name: '大字爆炎' },
  { move_id: 196, identifier: 'icy-wind', name: '冰冻之风' },
  { move_id: 225, identifier: 'dragon-breath', name: '龙息' },
  { move_id: 242, identifier: 'crunch', name: '咬碎' },
  { move_id: 245, identifier: 'extreme-speed', name: '神速' },
  { move_id: 252, identifier: 'fake-out', name: '击掌奇袭' },
  { move_id: 280, identifier: 'brick-break', name: '劈瓦' },
  { move_id: 337, identifier: 'dragon-claw', name: '龙爪' },
];

/**
 * 从稳定招式池中生成四招无序技能组。
 *
 * @param seed 配置序号，用于确定性地旋转候选招式。
 * @returns 固定包含四个不同招式的展示数组。
 */
function moveSet(seed: number): ConfigurationMoveSummary[] {
  const selected: ConfigurationMoveSummary[] = [];
  for (let offset = 0; selected.length < 4; offset += 1) {
    const candidate = MOVES[(seed * 3 + offset * 5) % MOVES.length];
    if (!selected.some((move) => move.move_id === candidate.move_id)) {
      selected.push(candidate);
    }
  }
  return selected.sort((left, right) => left.move_id - right.move_id);
}

/**
 * 构造不依赖固定 Pokémon 名称的配置侧摘要。
 *
 * @param side 配置侧标识，用于生成不同 Pokémon ID 与技能组。
 * @param seed 配置序号。
 * @returns 包含 Pokémon 名称和完整技能组的只读摘要。
 */
function sideSummary(side: 'attacker' | 'defender', seed: number): ConfigurationSideSummary {
  const baseId = side === 'attacker' ? 149 : 461;
  return {
    pokemon_id: baseId + (seed % 3),
    pokemon_name: side === 'attacker' ? `攻击方 #${baseId + (seed % 3)}` : `防守方 #${baseId + (seed % 3)}`,
    moves: moveSet(seed + (side === 'attacker' ? 0 : 7)),
  };
}

/**
 * 创建运行中、部分完成、取消或失败场景共用的任务快照。
 *
 * @param jobId fixture 任务标识。
 * @param status 当前任务状态。
 * @param completed 已完成配置对数量。
 * @returns 与真实后台 DTO 同形的任务快照。
 */
function snapshot(
  jobId: string,
  status: ConfigurationSpaceJobSnapshot['status'],
  completed: number,
): ConfigurationSpaceJobSnapshot {
  const failed = Math.min(540, Math.floor(completed * 0.025));
  const truncated = Math.min(220, Math.floor(completed * 0.012));
  const normalizedSucceeded = Math.max(0, completed - failed - truncated);
  const running = status === 'running' ? 24 : 0;
  const pending = Math.max(0, TOTAL_CONFIGURATION_PAIRS - completed - running);
  const coverage = Number(((normalizedSucceeded / TOTAL_CONFIGURATION_PAIRS) * 100).toFixed(2));
  const coveredWeight = Number(((completed / TOTAL_CONFIGURATION_PAIRS) * 100).toFixed(2));
  const terminal = status !== 'queued' && status !== 'running';
  const partial = status === 'partial';
  const cancelled = status === 'cancelled';
  const failedJob = status === 'failed';

  return {
    job_id: jobId,
    status,
    created_at: '2026-07-25T01:00:00Z',
    started_at: '2026-07-25T01:00:04Z',
    completed_at: terminal ? '2026-07-25T01:18:42Z' : null,
    updated_at: terminal ? '2026-07-25T01:18:42Z' : '2026-07-25T01:08:16Z',
    can_cancel: status === 'queued' || status === 'running',
    stop_reason_code: partial
      ? 'STATE_NODE_BUDGET_EXHAUSTED'
      : cancelled
        ? 'USER_CANCELLED'
        : failedJob
          ? 'WORKER_UNAVAILABLE'
          : null,
    stop_reason_message: partial
      ? '累计状态节点达到任务预算，未完成配置保持独立权重。'
      : cancelled
        ? '任务已由用户取消；取消前完成的结果仍可浏览。'
        : failedJob
          ? '任务级 worker 失败，已完成配置未被丢弃。'
          : null,
    counts: {
      total: TOTAL_CONFIGURATION_PAIRS,
      completed,
      succeeded: normalizedSucceeded,
      failed,
      truncated,
      running,
      pending,
      cancelled: cancelled ? pending : 0,
    },
    resources: {
      state_nodes: {
        used: Math.min(2_000_000, completed * 31),
        limit: 2_000_000,
      },
      edges: {
        used: Math.min(5_000_000, completed * 74),
        limit: 5_000_000,
      },
    },
    aggregate: {
      configuration_coverage_percent: coverage,
      covered_weight_percent: coveredWeight,
      unfinished_weight_percent: Number((100 - coveredWeight).toFixed(2)),
      covered_probability: {
        win_percent: 48.37,
        loss_percent: 46.12,
        draw_percent: 5.51,
      },
    },
    metadata: {
      ruleset_id: 'pokemon-champion',
      version_group_id: 25,
      calculation_revision: 'configuration-space.inference.v1',
      configuration_weight_assumption: 'uniform-configuration-pairs',
      attacker_action_policy: 'uniform-random-legal-moves',
      defender_action_policy: 'uniform-random-legal-moves',
      included_mechanisms: [
        'fixed-pokemon-profile',
        'version-group-aware-moves',
        'exact-battle-randomness',
      ],
      excluded_mechanisms: ['switching', 'external-ladder-usage-weight'],
    },
    top_sort_capabilities: [
      { sort: 'overall-win-rate', available: true, disabled_reason: null },
      { sort: 'worst-matchup', available: completed > 0, disabled_reason: completed > 0 ? null : '尚无已完成配置' },
      {
        sort: 'expected-winning-turns',
        available: terminal,
        disabled_reason: terminal ? null : '任务运行中，期望获胜回合排序尚未稳定',
      },
    ],
    issue_error_codes: [
      'STATE_NODE_LIMIT_EXCEEDED',
      'EDGE_LIMIT_EXCEEDED',
      'MAX_TURNS_REACHED',
      'SOLVER_RESOURCE_LIMIT',
    ],
  };
}

/**
 * 生成一个稳定配置 ID 对应的 Top-K 结果。
 *
 * @param index 排序窗口中的零基序号。
 * @param sort 当前排序指标。
 * @returns 不携带完整 graph artifact 的批量摘要。
 */
function topResult(index: number, sort: TopConfigurationSort): TopConfigurationResult {
  const seed = sort === 'overall-win-rate' ? index : sort === 'worst-matchup' ? index + 20 : index + 40;
  const win = Number((82.5 - index * 2.15).toFixed(2));
  const draw = Number((2.5 + (index % 3) * 0.75).toFixed(2));
  const status: ConfigurationRunStatus = index === 8 ? 'truncated' : index === 9 ? 'running' : 'completed';
  return {
    configuration_id: `cfg-${String(seed + 1).padStart(8, '0')}`,
    rank: index + 1,
    status,
    attacker: sideSummary('attacker', seed),
    defender: sideSummary('defender', seed),
    win_percent: status === 'completed' ? win : null,
    loss_percent: status === 'completed' ? Number((100 - win - draw).toFixed(2)) : null,
    draw_percent: status === 'completed' ? draw : null,
    expected_turns: status === 'completed' ? Number((2.1 + index * 0.31).toFixed(2)) : null,
    worst_matchup_win_percent: status === 'completed' ? Number((34.8 + index * 1.2).toFixed(2)) : null,
    graph: status === 'completed'
      ? {
          unique_state_count: 120 + index * 17,
          edge_count: 286 + index * 39,
          max_turn_number: 6 + (index % 4),
        }
      : null,
  };
}

/**
 * 生成失败或截断列表中的一个稳定配置诊断。
 *
 * @param index 全局问题序号。
 * @returns 可通过配置 ID 去重和分页排序的诊断项。
 */
function issueResult(index: number): ConfigurationIssueResult {
  const truncated = index % 3 !== 0;
  const errorCodes = truncated
    ? ['STATE_NODE_LIMIT_EXCEEDED', 'EDGE_LIMIT_EXCEEDED', 'MAX_TURNS_REACHED']
    : ['SOLVER_RESOURCE_LIMIT'];
  const errorCode = errorCodes[index % errorCodes.length];
  return {
    configuration_id: `cfg-issue-${String(index + 1).padStart(8, '0')}`,
    status: truncated ? 'truncated' : 'failed',
    error_code: errorCode,
    reason: truncated ? '配置状态图在预算边界处显式截断。' : '配置求解未产生可用概率结果。',
    diagnostic_summary: truncated
      ? '保留已展开节点和稳定停止原因，未把未知后继视为平局。'
      : '失败配置仍计入覆盖分母，可通过重试入口重新调度。',
    attacker: sideSummary('attacker', index + 80),
    defender: sideSummary('defender', index + 100),
    unique_state_count: truncated ? 2_000 + index : 340 + index,
    edge_count: truncated ? 5_000 + index * 2 : 780 + index * 2,
    max_turn_number: truncated ? 20 : 8 + (index % 5),
  };
}

/**
 * 解析 fixture cursor 中的稳定偏移。
 *
 * @param cursor 上一页返回的 cursor；首屏为 null。
 * @returns 非负列表偏移，非法 cursor 回退到首屏。
 */
function cursorOffset(cursor: string | null): number {
  if (cursor === null) {
    return 0;
  }
  const parsed = Number.parseInt(cursor.replace('offset:', ''), 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

/**
 * 供 Issue #89 页面独立开发与验收的内存任务客户端。
 *
 * 它只按当前页生成 Top-K 和问题列表，不会为 44,100 条配置预先创建 DOM 或对象数组。
 */
class FixtureBattleInferenceJobClient implements BattleInferenceJobClient {
  private status: ConfigurationSpaceJobSnapshot['status'];
  private completed: number;

  /**
   * 创建指定场景的 fixture 客户端。
   *
   * @param jobId fixture 任务 ID；名称中的 partial/cancelled/failed 决定初始状态。
   */
  constructor(private readonly jobId: string) {
    if (jobId.includes('partial')) {
      this.status = 'partial';
      this.completed = 29_840;
    } else if (jobId.includes('cancelled')) {
      this.status = 'cancelled';
      this.completed = 18_420;
    } else if (jobId.includes('failed')) {
      this.status = 'failed';
      this.completed = 8_460;
    } else if (jobId.includes('complete')) {
      this.status = 'completed';
      this.completed = TOTAL_CONFIGURATION_PAIRS;
    } else {
      this.status = 'running';
      this.completed = 17_640;
    }
  }

  /** @inheritdoc */
  async getJob(): Promise<ConfigurationSpaceJobSnapshot> {
    if (this.status === 'running') {
      // 每次轮询只推进有限窗口，模拟后台持续写入而不瞬间完成任务。
      this.completed = Math.min(TOTAL_CONFIGURATION_PAIRS, this.completed + 735);
      if (this.completed === TOTAL_CONFIGURATION_PAIRS) {
        this.status = 'completed';
      }
    }
    return snapshot(this.jobId, this.status, this.completed);
  }

  /** @inheritdoc */
  async cancelJob(): Promise<ConfigurationSpaceJobSnapshot> {
    if (this.status === 'running' || this.status === 'queued') {
      this.status = 'cancelled';
    }
    return snapshot(this.jobId, this.status, this.completed);
  }

  /** @inheritdoc */
  async listTopConfigurations(
    _jobId: string,
    sort: TopConfigurationSort,
    limit: number,
  ): Promise<TopConfigurationResult[]> {
    return Array.from(
      { length: Math.min(limit, TOP_RESULT_LIMIT) },
      (_, index) => topResult(index, sort),
    );
  }

  /** @inheritdoc */
  async listConfigurationIssues(
    _jobId: string,
    query: ConfigurationIssueQuery,
  ): Promise<CursorPage<ConfigurationIssueResult>> {
    const matching: ConfigurationIssueResult[] = [];
    const offset = cursorOffset(query.cursor);
    let scanIndex = offset;
    while (matching.length < query.limit && scanIndex < ISSUE_TOTAL) {
      const item = issueResult(scanIndex);
      const statusMatches = query.status === 'all' || item.status === query.status;
      const codeMatches = query.error_code === null || item.error_code === query.error_code;
      if (statusMatches && codeMatches) {
        matching.push(item);
      }
      scanIndex += 1;
    }
    return {
      items: matching,
      next_cursor: scanIndex < ISSUE_TOTAL ? `offset:${scanIndex}` : null,
      total: ISSUE_TOTAL,
    };
  }

  /** @inheritdoc */
  async retryConfiguration(
    _jobId: string,
    configurationId: string,
  ): Promise<ConfigurationRetryResult> {
    return {
      accepted: false,
      message: `${configurationId} 已形成重试操作合同；等待后台 API 接线后正式调度。`,
    };
  }

  /** @inheritdoc */
  async requestConfigurationGraph(
    _jobId: string,
    configurationId: string,
  ): Promise<BattleExplorationResult> {
    return {
      root_node_id: 0,
      graph_id: `fixture-graph-${configurationId}`,
      calculation_revision: 'configuration-space.inference.v1',
      expires_at: '2026-07-25T02:30:00Z',
      cursor: { steps: [] },
      expandable: true,
    };
  }
}

/**
 * 创建与真实 API 合同一致的 fixture 客户端。
 *
 * @param jobId 以 fixture- 开头的场景标识。
 * @returns 只按当前窗口生成数据的内存客户端。
 */
export function createFixtureBattleInferenceJobClient(
  jobId: string,
): BattleInferenceJobClient {
  return new FixtureBattleInferenceJobClient(jobId);
}
