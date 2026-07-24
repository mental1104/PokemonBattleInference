import { computed, onUnmounted, ref, type Ref } from 'vue';
import type { BattleExplorationResult } from '../api/inference';
import type { BattleInferenceJobClient } from '../api/configurationSpaceJobs';
import type {
  ConfigurationIssueResult,
  ConfigurationIssueStatusFilter,
  ConfigurationSpaceJobSnapshot,
  TopConfigurationResult,
  TopConfigurationSort,
} from '../types/configurationSpaceJob';

const POLL_INTERVAL_MS = 2_000;
const TOP_RESULT_LIMIT = 10;
const ISSUE_PAGE_LIMIT = 20;

/** 组件消费的配置空间任务状态与操作集合。 */
export interface ConfigurationSpaceJobState {
  snapshot: Ref<ConfigurationSpaceJobSnapshot | null>;
  topConfigurations: Ref<TopConfigurationResult[]>;
  configurationIssues: Ref<ConfigurationIssueResult[]>;
  topSort: Ref<TopConfigurationSort>;
  issueStatus: Ref<ConfigurationIssueStatusFilter>;
  issueErrorCode: Ref<string>;
  loading: Ref<boolean>;
  topLoading: Ref<boolean>;
  issueLoading: Ref<boolean>;
  cancelling: Ref<boolean>;
  actionMessage: Ref<string>;
  errorMessage: Ref<string>;
  issueNextCursor: Ref<string | null>;
  issueTotal: Ref<number>;
  activeGraphHandle: Ref<BattleExplorationResult | null>;
  activeGraphConfigurationId: Ref<string | null>;
  canLoadMoreIssues: Readonly<Ref<boolean>>;
  start: (jobId: string, client: BattleInferenceJobClient) => Promise<void>;
  stop: () => void;
  selectTopSort: (sort: TopConfigurationSort) => Promise<void>;
  applyIssueFilters: () => Promise<void>;
  loadMoreIssues: () => Promise<void>;
  cancelJob: () => Promise<void>;
  retryConfiguration: (configurationId: string) => Promise<void>;
  exploreConfiguration: (configurationId: string) => Promise<void>;
  closeGraphExplorer: () => void;
}

/**
 * 管理配置空间任务轮询、分页、排序、取消、重试和按需图请求。
 *
 * 页面只保留当前 Top-K 窗口和已加载的问题页；44,100 条配置不会一次性进入内存或 DOM。
 *
 * @returns 可由结果页直接绑定的响应式状态和操作。
 */
export function useConfigurationSpaceJob(): ConfigurationSpaceJobState {
  const snapshot = ref<ConfigurationSpaceJobSnapshot | null>(null);
  const topConfigurations = ref<TopConfigurationResult[]>([]);
  const configurationIssues = ref<ConfigurationIssueResult[]>([]);
  const topSort = ref<TopConfigurationSort>('overall-win-rate');
  const issueStatus = ref<ConfigurationIssueStatusFilter>('all');
  const issueErrorCode = ref('');
  const loading = ref(false);
  const topLoading = ref(false);
  const issueLoading = ref(false);
  const cancelling = ref(false);
  const actionMessage = ref('');
  const errorMessage = ref('');
  const issueNextCursor = ref<string | null>(null);
  const issueTotal = ref(0);
  const activeGraphHandle = ref<BattleExplorationResult | null>(null);
  const activeGraphConfigurationId = ref<string | null>(null);
  const canLoadMoreIssues = computed(
    () => issueNextCursor.value !== null && !issueLoading.value,
  );

  let activeJobId = '';
  let activeClient: BattleInferenceJobClient | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let lifecycleGeneration = 0;
  let snapshotRequestGeneration: number | null = null;

  /** 停止轮询并使旧生命周期中的异步响应失效。 */
  function stop(): void {
    lifecycleGeneration += 1;
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    snapshotRequestGeneration = null;
  }

  /**
   * 判断当前任务是否仍需要轮询。
   *
   * @param current 最新任务快照。
   * @returns queued/running 时返回 true，其余终态返回 false。
   */
  function shouldPoll(current: ConfigurationSpaceJobSnapshot): boolean {
    return current.status === 'queued' || current.status === 'running';
  }

  /**
   * 在活动任务需要持续更新时建立唯一轮询计时器。
   *
   * @param generation 当前页面生命周期序号，用于拒绝旧任务回写。
   */
  function ensurePolling(generation: number): void {
    if (pollTimer !== null || snapshot.value === null || !shouldPoll(snapshot.value)) {
      return;
    }
    pollTimer = setInterval(() => {
      void refreshRunningJob(generation);
    }, POLL_INTERVAL_MS);
  }

  /**
   * 读取最新任务快照，并在任务进入终态时关闭轮询。
   *
   * @param generation 当前页面生命周期序号。
   * @returns 本次请求仍属于当前生命周期时返回最新快照，否则返回 null。
   */
  async function loadSnapshot(
    generation: number,
  ): Promise<ConfigurationSpaceJobSnapshot | null> {
    if (activeClient === null || snapshotRequestGeneration === generation) {
      return null;
    }
    snapshotRequestGeneration = generation;
    try {
      const next = await activeClient.getJob(activeJobId);
      if (generation !== lifecycleGeneration) {
        return null;
      }
      snapshot.value = next;
      if (!shouldPoll(next) && pollTimer !== null) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      return next;
    } finally {
      if (snapshotRequestGeneration === generation) {
        snapshotRequestGeneration = null;
      }
    }
  }

  /**
   * 按当前排序重新读取固定大小的 Top-K 窗口。
   *
   * @param generation 当前页面生命周期序号。
   */
  async function loadTopConfigurations(generation: number): Promise<void> {
    if (activeClient === null) {
      return;
    }
    topLoading.value = true;
    try {
      const items = await activeClient.listTopConfigurations(
        activeJobId,
        topSort.value,
        TOP_RESULT_LIMIT,
      );
      if (generation === lifecycleGeneration) {
        topConfigurations.value = items;
      }
    } finally {
      if (generation === lifecycleGeneration) {
        topLoading.value = false;
      }
    }
  }

  /**
   * 按当前过滤条件读取问题页，并使用配置 ID 保持追加结果稳定去重。
   *
   * @param generation 当前页面生命周期序号。
   * @param reset 是否从首屏重新加载并替换旧列表。
   */
  async function loadConfigurationIssues(
    generation: number,
    reset: boolean,
  ): Promise<void> {
    if (activeClient === null || issueLoading.value) {
      return;
    }
    issueLoading.value = true;
    try {
      const page = await activeClient.listConfigurationIssues(activeJobId, {
        status: issueStatus.value,
        error_code: issueErrorCode.value.trim() || null,
        cursor: reset ? null : issueNextCursor.value,
        limit: ISSUE_PAGE_LIMIT,
      });
      if (generation !== lifecycleGeneration) {
        return;
      }
      const existing = reset ? [] : configurationIssues.value;
      const byId = new Map(existing.map((item) => [item.configuration_id, item]));
      for (const item of page.items) {
        byId.set(item.configuration_id, item);
      }
      configurationIssues.value = [...byId.values()];
      issueNextCursor.value = page.next_cursor;
      issueTotal.value = page.total;
    } finally {
      if (generation === lifecycleGeneration) {
        issueLoading.value = false;
      }
    }
  }

  /**
   * 轮询运行中任务的数量与资源进度，并同步刷新 Top-K 当前窗口。
   *
   * @param generation 当前页面生命周期序号。
   */
  async function refreshRunningJob(generation: number): Promise<void> {
    try {
      const next = await loadSnapshot(generation);
      if (next !== null && generation === lifecycleGeneration) {
        await loadTopConfigurations(generation);
      }
    } catch (error) {
      if (generation === lifecycleGeneration) {
        errorMessage.value = error instanceof Error ? error.message : '任务轮询失败';
      }
    }
  }

  /**
   * 切换到指定 job_id，清理旧任务窗口后并行加载首屏数据。
   *
   * @param jobId 从 URL 恢复或用户打开的稳定任务标识。
   * @param client 与该 job_id 对应的 HTTP、fixture 或测试客户端。
   */
  async function start(jobId: string, client: BattleInferenceJobClient): Promise<void> {
    stop();
    const generation = lifecycleGeneration;
    activeJobId = jobId;
    activeClient = client;
    snapshot.value = null;
    topConfigurations.value = [];
    configurationIssues.value = [];
    issueNextCursor.value = null;
    issueTotal.value = 0;
    activeGraphHandle.value = null;
    activeGraphConfigurationId.value = null;
    actionMessage.value = '';
    errorMessage.value = '';
    loading.value = true;
    topLoading.value = false;
    issueLoading.value = false;
    cancelling.value = false;
    try {
      await Promise.all([
        loadSnapshot(generation),
        loadTopConfigurations(generation),
        loadConfigurationIssues(generation, true),
      ]);
      if (generation === lifecycleGeneration) {
        ensurePolling(generation);
      }
    } catch (error) {
      if (generation === lifecycleGeneration) {
        errorMessage.value = error instanceof Error ? error.message : '任务结果加载失败';
      }
    } finally {
      if (generation === lifecycleGeneration) {
        loading.value = false;
      }
    }
  }

  /**
   * 切换 Top-K 排序并替换当前窗口。
   *
   * @param sort 用户选择且后端声明可用的排序标识。
   */
  async function selectTopSort(sort: TopConfigurationSort): Promise<void> {
    if (topSort.value === sort || activeClient === null) {
      return;
    }
    topSort.value = sort;
    errorMessage.value = '';
    try {
      await loadTopConfigurations(lifecycleGeneration);
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : 'Top-K 加载失败';
    }
  }

  /** 使用当前状态和错误码过滤条件重新读取问题首屏。 */
  async function applyIssueFilters(): Promise<void> {
    issueNextCursor.value = null;
    errorMessage.value = '';
    try {
      await loadConfigurationIssues(lifecycleGeneration, true);
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '失败列表加载失败';
    }
  }

  /** 使用下一页 cursor 追加一个有界问题窗口。 */
  async function loadMoreIssues(): Promise<void> {
    if (!canLoadMoreIssues.value) {
      return;
    }
    try {
      await loadConfigurationIssues(lifecycleGeneration, false);
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '下一页加载失败';
    }
  }

  /** 取消当前任务，同时保留已完成 Top-K 与问题列表。 */
  async function cancelJob(): Promise<void> {
    if (activeClient === null || snapshot.value?.can_cancel !== true) {
      return;
    }
    cancelling.value = true;
    actionMessage.value = '';
    errorMessage.value = '';
    try {
      const next = await activeClient.cancelJob(activeJobId);
      snapshot.value = next;
      actionMessage.value = '任务已取消；已完成配置结果仍保留。';
      if (pollTimer !== null) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '取消任务失败';
    } finally {
      cancelling.value = false;
    }
  }

  /**
   * 调用单个失败或截断配置的重试占位合同。
   *
   * @param configurationId 稳定配置 ID。
   */
  async function retryConfiguration(configurationId: string): Promise<void> {
    if (activeClient === null) {
      return;
    }
    actionMessage.value = '';
    errorMessage.value = '';
    try {
      const result = await activeClient.retryConfiguration(activeJobId, configurationId);
      actionMessage.value = result.message;
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '重试请求失败';
    }
  }

  /**
   * 为一个已完成配置按需申请完整图句柄。
   *
   * @param configurationId 稳定配置 ID；批量结果本身不携带 graph artifact。
   */
  async function exploreConfiguration(configurationId: string): Promise<void> {
    if (activeClient === null) {
      return;
    }
    actionMessage.value = '';
    errorMessage.value = '';
    try {
      const handle = await activeClient.requestConfigurationGraph(
        activeJobId,
        configurationId,
      );
      activeGraphConfigurationId.value = configurationId;
      activeGraphHandle.value = handle;
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '完整图创建失败';
    }
  }

  /** 关闭当前按需图窗口并释放 graph handle 的组件引用。 */
  function closeGraphExplorer(): void {
    activeGraphHandle.value = null;
    activeGraphConfigurationId.value = null;
  }

  onUnmounted(stop);

  return {
    snapshot,
    topConfigurations,
    configurationIssues,
    topSort,
    issueStatus,
    issueErrorCode,
    loading,
    topLoading,
    issueLoading,
    cancelling,
    actionMessage,
    errorMessage,
    issueNextCursor,
    issueTotal,
    activeGraphHandle,
    activeGraphConfigurationId,
    canLoadMoreIssues,
    start,
    stop,
    selectTopSort,
    applyIssueFilters,
    loadMoreIssues,
    cancelJob,
    retryConfiguration,
    exploreConfiguration,
    closeGraphExplorer,
  };
}
