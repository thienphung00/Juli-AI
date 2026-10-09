/**
 * The Đang thực hiện step timeline (AC-8.7, ADR-109 d.13) — pure.
 *
 * Driven ONLY by the run's SSE events (live, or the replayed history of a
 * finished run). Each step's time is its event `timestamp`; its one-line
 * result is `tool.completed.summary`, or the latest
 * `workflow.status.phase_narration` while it runs. Nothing is invented: the
 * only rows not backed by an event are the playbook's not-yet-reached steps,
 * shown greyed as "upcoming" with a label and no time/result.
 *
 * Mapping (d.13's table):
 *   tool.* get_product_diagnoses → "Đọc chẩn đoán TikTok" (summary carries
 *     `Có mã: "…"` / `Không có mã chẩn đoán` / the soft-fail sentence)
 *   tool.* get_product_information / get_seo_keywords / inspect_product_image
 *   workflow.approval_required → "Xác nhận một lần" (inline consent)
 *   tool.* update_product_listing / upload_product_image → "Ghi lên TikTok Shop"
 *   tool.* check_product_status → "TikTok duyệt lại trang sản phẩm"
 *   workflow.completed / workflow.failed → "Kết thúc · đặt lịch đo", day 7 /
 *     day 14 computed from the completion timestamp (D14)
 */

import type { AgentEvent, ConfirmationOptionPayload } from "@juli/contracts";

import {
  CONSENT_STEP_LABEL,
  FIELD_LABELS,
  REVERT_WRITE_LABEL,
  TERMINAL_STEP_LABEL,
  TERMINAL_STEP_LABEL_NO_MEASURE,
  TOOL_STEP_LABELS,
  UNKNOWN_TOOL_LABEL,
} from "./copy";
import { RUN_TERMINAL_STATE_COPY, RUN_TERMINAL_STATE_UNKNOWN_COPY } from "../run-ledger/copy";
import { resolveRunTerminalState } from "../run-ledger/terminal-state";

export type StepStatus = "done" | "current" | "upcoming" | "failed";
export type StepKind = "tool" | "consent" | "terminal";

export interface TimelineStep {
  readonly key: string;
  readonly kind: StepKind;
  readonly label: string;
  readonly status: StepStatus;
  /** Event timestamp (ISO) — absent for upcoming steps. */
  readonly at: string | null;
  /** One-line result from the events, or null. */
  readonly detail: string | null;
}

export interface ConsentRequest {
  readonly toolCallId: string;
  readonly expiresAt: string;
  readonly options: readonly ConfirmationOptionPayload[];
  readonly proposedChange: Record<string, unknown>;
}

export interface RunTimeline {
  readonly steps: readonly TimelineStep[];
  /** Set while the run waits on the seller's two-step consent. */
  readonly pendingConsent: ConsentRequest | null;
  readonly terminal: {
    readonly kind: "completed" | "failed";
    readonly stopReason: string;
    readonly at: string;
    /** Day 7 / day 14 (D14) — only for a run that wrote something. */
    readonly day7: string | null;
    readonly day14: string | null;
  } | null;
  readonly narration: string | null;
}

const CONSENT = "__consent__";
const TERMINAL = "__terminal__";

const OPTIMIZE_PLAN = [
  "get_product_diagnoses",
  "get_product_information",
  "get_seo_keywords",
  "inspect_product_image",
  CONSENT,
  "update_product_listing",
  "check_product_status",
  TERMINAL,
] as const;

const REVERT_PLAN = [
  "get_product_information",
  CONSENT,
  "update_product_listing",
  "check_product_status",
  TERMINAL,
] as const;

const WRITE_TOOLS = new Set(["update_product_listing", "upload_product_image", "update_product_price"]);

const DAY_MS = 86_400_000;

function planIndex(plan: readonly string[], key: string): number {
  if (key === "upload_product_image" || key === "update_product_price") {
    return plan.indexOf("update_product_listing");
  }
  return plan.indexOf(key);
}

export function toolLabel(toolName: string, isRevert = false): string {
  if (isRevert && WRITE_TOOLS.has(toolName)) return REVERT_WRITE_LABEL;
  return TOOL_STEP_LABELS[toolName] ?? UNKNOWN_TOOL_LABEL;
}

/** "Tiêu đề, Mô tả" from a proposed change's keys. */
export function describeProposedChange(change: Record<string, unknown>): string {
  const labels = [...new Set(Object.keys(change).map((key) => FIELD_LABELS[key]).filter(Boolean))];
  return labels.length > 0 ? `Thay đổi: ${labels.join(", ")}` : "Thay đổi trên trang sản phẩm";
}

/** Adds whole days to an ISO timestamp (D14 day 7 / day 14). */
export function addDays(iso: string, days: number): string | null {
  const time = Date.parse(iso);
  return Number.isFinite(time) ? new Date(time + days * DAY_MS).toISOString() : null;
}

function terminalDetail(stopReason: string, day7: string | null, day14: string | null): string {
  if (stopReason === "concurrency_conflict") {
    return "Trường này đã bị thay đổi bên ngoài sau khi Juli ghi — Juli không ghi đè.";
  }
  if (day7 && day14) {
    return `Đo sơ bộ ngày ${vnDate(day7)} (ngày 7), chốt ngày ${vnDate(day14)} (ngày 14).`;
  }
  const key = resolveRunTerminalState(stopReason);
  return (key ? RUN_TERMINAL_STATE_COPY[key] : RUN_TERMINAL_STATE_UNKNOWN_COPY).body;
}

/**
 * Fold the run's events into timeline rows. Idempotent by sequence number,
 * like `reduceRunView` — a reconnect prefix or duplicate frame changes nothing.
 */
export function buildRunTimeline(
  events: readonly AgentEvent[],
  options: { readonly isRevert?: boolean } = {},
): RunTimeline {
  const isRevert = options.isRevert ?? false;
  const plan: readonly string[] = isRevert ? REVERT_PLAN : OPTIMIZE_PLAN;
  const bySeq = new Map<number, AgentEvent>();
  for (const event of events) if (!bySeq.has(event.sequence_number)) bySeq.set(event.sequence_number, event);
  const ordered = [...bySeq.values()].sort((a, b) => a.sequence_number - b.sequence_number);

  type MutableStep = { -readonly [K in keyof TimelineStep]: TimelineStep[K] } & { planKey: string };
  const steps: MutableStep[] = [];
  const byCall = new Map<string, MutableStep>();
  let consent: MutableStep | null = null;
  let consentRequest: ConsentRequest | null = null;
  let narration: string | null = null;
  let wroteSomething = false;
  let terminal: RunTimeline["terminal"] = null;

  for (const event of ordered) {
    switch (event.event_type) {
      case "tool.started": {
        if (consent && consent.status === "current") {
          consent.status = "done";
          consent.detail = consent.detail ?? "Đã xác nhận";
          consentRequest = null;
        }
        const existing = byCall.get(event.payload.tool_call_id);
        if (existing) break;
        const step: MutableStep = {
          key: event.payload.tool_call_id,
          kind: "tool",
          label: toolLabel(event.payload.tool_name, isRevert),
          status: "current",
          at: event.timestamp,
          detail: null,
          planKey: event.payload.tool_name,
        };
        byCall.set(step.key, step);
        steps.push(step);
        break;
      }
      case "tool.completed": {
        let step = byCall.get(event.payload.tool_call_id);
        if (!step) {
          step = {
            key: event.payload.tool_call_id,
            kind: "tool",
            label: toolLabel(event.payload.tool_name, isRevert),
            status: "current",
            at: event.timestamp,
            detail: null,
            planKey: event.payload.tool_name,
          };
          byCall.set(step.key, step);
          steps.push(step);
        }
        step.status = event.payload.ok ? "done" : "failed";
        step.at = event.timestamp;
        step.detail = event.payload.summary || null;
        if (event.payload.ok && WRITE_TOOLS.has(event.payload.tool_name)) wroteSomething = true;
        break;
      }
      case "workflow.approval_required": {
        consent = {
          key: `consent-${event.payload.tool_call_id}`,
          kind: "consent",
          label: CONSENT_STEP_LABEL,
          status: "current",
          at: event.timestamp,
          detail: describeProposedChange(event.payload.proposed_change),
          planKey: CONSENT,
        };
        steps.push(consent);
        consentRequest = {
          toolCallId: event.payload.tool_call_id,
          expiresAt: event.payload.expires_at,
          options: event.payload.options ?? [],
          proposedChange: event.payload.proposed_change,
        };
        break;
      }
      case "workflow.status":
        narration = event.payload.phase_narration || narration;
        break;
      case "assistant.text":
        narration = event.payload.text || narration;
        break;
      case "workflow.completed":
      case "workflow.failed": {
        const stopReason = event.payload.stop_reason;
        if (consent && consent.status === "current") {
          consent.status = stopReason === "confirmation_declined" ? "done" : "failed";
          consent.detail =
            stopReason === "confirmation_declined"
              ? "Bạn đã chọn không thực hiện"
              : stopReason === "confirmation_expired"
                ? "Đề xuất đã hết hạn trước khi bạn xác nhận"
                : consent.detail;
        }
        consentRequest = null;
        const measured = event.event_type === "workflow.completed" && wroteSomething && !isRevert;
        const day7 = measured ? addDays(event.timestamp, 7) : null;
        const day14 = measured ? addDays(event.timestamp, 14) : null;
        terminal = {
          kind: event.event_type === "workflow.completed" ? "completed" : "failed",
          stopReason,
          at: event.timestamp,
          day7,
          day14,
        };
        steps.push({
          key: TERMINAL,
          kind: "terminal",
          label: measured ? TERMINAL_STEP_LABEL : TERMINAL_STEP_LABEL_NO_MEASURE,
          status: event.event_type === "workflow.completed" ? "done" : "failed",
          at: event.timestamp,
          detail: terminalDetail(stopReason, day7, day14),
          planKey: TERMINAL,
        });
        break;
      }
    }
  }

  // A run still going: steps that are not running any more stay done; the
  // last running one carries the latest narration as its live line.
  if (!terminal) {
    const running = [...steps].reverse().find((step) => step.status === "current" && step.kind === "tool");
    if (running && !running.detail && narration) running.detail = narration;
  } else {
    for (const step of steps) if (step.status === "current") step.status = "done";
  }

  const reached = steps.reduce((max, step) => Math.max(max, planIndex(plan, step.planKey)), -1);
  const seen = new Set(steps.map((step) => step.planKey));
  const upcoming: TimelineStep[] = terminal
    ? []
    : plan
        .slice(reached + 1)
        .filter((key) => !seen.has(key))
        .map((key) => ({
          key: `upcoming-${key}`,
          kind: key === CONSENT ? "consent" : key === TERMINAL ? "terminal" : "tool",
          label:
            key === CONSENT
              ? CONSENT_STEP_LABEL
              : key === TERMINAL
                ? isRevert
                  ? TERMINAL_STEP_LABEL_NO_MEASURE
                  : TERMINAL_STEP_LABEL
                : toolLabel(key, isRevert),
          status: "upcoming",
          at: null,
          detail: null,
        }));

  return {
    steps: [
      ...steps.map((step): TimelineStep => ({
        key: step.key,
        kind: step.kind,
        label: step.label,
        status: step.status,
        at: step.at,
        detail: step.detail,
      })),
      ...upcoming,
    ],
    pendingConsent: consentRequest,
    terminal,
    narration,
  };
}

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
