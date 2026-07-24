import type { BattleExplorationResult } from './inference';
import { createFixtureBattleInferenceJobClient } from '../fixtures/configurationSpaceJobs';
import type {
  ConfigurationIssueQuery,
  ConfigurationIssueResult,
  ConfigurationRetryResult,
  ConfigurationSpaceJobSnapshot,
  CursorPage,
  TopConfigurationResult,
  TopConfigurationSort,
} from '../types/configurationSpaceJob';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

/** 首页未携带真实 job_id 时用于演示 44,100 配置规模的 fixture 任务。 */
export const DEFAULT_CONFIGURATION_SPACE_FIXTURE_JOB_ID = 'fixture-running-44100';

/**
 * 配置空间结果页依赖的可替换客户端合同。
 *
 * HTTP adapter、前端 fixture 与组件测试 fake 均实现同一组方法，页面不依赖后台
 * worker、数据库或具体 transport 细节。
 */
export interface BattleInferenceJobClient {
  /**
   * 读取任务最新生命周期、数量进度、资源预算和聚合摘要。
   *
   * @param jobId 后台任务稳定标识。
   * @returns 当前任务快照。
   */
  getJob(jobId: string): Promise<ConfigurationSpaceJobSnapshot>;

  /**
   * 请求取消仍在运行的任务；已完成结果必须继续可读。
   *
   * @param jobId 后台任务稳定标识。
   * @returns 取消后的任务快照。
   */
  cancelJob(jobId: string): Promise<ConfigurationSpaceJobSnapshot>;

  /**
   * 按指定指标读取当前 Top-K 窗口。
   *
   * @param jobId 后台任务稳定标识。
   * @param sort 后端支持的稳定排序标识。
   * @param limit 本次最多返回的配置数量。
   * @returns 当前排序下的配置窗口。
   */
  listTopConfigurations(
    jobId: string,
    sort: TopConfigurationSort,
    limit: number,
  ): Promise<TopConfigurationResult[]>;

  /**
   * 使用稳定 cursor 分页读取失败或截断配置。
   *
   * @param jobId 后台任务稳定标识。
   * @param query 状态、错误码、cursor 与页大小。
   * @returns 当前分页窗口以及下一页 cursor。
   */
  listConfigurationIssues(
    jobId: string,
    query: ConfigurationIssueQuery,
  ): Promise<CursorPage<ConfigurationIssueResult>>;

  /**
   * 提交单个失败或截断配置的重试操作合同。
   *
   * @param jobId 后台任务稳定标识。
   * @param configurationId 稳定配置 ID。
   * @returns 后台是否接受请求及可展示说明。
   */
  retryConfiguration(
    jobId: string,
    configurationId: string,
  ): Promise<ConfigurationRetryResult>;

  /**
   * 按需构建并返回单个已完成配置的完整图句柄。
   *
   * @param jobId 后台任务稳定标识。
   * @param configurationId 稳定配置 ID。
   * @returns 可交给现有渐进图浏览器的 graph handle。
   */
  requestConfigurationGraph(
    jobId: string,
    configurationId: string,
  ): Promise<BattleExplorationResult>;
}

interface ApiErrorDetail {
  code?: string;
  message?: string;
}

interface ApiErrorPayload {
  detail?: string | ApiErrorDetail;
}

/** 表示配置空间任务 API 返回的稳定 HTTP 错误。 */
export class ConfigurationSpaceJobApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  /**
   * 创建可供结果页展示稳定错误码的 API 异常。
   *
   * @param status HTTP 状态码。
   * @param code 服务端业务错误码；普通字符串错误时为 null。
   * @param message 用户可读错误文本。
   */
  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = 'ConfigurationSpaceJobApiError';
    this.status = status;
    this.code = code;
  }
}

/**
 * 读取配置空间 JSON 响应并统一转换 FastAPI detail 错误。
 *
 * @param path 相对于 `/api/v1` 的接口路径。
 * @param init fetch 请求参数。
 * @returns 通过泛型声明的 JSON 响应。
 * @throws ConfigurationSpaceJobApiError 当服务端返回非 2xx 状态时抛出。
 */
async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  const payload = (await response.json()) as T & ApiErrorPayload;
  if (!response.ok) {
    const detail = payload.detail;
    const code = typeof detail === 'object' && detail !== null ? detail.code ?? null : null;
    const message =
      typeof detail === 'string'
        ? detail
        : detail?.message ?? `请求失败：HTTP ${response.status}`;
    throw new ConfigurationSpaceJobApiError(response.status, code, message);
  }
  return payload;
}

/**
 * 面向未来后台 API 的 HTTP adapter。
 *
 * 路径只表达 Issue #89 需要的操作合同；worker/API 正式接线后页面无需修改。
 */
export class HttpBattleInferenceJobClient implements BattleInferenceJobClient {
  /** @inheritdoc */
  async getJob(jobId: string): Promise<ConfigurationSpaceJobSnapshot> {
    return requestJson<ConfigurationSpaceJobSnapshot>(
      `/inference/configuration-jobs/${encodeURIComponent(jobId)}`,
      { method: 'GET' },
    );
  }

  /** @inheritdoc */
  async cancelJob(jobId: string): Promise<ConfigurationSpaceJobSnapshot> {
    return requestJson<ConfigurationSpaceJobSnapshot>(
      `/inference/configuration-jobs/${encodeURIComponent(jobId)}/cancel`,
      { method: 'POST' },
    );
  }

  /** @inheritdoc */
  async listTopConfigurations(
    jobId: string,
    sort: TopConfigurationSort,
    limit: number,
  ): Promise<TopConfigurationResult[]> {
    const params = new URLSearchParams({ sort, limit: String(limit) });
    return requestJson<TopConfigurationResult[]>(
      `/inference/configuration-jobs/${encodeURIComponent(jobId)}/top-configurations?${params}`,
      { method: 'GET' },
    );
  }

  /** @inheritdoc */
  async listConfigurationIssues(
    jobId: string,
    query: ConfigurationIssueQuery,
  ): Promise<CursorPage<ConfigurationIssueResult>> {
    const params = new URLSearchParams({
      status: query.status,
      limit: String(query.limit),
    });
    if (query.error_code !== null) {
      params.set('error_code', query.error_code);
    }
    if (query.cursor !== null) {
      params.set('cursor', query.cursor);
    }
    return requestJson<CursorPage<ConfigurationIssueResult>>(
      `/inference/configuration-jobs/${encodeURIComponent(jobId)}/issues?${params}`,
      { method: 'GET' },
    );
  }

  /** @inheritdoc */
  async retryConfiguration(
    jobId: string,
    configurationId: string,
  ): Promise<ConfigurationRetryResult> {
    return requestJson<ConfigurationRetryResult>(
      `/inference/configuration-jobs/${encodeURIComponent(jobId)}/configurations/${encodeURIComponent(configurationId)}/retry`,
      { method: 'POST' },
    );
  }

  /** @inheritdoc */
  async requestConfigurationGraph(
    jobId: string,
    configurationId: string,
  ): Promise<BattleExplorationResult> {
    return requestJson<BattleExplorationResult>(
      `/inference/configuration-jobs/${encodeURIComponent(jobId)}/configurations/${encodeURIComponent(configurationId)}/graph`,
      { method: 'POST' },
    );
  }
}

/**
 * 根据 job_id 选择真实 HTTP adapter 或可独立开发的 fixture adapter。
 *
 * @param jobId 页面从 URL 恢复的任务标识。
 * @returns fixture 前缀使用内存客户端，其他标识使用 HTTP 客户端。
 */
export function createBattleInferenceJobClient(jobId: string): BattleInferenceJobClient {
  if (jobId.startsWith('fixture-')) {
    return createFixtureBattleInferenceJobClient(jobId);
  }
  return new HttpBattleInferenceJobClient();
}
