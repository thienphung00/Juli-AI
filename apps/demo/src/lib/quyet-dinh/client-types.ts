/**
 * Quyết định's client CONTRACT — network-free (ADR-094 d.1).
 *
 * `QuyetDinhView` (the P10 screens) talks to its data through `QdClients`
 * only. Two implementations exist: the signed-in door's real backend (v1 demo routes)
 * clients (`signed-in-quyet-dinh.tsx` → `api-client.ts` and friends) and the
 * signed-out sample's in-memory fixture clients (`sample-clients.ts`). This
 * file holds only shapes, the error class and pure helpers, so the sample
 * door's module graph never reaches a fetch call site or a backend route literal
 * (`replay-module-graph.test.ts`). `api-client.ts` re-exports the helpers.
 */

import type { AgentEvent, DemoDecisionItem, WorkflowRunListItem } from "@juli/contracts";

import type {
  ConfirmationDecisionKind,
  ConfirmationDecisionResult,
  SubmitConfirmationDecisionOptions,
} from "../run-surface/confirmation-decision";
import type { ContentAnalysisClients } from "../content-analysis/types";
import type { Measurement, PhotoCheck, RunDetail, SellerInstructions } from "./p10-types";
import type { ReasonChoice } from "./reasons";
import type { RevertQuestion, RuleKey, RunChanges, SetBy, ShopRules } from "./types";

export interface AuthedOptions {
  readonly token: string;
  readonly shopId: string;
  readonly fetchImpl?: typeof fetch;
}

/** A non-2xx answer. `message` is the backend's Vietnamese sentence when it sent one. */
export class QdApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string | null,
    public readonly serverMessage: string | null,
    /** The parsed error body (P10: photo checks ride on a 422). */
    public readonly body: unknown = null,
  ) {
    super(serverMessage ?? `Request failed (${status})`);
    this.name = "QdApiError";
  }
}


/** Seller-facing sentence for a failed revert: the backend's own words when given. */
export function describeRevertError(error: unknown): string {
  if (error instanceof QdApiError) {
    if (error.serverMessage && (error.status === 409 || error.status === 503)) return error.serverMessage;
    if (error.status === 429) return "Bạn vừa gửi quá nhiều yêu cầu. Vui lòng thử lại sau ít phút.";
    if (error.status === 404) return "Không tìm thấy lượt chạy này trong shop bạn đang thao tác.";
    if (error.status === 401) return "Phiên đăng nhập của bạn không còn hiệu lực. Vui lòng đăng nhập lại.";
    return `Chưa thể hoàn tác lúc này (lỗi ${error.status}). Vui lòng thử lại.`;
  }
  return "Không thể kết nối. Vui lòng kiểm tra mạng và thử lại.";
}


/** Photo checks from a 202 or a 422 body (`{checks}` at the top, under `data` or under `detail`). */
export function photoChecksOf(body: unknown): PhotoCheck[] | null {
  const candidates = [body, (body as { data?: unknown })?.data, (body as { detail?: unknown })?.detail];
  for (const candidate of candidates) {
    const checks = (candidate as { checks?: unknown } | null)?.checks;
    if (Array.isArray(checks)) {
      return checks
        .filter((c): c is PhotoCheck => !!c && typeof c === "object" && typeof (c as PhotoCheck).label === "string")
        .map((c) => ({
          key: String(c.key),
          label: c.label,
          ok: Boolean(c.ok),
          ...(typeof c.heuristic === "boolean" ? { heuristic: c.heuristic } : {}),
          ...(typeof c.detail === "string" && c.detail ? { detail: c.detail } : {}),
        }));
    }
  }
  return null;
}


/** 409 `external_change` on a revert (Revert.dc.html's conflict branch). */
export function isExternalChange(error: unknown): boolean {
  return error instanceof QdApiError && error.status === 409 && error.code === "external_change";
}

interface DecisionsOptions {
  readonly token: string;
  readonly shopId: string;
  readonly fetchImpl?: typeof fetch;
}

/** A run's event stream as Quyết định reads it: the events so far and the connection's state. */
export interface RunEventsState {
  readonly events: readonly AgentEvent[];
  readonly streamStatus: "idle" | "connecting" | "open" | "reconnecting" | "closed";
}

/**
 * A React hook (called once per rendered run, unconditionally) that yields
 * the run's events. Real: the SSE stream (`useRunStream`); sample: the
 * in-memory store.
 */
export type RunEventsHook = (runId: string, auth: AuthedOptions, streamFetch?: typeof fetch) => RunEventsState;

export interface QdClients {
  readonly fetchDecisions: (options: DecisionsOptions) => Promise<readonly DemoDecisionItem[]>;
  readonly approve: (actionCardId: string, options: DecisionsOptions) => Promise<{ runId: string }>;
  readonly reject: (
    options: AuthedOptions,
    decisionId: string,
    reason: ReasonChoice,
  ) => Promise<{ status: string; cooldown_until: string | null }>;
  readonly fetchRuns: (options: { token?: string; shopId?: string; fetchImpl?: typeof fetch }) => Promise<WorkflowRunListItem[]>;
  readonly fetchRules: (options: AuthedOptions) => Promise<ShopRules>;
  readonly putRule: (options: AuthedOptions, ruleKey: RuleKey, value: unknown, setBy: SetBy, scopeRef?: string | null) => Promise<void>;
  readonly deleteRule: (options: AuthedOptions, ruleKey: RuleKey, scopeRef?: string | null) => Promise<void>;
  readonly fetchChanges: (options: AuthedOptions, runId: string) => Promise<RunChanges>;
  readonly startRevert: (options: AuthedOptions, runId: string, reason?: ReasonChoice) => Promise<{ runId: string }>;
  readonly fetchQuestions: (options: AuthedOptions) => Promise<RevertQuestion[]>;
  readonly dismissQuestion: (options: AuthedOptions, questionId: string) => Promise<void>;
  readonly confirm: (
    runId: string,
    toolCallId: string,
    decision: ConfirmationDecisionKind,
    optionId: string | null,
    options?: SubmitConfirmationDecisionOptions,
  ) => Promise<ConfirmationDecisionResult>;
  readonly decline: (
    options: AuthedOptions,
    runId: string,
    reason: ReasonChoice,
  ) => Promise<{ status: string; cooldown_until: string | null }>;
  readonly uploadPhoto: (options: AuthedOptions, runId: string, file: File) => Promise<PhotoCheck[]>;
  readonly fetchInstructions: (options: AuthedOptions, runId: string) => Promise<SellerInstructions>;
  readonly markApplied: (options: AuthedOptions, runId: string) => Promise<void>;
  readonly fetchMeasurement: (options: AuthedOptions, runId: string) => Promise<Measurement | null>;
  readonly fetchRunDetail: (options: AuthedOptions, runId: string) => Promise<RunDetail>;
  /** P14-E "Dùng kịch bản này" (`p14-content-cards.md` §2.2): version + only the edited blocks. */
  readonly useContent: (
    options: AuthedOptions,
    runId: string,
    version: number,
    editedBlocks?: Readonly<Record<string, string>> | null,
  ) => Promise<void>;
  /** P14-E "Soạn lại". */
  readonly redraftContent: (options: AuthedOptions, runId: string) => Promise<void>;
  /** P14-E "Tôi đã đăng video" / "Tôi đã LIVE xong". */
  readonly markPublished: (options: AuthedOptions, runId: string) => Promise<void>;
  readonly useRunEvents: RunEventsHook;
  /**
   * P15 "Phân tích video" for a content run: the real chunked upload (signed in)
   * or the canned sample (signed out / no shop). Optional: absent → no block.
   */
  readonly analysisClients?: (auth: AuthedOptions) => ContentAnalysisClients;
  /** SSE transport override (tests); the real one is same-origin `fetch`. */
  readonly streamFetch?: typeof fetch;
}
