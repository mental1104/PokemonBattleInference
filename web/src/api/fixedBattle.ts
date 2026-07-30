import type { BattleJourneyResult } from './inference';
import type {
  FixedBattleSummaryRequest,
  FixedBattleSummaryResult,
  MoveSetCombinationsRequest,
  MoveSetCombinationsResult,
} from '../types/fixedBattle';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

interface ApiFailureDetail {
  requested_identifier?: string;
  reason?: string;
  status?: string;
}

interface ApiErrorDetail {
  code?: string;
  message?: string;
  failures?: ApiFailureDetail[];
}

interface ApiErrorPayload {
  detail?: string | ApiErrorDetail;
}

/** 表示组合预览或固定精确推演返回的稳定业务错误。 */
export class FixedBattleApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  /**
   * 创建前端可展示的固定推演错误。
   *
   * @param status HTTP 状态码。
   * @param code 后端稳定业务错误码；响应未提供时为 null。
   * @param message 已包含结构化准入失败摘要的可读文本。
   */
  constructor(status: number, code: string | null, message: string) {
    super(message);
    this.name = 'FixedBattleApiError';
    this.status = status;
    this.code = code;
  }
}

/**
 * 调用固定推演 JSON API，并把 FastAPI detail 转换为页面错误。
 *
 * @param path `/api/v1` 之后的资源路径。
 * @param body 可直接 JSON 序列化的请求 DTO。
 * @returns 后端响应的类型化 JSON。
 */
async function postJson<RequestT, ResponseT>(
  path: string,
  body: RequestT,
): Promise<ResponseT> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload = (await response.json()) as ResponseT & ApiErrorPayload;
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
      return `${identifier}: ${failure.reason ?? failure.status ?? '机制未通过准入'}`;
    });
    message = `${message}（${failures.join('；')}）`;
  }
  throw new FixedBattleApiError(response.status, code, message);
}

/** 只生成左右技能组合，不创建 configuration job。 */
export function enumerateMoveSetCombinations(
  request: MoveSetCombinationsRequest,
): Promise<MoveSetCombinationsResult> {
  return postJson<MoveSetCombinationsRequest, MoveSetCombinationsResult>(
    '/inference/move-set-combinations',
    request,
  );
}

/** 对用户选定的一个双方配置快照计算精确胜负平摘要。 */
export function inferFixedBattleSummary(
  request: FixedBattleSummaryRequest,
): Promise<FixedBattleSummaryResult> {
  return postJson<FixedBattleSummaryRequest, FixedBattleSummaryResult>(
    '/inference/fixed-one-on-one',
    request,
  );
}

/**
 * 对用户选定的固定配置求解，并返回可渐进探索的完整图句柄。
 *
 * @param request 与 summary-only 入口相同的固定配置请求。
 * @returns 包含全局 summary 和 graph exploration handle 的顶层结果。
 */
export function inferFixedBattleJourney(
  request: FixedBattleSummaryRequest,
): Promise<BattleJourneyResult> {
  return postJson<FixedBattleSummaryRequest, BattleJourneyResult>(
    '/inference/fixed-one-on-one/graph',
    request,
  );
}
