/**
 * The Đang thực hiện step timeline (AC-8.7 → AC-10.3; `Run.dc.html`,
 * `RunPhoto.dc.html`, `RunManual.dc.html`, `Revert.dc.html`) — pure.
 *
 * Driven by the run's SSE events (live, or the replayed history of a
 * finished run) plus `run.awaiting` (P10 contract §4/§5). Each run kind has a
 * fixed plan of rows in the artboard's order; an event fills its row with
 * the event time and `tool.completed.summary`. Rows not reached yet stay
 * greyed (no time, no result); after "Không thực hiện" they read "Bỏ qua".
 * Tools the plan does not name are inserted where they happened, never
 * dropped.
 *
 *   listing  Đọc chẩn đoán TikTok · Đọc thông tin sản phẩm · Phân tích từ khoá ·
 *            Phân tích ảnh sản phẩm · Xác nhận một lần · Ghi lên TikTok Shop ·
 *            TikTok duyệt lại trang sản phẩm · Kết thúc · đặt lịch đo
 *   photo    Đọc chẩn đoán TikTok · Phân tích ảnh hiện tại · Chờ ảnh từ bạn ·
 *            Kiểm tra ảnh mới · Xác nhận một lần · Tải ảnh lên TikTok Shop ·
 *            TikTok duyệt lại trang sản phẩm · Kết thúc · đặt lịch đo
 *   manual   Đọc giá và khuyến mãi hiện có · Kiểm tra quy tắc bạn đặt · Soạn
 *            hướng dẫn · Áp dụng trên Seller Center (Bạn) · Kiểm tra trên
 *            TikTok · Kết thúc · đặt lịch đo — promotion tools have no fixed
 *            names yet (P10-B), so the tools before the pause fill the first
 *            three rows in order and the tools after it are the verification.
 *   revert   Bạn bấm Hoàn tác · Cho Juli biết lý do · Đọc nội dung hiện tại
 *            trên TikTok · Kiểm tra có ai sửa ngoài Juli · Xác nhận một lần ·
 *            Ghi lại nội dung cũ lên TikTok Shop · TikTok duyệt lại trang sản
 *            phẩm · Kết thúc · dừng đo
 *
 * The pause point (photo / seller action) is the first `workflow.status`
 * whose narration starts with "Đang chờ" (contract §4: "Đang chờ ảnh từ bạn").
 */

import type { AgentEvent, ConfirmationOptionPayload } from "@juli/contracts";

import { FIELD_LABELS } from "./copy";
import { RUN_TERMINAL_STATE_COPY, RUN_TERMINAL_STATE_UNKNOWN_COPY } from "../run-ledger/copy";
import { resolveRunTerminalState } from "../run-ledger/terminal-state";

export type StepStatus = "done" | "current" | "upcoming" | "failed" | "skipped";
export type StepKind = "tool" | "consent" | "terminal" | "await";
/** `content` (P14-E): a "Juli soạn · bạn làm" run — its panel reads the run detail's `content.steps`. */
export type RunKind = "listing" | "photo" | "manual" | "revert" | "content";
export type Who = "juli" | "you";

export interface TimelineStep {
  readonly key: string;
  readonly kind: StepKind;
  readonly label: string;
  readonly status: StepStatus;
  /** Event timestamp (ISO) — absent for steps not reached. */
  readonly at: string | null;
  /** One-line result, or null. */
  readonly detail: string | null;
  /** "Juli" / "Bạn" chip (RunManual.dc.html only). */
  readonly who?: Who;
}

export interface ConsentRequest {
  readonly toolCallId: string;
  readonly toolName: string;
  readonly expiresAt: string;
  readonly options: readonly ConfirmationOptionPayload[];
  readonly proposedChange: Record<string, unknown>;
}

export interface RunTimeline {
  readonly steps: readonly TimelineStep[];
  /** Set while the run waits on the seller's consent. */
  readonly pendingConsent: ConsentRequest | null;
  readonly terminal: {
    readonly kind: "completed" | "failed";
    readonly stopReason: string;
    readonly at: string;
    /** Day 7 / day 14 (D14) — only for a run that wrote (or verified) something. */
    readonly day7: string | null;
    readonly day14: string | null;
  } | null;
  readonly narration: string | null;
  /** The tool running right now (no completion yet), if any. */
  readonly runningTool: string | null;
  /** A write tool completed ok. */
  readonly wrote: boolean;
  /** Tool calls seen after the pause point (manual: the TikTok verification). */
  readonly toolsAfterPause: number;
}

export interface TimelineOptions {
  readonly isRevert?: boolean;
  readonly kind?: RunKind;
  readonly awaiting?: "photo" | "seller_action" | "content_choice" | "content_publish" | null;
  /** Photo checks the seller's upload got this visit (contract §4). */
  readonly photoChecks?: readonly { readonly label: string; readonly ok: boolean }[] | null;
  /** Revert run: when it was started and the reason the seller gave. */
  readonly revertStartedAt?: string | null;
  readonly revertReason?: string | null;
  /** Revert run: the fields Juli restores (for the conflict line). */
  readonly revertFieldLabels?: readonly string[];
}

export const STEP_COPY = {
  consentWaiting: "Đang chờ bạn",
  consentDone: "Bạn đã xác nhận",
  consentDeclined: "Bạn chọn không thực hiện",
  consentExpired: "Đề xuất đã hết hạn trước khi bạn xác nhận",
  skipped: "Bỏ qua",
  photoWaiting: "Đang chờ bạn",
  photoReceived: "Đã nhận ảnh",
  sellerWaiting: "Đang chờ bạn",
  sellerApplied: "Bạn báo đã áp dụng",
  sellerDeclined: "Bạn chọn không áp dụng",
  revertNoConflict: "Không ai sửa · an toàn để khôi phục",
  revertTerminal: 'Thay đổi ghi nhận "Đã hoàn tác"',
} as const;

const PHOTO_STAGE_TOOL = "upload_product_image";
const WRITE_TOOLS = new Set(["update_product_listing", "upload_product_image", "update_product_price"]);
const DAY_MS = 86_400_000;

// -- plans ------------------------------------------------------------------------

type PseudoType = "awaitPhoto" | "photoCheck" | "awaitSeller" | "revertClicked" | "revertReason" | "revertCheck";

type RowSpec =
  | { readonly type: "tool"; readonly key: string; readonly label: string; readonly tools: readonly string[]; readonly who?: Who }
  | { readonly type: "slot"; readonly key: string; readonly label: string; readonly slot: number; readonly who?: Who }
  | { readonly type: "verify"; readonly key: string; readonly label: string; readonly who?: Who }
  | { readonly type: "consent"; readonly key: string; readonly label: string; readonly who?: Who }
  | { readonly type: PseudoType; readonly key: string; readonly label: string; readonly who?: Who }
  | { readonly type: "terminal"; readonly key: string; readonly label: string; readonly who?: Who };

const CONSENT_ROW: RowSpec = { type: "consent", key: "consent", label: "Xác nhận một lần" };
const REVIEW_ROW: RowSpec = { type: "tool", key: "review", label: "TikTok duyệt lại trang sản phẩm", tools: ["check_product_status"] };
const MEASURE_END: RowSpec = { type: "terminal", key: "terminal", label: "Kết thúc · đặt lịch đo" };

export const PLANS: Readonly<Record<RunKind, readonly RowSpec[]>> = {
  listing: [
    { type: "tool", key: "diag", label: "Đọc chẩn đoán TikTok", tools: ["get_product_diagnoses"] },
    { type: "tool", key: "info", label: "Đọc thông tin sản phẩm", tools: ["get_product_information"] },
    { type: "tool", key: "seo", label: "Phân tích từ khoá", tools: ["get_seo_keywords"] },
    { type: "tool", key: "image", label: "Phân tích ảnh sản phẩm", tools: ["inspect_product_image"] },
    CONSENT_ROW,
    { type: "tool", key: "write", label: "Ghi lên TikTok Shop", tools: ["update_product_listing", "update_product_price"] },
    REVIEW_ROW,
    MEASURE_END,
  ],
  photo: [
    { type: "tool", key: "diag", label: "Đọc chẩn đoán TikTok", tools: ["get_product_diagnoses"] },
    { type: "tool", key: "image", label: "Phân tích ảnh hiện tại", tools: ["inspect_product_image", "get_product_information"] },
    { type: "awaitPhoto", key: "await-photo", label: "Chờ ảnh từ bạn" },
    { type: "photoCheck", key: "photo-check", label: "Kiểm tra ảnh mới" },
    CONSENT_ROW,
    // P10-B stages the photo (`upload_product_image`) BEFORE the consent and the
    // consent is on `update_product_listing`, which is what changes the cover.
    { type: "tool", key: "write", label: "Tải ảnh lên TikTok Shop", tools: ["update_product_listing"] },
    REVIEW_ROW,
    MEASURE_END,
  ],
  manual: [
    { type: "slot", key: "read", label: "Đọc giá và khuyến mãi hiện có", slot: 0, who: "juli" },
    { type: "slot", key: "rules", label: "Kiểm tra quy tắc bạn đặt", slot: 1, who: "juli" },
    { type: "slot", key: "guide", label: "Soạn hướng dẫn", slot: 2, who: "juli" },
    { type: "awaitSeller", key: "await-seller", label: "Áp dụng trên Seller Center", who: "you" },
    { type: "verify", key: "verify", label: "Kiểm tra trên TikTok", who: "juli" },
    { type: "terminal", key: "terminal", label: "Kết thúc · đặt lịch đo", who: "juli" },
  ],
  content: [
    { type: "tool", key: "read-content", label: "Đọc số liệu nội dung", tools: ["get_content_performance"] },
    {
      type: "tool",
      key: "read-product",
      label: "Đọc thông tin sản phẩm",
      tools: ["get_product_information", "get_seo_keywords", "find_product_promotions", "get_seller_content_rules"],
    },
    { type: "tool", key: "detect", label: "Tìm video / phiên LIVE mới", tools: ["find_new_content"] },
    MEASURE_END,
  ],
  revert: [
    { type: "revertClicked", key: "clicked", label: "Bạn bấm Hoàn tác" },
    { type: "revertReason", key: "reason", label: "Cho Juli biết lý do" },
    { type: "tool", key: "read", label: "Đọc nội dung hiện tại trên TikTok", tools: ["get_product_information"] },
    { type: "revertCheck", key: "check", label: "Kiểm tra có ai sửa ngoài Juli" },
    CONSENT_ROW,
    {
      type: "tool",
      key: "write",
      label: "Ghi lại nội dung cũ lên TikTok Shop",
      tools: ["update_product_listing", "upload_product_image", "update_product_price"],
    },
    REVIEW_ROW,
    { type: "terminal", key: "terminal", label: "Kết thúc · dừng đo" },
  ],
};

/** Label for a tool the plan does not name. */
export const TOOL_STEP_LABELS: Readonly<Record<string, string>> = Object.freeze({
  get_product_diagnoses: "Đọc chẩn đoán TikTok",
  get_product_information: "Đọc thông tin sản phẩm",
  get_seo_keywords: "Phân tích từ khoá",
  inspect_product_image: "Phân tích ảnh sản phẩm",
  update_product_listing: "Ghi lên TikTok Shop",
  upload_product_image: "Tải ảnh lên TikTok Shop",
  update_product_price: "Cập nhật giá trên TikTok Shop",
  check_product_status: "TikTok duyệt lại trang sản phẩm",
  get_content_performance: "Đọc số liệu nội dung",
  get_seller_content_rules: "Đọc Quy tắc của bạn",
  find_product_promotions: "Đọc khuyến mãi",
  find_new_content: "Tìm video / phiên LIVE mới",
});
export const UNKNOWN_TOOL_LABEL = "Bước xử lý";

export function toolLabel(toolName: string): string {
  return TOOL_STEP_LABELS[toolName] ?? UNKNOWN_TOOL_LABEL;
}

/** "Thay đổi: Tiêu đề, Mô tả" from a proposed change's keys. */
export function describeProposedChange(change: Record<string, unknown>): string {
  const labels = [...new Set(Object.keys(change).map((key) => FIELD_LABELS[key]).filter(Boolean))];
  return labels.length > 0 ? `Thay đổi: ${labels.join(", ")}` : "Thay đổi trên trang sản phẩm";
}

/** Adds whole days to an ISO timestamp (D14 day 7 / day 14). */
export function addDays(iso: string, days: number): string | null {
  const time = Date.parse(iso);
  return Number.isFinite(time) ? new Date(time + days * DAY_MS).toISOString() : null;
}

// -- fold -------------------------------------------------------------------------

interface ToolCall {
  readonly id: string;
  readonly name: string;
  startedAt: string;
  completedAt: string | null;
  ok: boolean | null;
  summary: string | null;
  readonly afterPause: boolean;
}

function dedupe(events: readonly AgentEvent[]): AgentEvent[] {
  const bySeq = new Map<number, AgentEvent>();
  for (const event of events) if (!bySeq.has(event.sequence_number)) bySeq.set(event.sequence_number, event);
  return [...bySeq.values()].sort((a, b) => a.sequence_number - b.sequence_number);
}

function measuredTerminalDetail(day7: string | null, day14: string | null): string | null {
  if (!day7 || !day14) return null;
  return `Đo sơ bộ ${vnDate(day7).slice(0, 5)} (ngày 7) · chốt ${vnDate(day14).slice(0, 5)} (ngày 14)`;
}

function endedDetail(stopReason: string): string {
  if (stopReason === "concurrency_conflict") {
    return "Trường này đã bị thay đổi bên ngoài sau khi Juli ghi — Juli không ghi đè.";
  }
  const key = resolveRunTerminalState(stopReason);
  return (key ? RUN_TERMINAL_STATE_COPY[key] : RUN_TERMINAL_STATE_UNKNOWN_COPY).body;
}

/**
 * Fold the run's events into timeline rows. Idempotent by sequence number —
 * a reconnect prefix or a duplicate frame changes nothing.
 */
export function buildRunTimeline(events: readonly AgentEvent[], options: TimelineOptions = {}): RunTimeline {
  const kind: RunKind = options.isRevert ? "revert" : (options.kind ?? "listing");
  const plan = PLANS[kind];
  const ordered = dedupe(events);

  const calls: ToolCall[] = [];
  const byId = new Map<string, ToolCall>();
  let pauseSeq: number | null = null;
  let pauseSeen = false;
  let firstAfterPauseAt: string | null = null;
  let consentEvent: { seq: number; at: string; request: ConsentRequest } | null = null;
  let consentDecidedAt: string | null = null;
  let narration: string | null = null;
  let textBeforePause = false;
  const box: { terminal: RunTimeline["terminal"] } = { terminal: null };
  let wrote = false;

  for (const event of ordered) {
    if (pauseSeq !== null && firstAfterPauseAt === null && event.sequence_number > pauseSeq) {
      firstAfterPauseAt = event.timestamp;
    }
    switch (event.event_type) {
      case "tool.started":
      case "tool.completed": {
        let call = byId.get(event.payload.tool_call_id);
        if (!call) {
          call = {
            id: event.payload.tool_call_id,
            name: event.payload.tool_name,
            startedAt: event.timestamp,
            completedAt: null,
            ok: null,
            summary: null,
            afterPause: pauseSeen,
          };
          byId.set(call.id, call);
          calls.push(call);
        }
        if (consentEvent && !consentDecidedAt && event.sequence_number > consentEvent.seq) {
          consentDecidedAt = event.timestamp;
        }
        if (event.event_type === "tool.completed") {
          call.completedAt = event.timestamp;
          call.ok = event.payload.ok;
          call.summary = event.payload.summary || null;
          if (event.payload.ok && WRITE_TOOLS.has(event.payload.tool_name)) wrote = true;
        }
        break;
      }
      case "workflow.approval_required":
        consentEvent = {
          seq: event.sequence_number,
          at: event.timestamp,
          request: {
            toolCallId: event.payload.tool_call_id,
            toolName: event.payload.tool_name,
            expiresAt: event.payload.expires_at,
            options: event.payload.options ?? [],
            proposedChange: event.payload.proposed_change,
          },
        };
        consentDecidedAt = null;
        break;
      case "workflow.status": {
        const text = event.payload.phase_narration || "";
        if (text) narration = text;
        if (!pauseSeen && /^Đang chờ/.test(text)) {
          pauseSeen = true;
          pauseSeq = event.sequence_number;
        }
        break;
      }
      case "assistant.text":
        narration = event.payload.text || narration;
        if (!pauseSeen && event.payload.text) textBeforePause = true;
        break;
      case "workflow.completed":
      case "workflow.failed": {
        const stopReason = event.payload.stop_reason;
        const verified = kind === "manual" && calls.some((call) => call.afterPause && call.ok);
        const measured = event.event_type === "workflow.completed" && kind !== "revert" && (wrote || verified);
        box.terminal = {
          kind: event.event_type === "workflow.completed" ? "completed" : "failed",
          stopReason,
          at: event.timestamp,
          day7: measured ? addDays(event.timestamp, 7) : null,
          day14: measured ? addDays(event.timestamp, 14) : null,
        };
        break;
      }
    }
  }

  const terminal = box.terminal;
  const awaiting = options.awaiting ?? null;
  const declined = terminal?.stopReason === "confirmation_declined" || terminal?.stopReason === "cancelled_by_seller";
  const conflict = terminal?.stopReason === "concurrency_conflict";
  const ended = terminal !== null;
  const endedNormally = ended && !declined && !conflict;

  // Assign tool calls to plan rows.
  const assigned = new Map<string, ToolCall[]>();
  const extras: { call: ToolCall; afterKey: string | null }[] = [];
  let lastKey: string | null = null;
  for (const call of calls) {
    let rowKey: string | null = null;
    if (kind === "photo" && call.name === PHOTO_STAGE_TOOL && !consentEvent) {
      // Staging the seller's photo on TikTok is part of "Kiểm tra ảnh mới".
      continue;
    }
    if (kind === "manual") {
      // P10-B's promotion run: price + existing promotions are read before the
      // pause (`get_product_information`, `find_product_promotions`), the rules
      // check is narrated, and every tool after the pause verifies on TikTok.
      rowKey = call.afterPause ? "verify" : "read";
    } else {
      rowKey = plan.find((spec) => spec.type === "tool" && spec.tools.includes(call.name))?.key ?? null;
    }
    if (rowKey) {
      assigned.set(rowKey, [...(assigned.get(rowKey) ?? []), call]);
      lastKey = rowKey;
    } else {
      extras.push({ call, afterKey: lastKey });
    }
  }

  let furthest = -1;
  plan.forEach((spec, i) => {
    if (assigned.has(spec.key) || (spec.type === "consent" && consentEvent)) furthest = Math.max(furthest, i);
  });

  const rows: TimelineStep[] = [];

  const toolRow = (spec: RowSpec, list: ToolCall[]): TimelineStep => {
    const last = list[list.length - 1];
    const running = list.some((call) => call.ok === null) && !ended;
    const failed = list.some((call) => call.ok === false);
    return {
      key: spec.key,
      kind: "tool",
      label: spec.label,
      status: running ? "current" : failed ? "failed" : "done",
      at: last.completedAt ?? last.startedAt,
      detail: last.summary ?? (running ? narration : null),
      who: spec.who,
    };
  };

  const notReached = (spec: RowSpec, rowKind: StepKind): TimelineStep => ({
    key: spec.key,
    kind: rowKind,
    label: spec.label,
    status: declined || conflict ? "skipped" : "upcoming",
    at: null,
    detail: declined || conflict ? STEP_COPY.skipped : null,
    who: spec.who,
  });

  const pseudo = (spec: RowSpec, rowKind: StepKind, status: StepStatus, at: string | null, detail: string | null): TimelineStep => ({
    key: spec.key,
    kind: rowKind,
    label: spec.label,
    status,
    at,
    detail,
    who: spec.who,
  });

  plan.forEach((spec, index) => {
    switch (spec.type) {
      case "tool":
      case "slot":
      case "verify": {
        const list = assigned.get(spec.key);
        const manualDone =
          kind === "manual" &&
          spec.type === "slot" &&
          (pauseSeen || awaiting === "seller_action" || (spec.slot === 1 && textBeforePause));
        if (list && list.length > 0) {
          rows.push(toolRow(spec, list));
        } else if (manualDone) {
          rows.push(pseudo(spec, "tool", "done", null, null));
        } else if (endedNormally) {
          // A finished run that never called this tool: manual rows still
          // happened (the backend may batch them), listing tools were skipped.
          if (kind === "manual") rows.push(pseudo(spec, "tool", "done", null, null));
        } else if (spec.type === "tool" && index < furthest) {
          // A tool this run skipped — it will not come back.
        } else {
          rows.push(notReached(spec, "tool"));
        }
        break;
      }
      case "consent": {
        if (!consentEvent) {
          rows.push(notReached(spec, "consent"));
          break;
        }
        const expired = terminal?.stopReason === "confirmation_expired";
        const waiting = !ended && !consentDecidedAt;
        const detail = waiting
          ? STEP_COPY.consentWaiting
          : declined && !consentDecidedAt
            ? STEP_COPY.consentDeclined
            : expired
              ? STEP_COPY.consentExpired
              : STEP_COPY.consentDone;
        rows.push(pseudo(spec, "consent", waiting ? "current" : expired ? "failed" : "done", consentEvent.at, detail));
        break;
      }
      case "awaitPhoto": {
        if (awaiting === "photo" && !ended) rows.push(pseudo(spec, "await", "current", null, STEP_COPY.photoWaiting));
        else if (consentEvent || firstAfterPauseAt || endedNormally) rows.push(pseudo(spec, "await", "done", firstAfterPauseAt, STEP_COPY.photoReceived));
        else if (pauseSeen && !ended) rows.push(pseudo(spec, "await", "current", null, STEP_COPY.photoWaiting));
        else rows.push(notReached(spec, "await"));
        break;
      }
      case "photoCheck": {
        const checks = options.photoChecks ?? null;
        const line = checks && checks.length > 0 ? checks.map((check) => check.label).join(" · ") : null;
        if (consentEvent || endedNormally) rows.push(pseudo(spec, "tool", "done", consentEvent?.at ?? null, line));
        else if (awaiting !== "photo" && firstAfterPauseAt && !ended) rows.push(pseudo(spec, "tool", "current", firstAfterPauseAt, line ?? narration));
        else rows.push(notReached(spec, "tool"));
        break;
      }
      case "awaitSeller": {
        if (awaiting === "seller_action" && !ended) rows.push(pseudo(spec, "await", "current", null, STEP_COPY.sellerWaiting));
        else if (declined) rows.push(pseudo(spec, "await", "done", terminal?.at ?? null, STEP_COPY.sellerDeclined));
        else if (assigned.has("verify") || (ended && terminal?.kind === "completed")) {
          rows.push(pseudo(spec, "await", "done", firstAfterPauseAt, STEP_COPY.sellerApplied));
        } else if (pauseSeen && !ended) rows.push(pseudo(spec, "await", "current", null, STEP_COPY.sellerWaiting));
        else rows.push(notReached(spec, "await"));
        break;
      }
      case "revertClicked":
        rows.push(pseudo(spec, "await", "done", options.revertStartedAt ?? null, options.revertStartedAt ? vnDate(options.revertStartedAt) : null));
        break;
      case "revertReason":
        rows.push(pseudo(spec, "await", "done", options.revertStartedAt ?? null, options.revertReason ?? null));
        break;
      case "revertCheck": {
        if (conflict) {
          const fields = (options.revertFieldLabels ?? []).join(", ") || "Nội dung";
          rows.push(pseudo(spec, "tool", "failed", terminal?.at ?? null, `${fields} đã bị sửa ngoài Juli — dừng`));
        } else if (consentEvent || assigned.has("write") || (ended && terminal?.kind === "completed")) {
          rows.push(pseudo(spec, "tool", "done", consentEvent?.at ?? null, STEP_COPY.revertNoConflict));
        } else if (assigned.has("read") && !ended) {
          rows.push(pseudo(spec, "tool", "current", null, narration));
        } else {
          rows.push(notReached(spec, "tool"));
        }
        break;
      }
      case "terminal": {
        if (!terminal || declined || conflict) {
          rows.push(notReached(spec, "terminal"));
          break;
        }
        const measured = measuredTerminalDetail(terminal.day7, terminal.day14);
        const detail =
          terminal.kind === "completed" && kind === "revert"
            ? STEP_COPY.revertTerminal
            : (measured ?? endedDetail(terminal.stopReason));
        rows.push(pseudo(spec, "terminal", terminal.kind === "completed" ? "done" : "failed", terminal.at, detail));
        break;
      }
    }
  });

  // Tools the plan does not name: insert right after the row they followed.
  for (const { call, afterKey } of extras) {
    const at = afterKey ? rows.findIndex((row) => row.key === afterKey) + 1 : 0;
    const running = call.ok === null && !ended;
    rows.splice(at, 0, {
      key: `tool-${call.id}`,
      kind: "tool",
      label: toolLabel(call.name),
      status: running ? "current" : call.ok === false ? "failed" : "done",
      at: call.completedAt ?? call.startedAt,
      detail: call.summary ?? (running ? narration : null),
    });
  }

  // Exactly one "current" row: the first.
  let seenCurrent = false;
  const steps = rows.map((row): TimelineStep => {
    if (row.status !== "current") return row;
    if (seenCurrent) return { ...row, status: "upcoming", at: null, detail: null };
    seenCurrent = true;
    return row;
  });

  const running = ended ? null : (calls.find((call) => call.ok === null) ?? null);
  return {
    steps,
    pendingConsent: consentEvent && !consentDecidedAt && !ended ? consentEvent.request : null,
    terminal,
    narration,
    runningTool: running?.name ?? null,
    wrote,
    toolsAfterPause: calls.filter((call) => call.afterPause).length,
  };
}

// -- Vietnam time -------------------------------------------------------------------

const VN_TIME_ZONE = "Asia/Ho_Chi_Minh";

function vnParts(iso: string, options: Intl.DateTimeFormatOptions): Record<string, string> | null {
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return null;
  const parts = new Intl.DateTimeFormat("en-GB", { ...options, timeZone: VN_TIME_ZONE }).formatToParts(new Date(time));
  return Object.fromEntries(parts.map((part) => [part.type, part.value]));
}

/** ISO → `dd/mm/yyyy` in Vietnam time. */
export function vnDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const p = vnParts(iso, { year: "numeric", month: "2-digit", day: "2-digit" });
  return p ? `${p.day}/${p.month}/${p.year}` : "—";
}

/** ISO → `HH:MM:SS` in Vietnam time. */
export function vnTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const p = vnParts(iso, { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
  return p ? `${p.hour}:${p.minute}:${p.second}` : "";
}
