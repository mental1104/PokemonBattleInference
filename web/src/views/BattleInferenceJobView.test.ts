import { flushPromises, mount } from '@vue/test-utils';
import { defineComponent, h } from 'vue';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BattleExplorationResult } from '../api/inference';
import type { BattleInferenceJobClient } from '../api/configurationSpaceJobs';
import type {
  ConfigurationIssueResult,
  ConfigurationSpaceJobSnapshot,
  TopConfigurationResult,
} from '../types/configurationSpaceJob';
import BattleInferenceJobView from './BattleInferenceJobView.vue';

/** 用可观测 handle 替代渐进图浏览器，隔离其独立 HTTP 交互。 */
const BattleGraphExplorerStub = defineComponent({
  name: 'BattleGraphExplorer',
  props: { handle: { type: Object, required: true } },
  setup(props) {
    return () => h('section', { 'data-test': 'graph-explorer-stub' }, String((props.handle as BattleExplorationResult).graph_id));
  },
});

/**
 * 创建任务结果页使用的完整快照。
 *
 * @param overrides 需要覆盖的顶层字段。
 * @returns 具备进度、预算、覆盖、排序和机制元数据的稳定 DTO。
 */
function jobSnapshot(
  overrides: Partial<ConfigurationSpaceJobSnapshot> = {},
): ConfigurationSpaceJobSnapshot {
  return {
    job_id: 'job-89',
    status: 'running',
    created_at: '2026-07-25T01:00:00Z',
    started_at: '2026-07-25T01:00:04Z',
    completed_at: null,
    updated_at: '2026-07-25T01:05:00Z',
    can_cancel: true,
    stop_reason_code: null,
    stop_reason_message: null,
    counts: {
      total: 44_100,
      completed: 12_000,
      succeeded: 11_400,
      failed: 300,
      truncated: 300,
      running: 24,
      pending: 32_076,
      cancelled: 0,
    },
    resources: {
      state_nodes: { used: 480_000, limit: 2_000_000 },
      edges: { used: 920_000, limit: 5_000_000 },
    },
    aggregate: {
      configuration_coverage_percent: 25.85,
      covered_weight_percent: 27.21,
      unfinished_weight_percent: 72.79,
      covered_probability: { win_percent: 48, loss_percent: 47, draw_percent: 5 },
    },
    metadata: {
      ruleset_id: 'pokemon-champion',
      version_group_id: 25,
      calculation_revision: 'configuration-space.inference.v1',
      configuration_weight_assumption: 'uniform-configuration-pairs',
      attacker_action_policy: 'uniform-random-legal-moves',
      defender_action_policy: 'uniform-random-legal-moves',
      included_mechanisms: ['exact-battle-randomness'],
      excluded_mechanisms: ['switching'],
    },
    top_sort_capabilities: [
      { sort: 'overall-win-rate', available: true, disabled_reason: null },
      { sort: 'worst-matchup', available: true, disabled_reason: null },
      {
        sort: 'expected-winning-turns',
        available: false,
        disabled_reason: '任务运行中，排序尚未稳定',
      },
    ],
    issue_error_codes: ['STATE_NODE_LIMIT_EXCEEDED', 'SOLVER_RESOURCE_LIMIT'],
    ...overrides,
  };
}

/**
 * 创建一个包含完整双方技能组和图规模的 Top-K 配置。
 *
 * @param configurationId 稳定配置 ID。
 * @returns 可触发按需图入口的已完成配置摘要。
 */
function topConfiguration(configurationId: string): TopConfigurationResult {
  return {
    configuration_id: configurationId,
    rank: 1,
    status: 'completed',
    attacker: {
      pokemon_id: 149,
      pokemon_name: '攻击方 #149',
      moves: [
        { move_id: 19, identifier: 'fly', name: '飞翔' },
        { move_id: 85, identifier: 'thunderbolt', name: '十万伏特' },
        { move_id: 245, identifier: 'extreme-speed', name: '神速' },
        { move_id: 280, identifier: 'brick-break', name: '劈瓦' },
      ],
    },
    defender: {
      pokemon_id: 461,
      pokemon_name: '防守方 #461',
      moves: [
        { move_id: 8, identifier: 'ice-punch', name: '冰冻拳' },
        { move_id: 44, identifier: 'bite', name: '咬住' },
        { move_id: 196, identifier: 'icy-wind', name: '冰冻之风' },
        { move_id: 252, identifier: 'fake-out', name: '击掌奇袭' },
      ],
    },
    win_percent: 68.25,
    loss_percent: 28.5,
    draw_percent: 3.25,
    expected_turns: 3.75,
    worst_matchup_win_percent: 41.5,
    graph: { unique_state_count: 240, edge_count: 680, max_turn_number: 8 },
  };
}

/**
 * 创建失败或截断问题项。
 *
 * @param configurationId 稳定配置 ID。
 * @param status 问题类型。
 * @returns 可过滤、分页、重试的诊断摘要。
 */
function configurationIssue(
  configurationId: string,
  status: 'failed' | 'truncated' = 'truncated',
): ConfigurationIssueResult {
  return {
    configuration_id: configurationId,
    status,
    error_code: status === 'failed' ? 'SOLVER_RESOURCE_LIMIT' : 'STATE_NODE_LIMIT_EXCEEDED',
    reason: status === 'failed' ? '求解失败。' : '状态图达到节点预算。',
    diagnostic_summary: '该配置仍保留在覆盖分母中。',
    attacker: topConfiguration('unused').attacker,
    defender: topConfiguration('unused').defender,
    unique_state_count: 2_000,
    edge_count: 5_000,
    max_turn_number: 20,
  };
}

/**
 * 创建所有方法均可观测的任务客户端。
 *
 * @param initialSnapshot 首次读取和取消前使用的任务快照。
 * @returns 可在测试中覆写具体响应的 Vitest mock 客户端。
 */
function mockClient(initialSnapshot = jobSnapshot()): BattleInferenceJobClient {
  return {
    getJob: vi.fn().mockResolvedValue(initialSnapshot),
    cancelJob: vi.fn().mockResolvedValue(jobSnapshot({
      status: 'cancelled',
      can_cancel: false,
      completed_at: '2026-07-25T01:08:00Z',
      stop_reason_code: 'USER_CANCELLED',
      stop_reason_message: '用户取消；已完成结果保留。',
    })),
    listTopConfigurations: vi.fn().mockResolvedValue([topConfiguration('cfg-00000001')]),
    listConfigurationIssues: vi.fn().mockResolvedValue({
      items: [configurationIssue('cfg-issue-00000001')],
      next_cursor: null,
      total: 1,
    }),
    retryConfiguration: vi.fn().mockResolvedValue({
      accepted: false,
      message: '重试操作合同已建立。',
    }),
    requestConfigurationGraph: vi.fn().mockResolvedValue({
      root_node_id: 0,
      graph_id: 'graph-on-demand-1',
      calculation_revision: 'configuration-space.inference.v1',
      expires_at: '2026-07-25T02:00:00Z',
      cursor: { steps: [] },
      expandable: true,
    }),
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe('BattleInferenceJobView', () => {
  it('polls running progress while keeping Top-K and issue DOM bounded', async () => {
    /**
     * 运行中任务必须持续刷新数量与资源快照，但页面只持有固定 Top-10 和当前问题分页窗口。测试使用 fake timer 推进一个轮询周期，让第二次快照把 completed 从 12,000 更新为 13,000；同时构造十条 Top-K 和二十条问题项，断言 DOM 数量严格等于窗口大小而不是任务总量 44,100。期望获胜回合排序在运行中由后端能力声明禁用，避免用户按尚不可用字段排序。
     */
    vi.useFakeTimers();
    const client = mockClient();
    vi.mocked(client.getJob)
      .mockResolvedValueOnce(jobSnapshot())
      .mockResolvedValue(jobSnapshot({
        counts: { ...jobSnapshot().counts, completed: 13_000, succeeded: 12_400, pending: 31_076 },
        resources: {
          state_nodes: { used: 520_000, limit: 2_000_000 },
          edges: { used: 990_000, limit: 5_000_000 },
        },
      }));
    vi.mocked(client.listTopConfigurations).mockResolvedValue(
      Array.from({ length: 10 }, (_, index) => topConfiguration(`cfg-${index}`)),
    );
    vi.mocked(client.listConfigurationIssues).mockResolvedValue({
      items: Array.from({ length: 20 }, (_, index) => configurationIssue(`issue-${index}`)),
      next_cursor: 'cursor-20',
      total: 1_180,
    });

    const wrapper = mount(BattleInferenceJobView, {
      props: { jobId: 'job-89', client },
      global: { stubs: { BattleGraphExplorer: BattleGraphExplorerStub } },
    });
    await flushPromises();

    expect(wrapper.text()).toContain('12,000 / 44,100');
    expect(wrapper.findAll('[data-test="top-configuration-item"]')).toHaveLength(10);
    expect(wrapper.findAll('[data-test="configuration-issue-item"]')).toHaveLength(20);
    expect(wrapper.get('[data-test="sort-expected-winning-turns"]').attributes('disabled')).toBeDefined();

    await vi.advanceTimersByTimeAsync(2_000);
    await flushPromises();

    expect(wrapper.text()).toContain('13,000 / 44,100');
    expect(client.getJob).toHaveBeenCalledTimes(2);
    expect(wrapper.findAll('[data-test="top-configuration-item"]')).toHaveLength(10);
  });

  it('shows covered probability beside coverage, unfinished weight and explicit stop reason', async () => {
    /**
     * 部分完成结果不能把已覆盖配置中的概率冒充为全空间胜率。测试注入达到节点预算的 partial 快照，要求同一区域同时出现“已覆盖配置中的胜负平概率”、配置覆盖率、未完成权重和稳定停止代码，并确认任务状态具有独立的“部分覆盖”语义。终态快照同时开放期望获胜回合排序，证明排序可用性来自服务端合同而不是页面猜测。
     */
    const partial = jobSnapshot({
      status: 'partial',
      can_cancel: false,
      completed_at: '2026-07-25T01:18:42Z',
      stop_reason_code: 'STATE_NODE_BUDGET_EXHAUSTED',
      stop_reason_message: '累计状态节点达到任务预算。',
      aggregate: {
        configuration_coverage_percent: 64.25,
        covered_weight_percent: 67.66,
        unfinished_weight_percent: 32.34,
        covered_probability: { win_percent: 51.5, loss_percent: 43.25, draw_percent: 5.25 },
      },
      top_sort_capabilities: [
        { sort: 'overall-win-rate', available: true, disabled_reason: null },
        { sort: 'worst-matchup', available: true, disabled_reason: null },
        { sort: 'expected-winning-turns', available: true, disabled_reason: null },
      ],
    });
    const wrapper = mount(BattleInferenceJobView, {
      props: { jobId: 'job-partial', client: mockClient(partial) },
      global: { stubs: { BattleGraphExplorer: BattleGraphExplorerStub } },
    });
    await flushPromises();

    expect(wrapper.get('[data-test="job-status"]').text()).toBe('部分覆盖');
    expect(wrapper.get('[data-test="aggregate-summary"]').text()).toContain('已覆盖配置中的胜负平概率');
    expect(wrapper.get('[data-test="aggregate-summary"]').text()).toContain('64.25%');
    expect(wrapper.get('[data-test="aggregate-summary"]').text()).toContain('32.34%');
    expect(wrapper.get('[data-test="stop-reason"]').text()).toContain('STATE_NODE_BUDGET_EXHAUSTED');
    expect(wrapper.get('[data-test="sort-expected-winning-turns"]').attributes('disabled')).toBeUndefined();
  });

  it('uses stable filters and cursor pagination without duplicating configuration IDs', async () => {
    /**
     * 失败与截断列表通过状态、错误代码和稳定 cursor 分页，而不是把全部问题项一次性渲染。测试让第二页故意重复第一页的一个 configuration_id，再追加一个新项；加载更多后页面必须只保留三个唯一配置。随后切换为 failed 过滤，客户端应收到状态、空 cursor、当前错误码和固定 20 条页大小，旧分页窗口被新查询替换。
     */
    const client = mockClient();
    vi.mocked(client.listConfigurationIssues)
      .mockResolvedValueOnce({
        items: [configurationIssue('issue-1'), configurationIssue('issue-2')],
        next_cursor: 'cursor-2',
        total: 3,
      })
      .mockResolvedValueOnce({
        items: [configurationIssue('issue-2'), configurationIssue('issue-3', 'failed')],
        next_cursor: null,
        total: 3,
      })
      .mockResolvedValueOnce({
        items: [configurationIssue('issue-3', 'failed')],
        next_cursor: null,
        total: 1,
      });
    const wrapper = mount(BattleInferenceJobView, {
      props: { jobId: 'job-89', client },
      global: { stubs: { BattleGraphExplorer: BattleGraphExplorerStub } },
    });
    await flushPromises();

    await wrapper.get('[data-test="load-more-issues"]').trigger('click');
    await flushPromises();
    expect(wrapper.findAll('[data-test="configuration-issue-item"]')).toHaveLength(3);

    await wrapper.get('[data-test="issue-status-filter"]').setValue('failed');
    await flushPromises();
    expect(wrapper.findAll('[data-test="configuration-issue-item"]')).toHaveLength(1);
    expect(client.listConfigurationIssues).toHaveBeenLastCalledWith('job-89', {
      status: 'failed',
      error_code: null,
      cursor: null,
      limit: 20,
    });
  });

  it('preserves completed results after cancellation and opens graphs only on demand', async () => {
    /**
     * 取消操作只停止剩余工作，不能清除已完成 Top-K；批量摘要也不能偷偷携带完整图。测试先取消运行任务并确认配置卡仍在，再点击已完成配置的“按需探索完整图”，要求客户端使用 job_id 与 configuration_id 调用独立入口，并把返回 handle 交给现有 GraphExplorer。最后点击失败项重试按钮，验证当前版本至少具备明确操作合同和用户反馈。
     */
    const client = mockClient();
    const wrapper = mount(BattleInferenceJobView, {
      props: { jobId: 'job-89', client },
      global: { stubs: { BattleGraphExplorer: BattleGraphExplorerStub } },
    });
    await flushPromises();

    await wrapper.get('[data-test="cancel-job"]').trigger('click');
    await flushPromises();
    expect(wrapper.get('[data-test="job-status"]').text()).toBe('已取消');
    expect(wrapper.findAll('[data-test="top-configuration-item"]')).toHaveLength(1);

    await wrapper.get('[data-test="explore-configuration"]').trigger('click');
    await flushPromises();
    expect(client.requestConfigurationGraph).toHaveBeenCalledWith('job-89', 'cfg-00000001');
    expect(wrapper.get('[data-test="graph-explorer-stub"]').text()).toBe('graph-on-demand-1');
    expect(wrapper.get('[data-test="on-demand-graph"]').text()).toContain('批量摘要未携带 graph artifact');

    await wrapper.get('[data-test="retry-configuration"]').trigger('click');
    await flushPromises();
    expect(client.retryConfiguration).toHaveBeenCalledWith('job-89', 'cfg-issue-00000001');
    expect(wrapper.text()).toContain('重试操作合同已建立。');
  });
});
