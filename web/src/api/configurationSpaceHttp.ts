import type {
  BattleConfigurationSpaceAdapter,
  CandidateMovePoolRequest,
  CandidateMovePoolResponse,
  CreateBattleConfigurationJobRequest,
  CreateBattleConfigurationJobResponse,
} from '../types/battleConfigurationSpace';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';
export const CONFIGURATION_JOB_CREATED_EVENT = 'battle-configuration-job-created';

interface ApiErrorDetail {
  code?: string;
  message?: string;
  failures?: Array<{
    source_kind?: string;
    requested_identifier?: string;
    status?: string;
    reason?: string;
  }>;
}

interface ApiErrorPayload {
  detail?: string | ApiErrorDetail;
}

/** 表示真实配置空间 API 返回的稳定业务错误。 */
export class BattleConfigurationSpaceApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = 'BattleConfigurationSpaceApiError';
    this.status = status;
    this.code = code;
  }
}

/** 读取 JSON，并把 FastAPI detail 转换为配置页可展示错误。 */
async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  const payload = (await response.json()) as T & ApiErrorPayload;
  if (response.ok) return payload;

  const detail = payload.detail;
  const code = typeof detail === 'object' && detail !== null ? detail.code ?? null : null;
  let message =
    typeof detail === 'string'
      ? detail
      : detail?.message ?? `请求失败：HTTP ${response.status}`;
  if (typeof detail === 'object' && detail?.failures?.length) {
    const failures = detail.failures.map((failure) => {
      const identifier = failure.requested_identifier ?? 'unknown';
      const reason = failure.reason ?? failure.status ?? '机制未通过严格准入';
      return `${identifier}: ${reason}`;
    });
    message = `${message}（${failures.join('；')}）`;
  }
  throw new BattleConfigurationSpaceApiError(response.status, code, message);
}

/** 为一次用户提交生成重试边界内稳定、跨提交不同的幂等键。 */
function idempotencyKey(): string {
  if (typeof crypto.randomUUID === 'function') {
    return `configuration-space-${crypto.randomUUID()}`;
  }
  return `configuration-space-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/** 配置页默认使用的真实 HTTP adapter。 */
export class HttpBattleConfigurationSpaceAdapter
  implements BattleConfigurationSpaceAdapter
{
  async listCandidateMoves(
    request: CandidateMovePoolRequest,
  ): Promise<CandidateMovePoolResponse> {
    const params = new URLSearchParams({
      ruleset_id: request.ruleset_id,
      version_group_id: String(request.version_group_id),
    });
    return requestJson<CandidateMovePoolResponse>(
      `/inference/candidate-pools/${encodeURIComponent(request.pokemon_id)}?${params}`,
      { method: 'GET' },
    );
  }

  async createJob(
    request: CreateBattleConfigurationJobRequest,
  ): Promise<CreateBattleConfigurationJobResponse> {
    const created = await requestJson<CreateBattleConfigurationJobResponse>(
      '/inference/configuration-jobs',
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey(),
        },
        body: JSON.stringify(request),
      },
    );
    window.dispatchEvent(
      new CustomEvent(CONFIGURATION_JOB_CREATED_EVENT, {
        detail: { jobId: created.job_id },
      }),
    );
    return created;
  }
}

export const battleConfigurationSpaceAdapter: BattleConfigurationSpaceAdapter =
  new HttpBattleConfigurationSpaceAdapter();
