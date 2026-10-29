/**
 * The signed-out Quyết định's data source: `QdClients` over an in-memory
 * store seeded from `sample-data.ts` (ADR-094 d.1 — no fetch call site, no
 * backend route literal anywhere in this module's graph). Approving,
 * rejecting, confirming, uploading a photo, "Tôi đã áp dụng" and Hoàn tác
 * change this store only; the run then plays its next contract events on
 * a short timer so the P10 timeline moves the way a real run does. Nothing
 * survives a reload, nothing reaches TikTok Shop.
 *
 * P37 (D47.2, owner 2026-10-16): a card's status follows the real lifecycle.
 * The store keeps each card's desk status the way `ActionCard.status` does
 * (active / approved / dismissed / expired) and derives the seller-facing
 * status exactly like the backend's `card_view._status`:
 *
 * - active → `pending`, or `expired` once 7 days have passed since it
 *   surfaced (`PROPOSAL_VALIDITY_DAYS`);
 * - Duyệt → approved; the run starts `queued`, then `running` (consent /
 *   waiting_external) → completed. Approved shows `applied` only when the
 *   latest run completed AND recorded a write; Seller Center / promotion and
 *   content runs record none, so they stay `running`, as in the real view;
 * - Từ chối, a declined consent, "Không thực hiện" and Hoàn tác close the card
 *   (`close_card` → dismissed → `rejected`, 7-day cooldown);
 * - a failed / cancelled / timed-out run puts the card back on the desk
 *   (`pending`).
 *
 * Two deterministic seams exercise the paths a click cannot reach:
 * `advanceTime` (the reviewer / test "tua nhanh": consent windows lapse →
 * cancelled, external waits lapse → timed_out, untouched cards expire) and
 * `failRun` (a run that fails on its own). Both are sample-only and say
 * nothing about a real shop.
 */

import { useCallback, useSyncExternalStore } from "react";

import type { AgentEvent, DemoDecisionItem, WorkflowRunListItem } from "@juli/contracts";

import { createSampleAnalysisClients } from "../content-analysis/sample";
import type { QdClients, RunEventsState } from "./client-types";
import type { CardStatus, Measurement, PhotoCheck, QdRun, RunAwaiting, RunDetail } from "./p10-types";
import {
  SAMPLE_APPLIED_CARD,
  SAMPLE_CARDS,
  SAMPLE_CONTENT_CARDS,
  SAMPLE_FINISHED_CHANGES,
  SAMPLE_FINISHED_RUN_ID,
  SAMPLE_INSTRUCTIONS,
  SAMPLE_PHOTO_CHECKS,
  contentPublished,
  contentPublishWait,
  contentRedraft,
  contentUntilChoice,
  endDraft,
  executorOf,
  failDraft,
  finishedListingEvents,
  listingUntilConsent,
  manualUntilGuide,
  manualVerify,
  photoToConsent,
  photoUntilUpload,
  revertUntilConsent,
  sampleChanges,
  sampleContentDecision,
  sampleContentDetail,
  sampleContentMeasurement,
  sampleDay7Measurement,
  sampleDecision,
  sampleRules,
  sampleSimulatedMeasurement,
  sampleWaitingMeasurement,
  toEvents,
  writeAndReview,
  type EventDraft,
  type SampleCardSpec,
  type SampleContentSpec,
  type SampleContentState,
} from "./sample-data";
import type { FieldChange, RunChanges, ShopRules } from "./types";

const DAY_MS = 86_400_000;
const HOUR_MS = 3_600_000;
/** P15: one stable canned-analysis client (no network). */
const SAMPLE_ANALYSIS_CLIENTS = createSampleAnalysisClients();
const CONSENT_VALIDITY_MS = 4 * HOUR_MS;
/** `emission_budget.PROPOSAL_VALIDITY_DAYS`: an untouched card expires 7 days after it surfaced. */
export const SAMPLE_PROPOSAL_VALIDITY_MS = 7 * DAY_MS;
/** The sample's external wait (photo, Seller Center, content): the run detail's `awaiting_expires_at`. */
export const SAMPLE_EXTERNAL_WAIT_MS = 3 * DAY_MS;
/** D24.21: a closed card's lever is not proposed again for 7 days. */
const COOLDOWN_MS = 7 * DAY_MS;

/** `ActionCard.status` as far as the seller can move it. */
type DeskStatus = "active" | "approved" | "dismissed" | "expired";

interface CardState {
  desk: DeskStatus;
  readonly surfacedAt: number;
  cooldownUntil: number | null;
}

/** How a sample run can end without success (`WorkflowRunStatus`). */
export type SampleRunFailure = "failed" | "cancelled" | "timed_out";
const FAILURE_STOP: Readonly<Record<SampleRunFailure, string>> = {
  failed: "tool_error_unrecoverable",
  cancelled: "confirmation_expired",
  timed_out: "external_wait_expired",
};
const LIVE_STATUSES = new Set(["queued", "running", "waiting_approval", "waiting_external"]);

type RunKindSample = "listing" | "photo" | "manual" | "revert" | "content";

interface SampleRun {
  readonly id: string;
  readonly kind: RunKindSample;
  readonly card: SampleCardSpec | null;
  item: QdRun;
  events: readonly AgentEvent[];
  changes: RunChanges;
  measurement: Measurement | null;
  photo: RunDetail["photo"];
  /** When the run started waiting on the seller (external wait), on the store's clock. */
  waitingSince: number | null;
  /** For a revert run: the run it restores. */
  readonly revertsRunId: string | null;
  /** P14-E content run: the card and the run's content state. */
  readonly contentSpec?: SampleContentSpec;
  content?: SampleContentState;
}

export interface SampleClientsOptions {
  /** Delay between the steps a run plays after a seller action (ms). */
  readonly stepMs?: number;
  readonly now?: () => number;
}

export interface SampleQdClients extends QdClients {
  /** Test seam: every run currently in the store. */
  readonly snapshotRuns: () => readonly QdRun[];
  /**
   * P32-E (partner trial account): "tua nhanh" every measured run to its
   * day-7 reading or day-14 verdict, in this store only. Returns how many moved.
   */
  readonly simulateMeasurement: (stage: "day7" | "final") => number;
  /** P37: the card's seller-facing status, derived like `card_view._status` (test seam). */
  readonly cardStatus: (cardId: string) => CardStatus | null;
  /**
   * P37 "tua nhanh": move the store's clock by `ms`. Consent windows that lapse
   * cancel their run (`confirmation_expired`), external waits that lapse time it
   * out (`external_wait_expired`) and cards untouched for 7 days read `expired`.
   */
  readonly advanceTime: (ms: number) => void;
  /** P37: end a live run as failed / cancelled / timed out; its card goes back to `pending`. */
  readonly failRun: (runId: string, outcome?: SampleRunFailure) => boolean;
  /**
   * P37: the cards still on the desk — what the real `GET /v1/demo/decisions`
   * lists (`status = active`, pending or past its 7 days). Phân tích reads it.
   */
  readonly fetchDeskDecisions: () => Promise<readonly DemoDecisionItem[]>;
  readonly subscribeDecisions: (listener: () => void) => () => void;
}

const EMPTY_EVENTS: readonly AgentEvent[] = [];

export function createSampleQdClients(options: SampleClientsOptions = {}): SampleQdClients {
  const stepMs = options.stepMs ?? 700;
  const now = options.now ?? (() => Date.now());
  const startedAt = now();

  let offsetMs = 0;
  /** The store's clock: the real one plus every "tua nhanh". */
  const clock = () => now() + offsetMs;
  const SEED_DESK: Readonly<Record<NonNullable<SampleCardSpec["status"]>, DeskStatus>> = {
    pending: "active",
    running: "approved",
    applied: "approved",
    simulated: "approved",
    rejected: "dismissed",
    expired: "expired",
  };
  const surfacedAt = startedAt - HOUR_MS;
  const cards = new Map<string, CardState>([
    ...SAMPLE_CARDS.map((card): [string, CardState] => [
      card.id,
      { desk: SEED_DESK[card.status ?? "pending"], surfacedAt, cooldownUntil: null },
    ]),
    ...SAMPLE_CONTENT_CARDS.map((card): [string, CardState] => [card.id, { desk: "active", surfacedAt, cooldownUntil: null }]),
  ]);
  let rules: ShopRules = sampleRules();
  const runs = new Map<string, SampleRun>();
  const listeners = new Set<() => void>();
  const cardListeners = new Set<() => void>();
  let counter = 0;

  const emit = () => {
    for (const listener of listeners) listener();
  };
  const notifyCards = () => {
    for (const listener of cardListeners) listener();
  };

  const iso = (ms: number) => new Date(ms).toISOString();
  const isLive = (run: SampleRun) => LIVE_STATUSES.has(run.item.status);
  const cardIdOf = (run: SampleRun): string | null => run.card?.id ?? run.contentSpec?.id ?? null;

  /** The latest non-revert run started from the card (`CardContext.latest_run`). */
  const latestRunFor = (cardId: string): SampleRun | null => {
    let latest: SampleRun | null = null;
    for (const run of runs.values()) if (run.kind !== "revert" && run.item.decision_id === cardId) latest = run;
    return latest;
  };

  /** `card_view._status`, over the store. */
  const sellerStatus = (cardId: string): CardStatus => {
    const state = cards.get(cardId);
    if (!state) return "pending";
    if (state.desk === "dismissed") return "rejected";
    if (state.desk === "expired") return "expired";
    if (state.desk === "approved") {
      const run = latestRunFor(cardId);
      return run && run.item.status === "completed" && run.changes.changes.length > 0 ? "applied" : "running";
    }
    return clock() - state.surfacedAt >= SAMPLE_PROPOSAL_VALIDITY_MS ? "expired" : "pending";
  };

  /** `decision_reasons.close_card`: off the desk, the lever cools down for 7 days. */
  const closeCard = (cardId: string | null) => {
    const state = cardId ? cards.get(cardId) : undefined;
    if (!state || (state.desk !== "active" && state.desk !== "approved")) return;
    state.desk = "dismissed";
    state.cooldownUntil = clock() + COOLDOWN_MS;
  };
  const runItem = (id: string, name: string, over: Partial<QdRun> & { decision_id?: string | null }): QdRun =>
    ({
      id,
      status: "running",
      stop_reason: null,
      product_name: name,
      created_at: iso(clock()),
      completed_at: null,
      running_seconds_elapsed: 0,
      latest_narration: null,
      decision_summary: null,
      awaiting: null,
      ...over,
    }) as QdRun;

  // Seed: the applied card's finished run, measured at day 7.
  {
    const completedMs = startedAt - 8 * DAY_MS;
    const events = finishedListingEvents(SAMPLE_FINISHED_RUN_ID, startedAt, 8);
    runs.set(SAMPLE_FINISHED_RUN_ID, {
      id: SAMPLE_FINISHED_RUN_ID,
      kind: "listing",
      card: SAMPLE_APPLIED_CARD,
      item: runItem(SAMPLE_FINISHED_RUN_ID, SAMPLE_APPLIED_CARD.name, {
        status: "completed",
        stop_reason: "final_response",
        created_at: events[0].timestamp,
        completed_at: events[events.length - 1].timestamp,
        decision_id: SAMPLE_APPLIED_CARD.id,
      }),
      events,
      changes: sampleChanges(SAMPLE_FINISHED_RUN_ID, SAMPLE_FINISHED_CHANGES),
      measurement: sampleDay7Measurement(completedMs),
      photo: null,
      waitingSince: null,
      revertsRunId: null,
    });
  }

  const getRun = (runId: string): SampleRun => {
    const run = runs.get(runId);
    if (!run) throw new Error("Không tìm thấy lượt chạy này trong dữ liệu mẫu.");
    return run;
  };

  const append = (run: SampleRun, drafts: readonly EventDraft[]) => {
    // An ended run takes no more events (a timer scheduled before it failed).
    if (drafts.length === 0 || !isLive(run)) return;
    // Timestamps run up to "now", never before the run's last event.
    const last = run.events.length > 0 ? Date.parse(run.events[run.events.length - 1].timestamp) : -Infinity;
    const start = Math.max(clock() - (drafts.length - 1) * 1000, last + 1000);
    const next = toEvents(run.id, drafts, run.events.length + 1, start);
    const statusBefore = run.item.status;
    run.events = [...run.events, ...next];
    for (const event of next) {
      if (event.event_type === "workflow.completed") {
        run.item = { ...run.item, status: "completed", stop_reason: event.payload.stop_reason, completed_at: event.timestamp, awaiting: null };
        run.waitingSince = null;
        onFinished(run, event.payload.stop_reason);
        notifyCards();
      } else if (event.event_type === "workflow.failed") {
        run.item = {
          ...run.item,
          status: event.payload.status,
          stop_reason: event.payload.stop_reason,
          completed_at: event.timestamp,
          awaiting: null,
        };
        run.waitingSince = null;
        onEnded(run, event.payload.stop_reason);
        notifyCards();
      } else if (event.event_type === "workflow.approval_required") {
        run.item = { ...run.item, status: "waiting_approval" };
      } else if ((event.event_type === "tool.started" || event.event_type === "workflow.started") && run.item.status !== "running") {
        // queued → running: the worker picked the run up.
        run.item = { ...run.item, status: "running", awaiting: null };
      }
    }
    emit();
    // P41: the queue's rows read the run list — re-read it when a run's status moved.
    // (An ended run already told its listeners above.)
    if (run.item.status !== statusBefore && isLive(run)) notifyCards();
  };

  /**
   * A run that ended without success. A failed / cancelled / timed-out run puts
   * its card back on the desk (D47.2; the backend's AC3 auto-revert does it for
   * `failed`); the seller's own "Không thực hiện" already closed the card.
   */
  function onEnded(run: SampleRun, stopReason: string) {
    if (run.kind === "revert" || stopReason === "cancelled_by_seller") return;
    const state = cards.get(cardIdOf(run) ?? "");
    if (state && state.desk === "approved") state.desk = "active";
    if (run.content) run.content.stage = "declined";
  }

  /** Run `fn` after one step (at once when `stepMs` is 0): the worker's pick-up delay. */
  const later = (fn: () => void) => {
    if (stepMs <= 0) fn();
    else window.setTimeout(fn, stepMs);
  };

  /** Play each batch `stepMs` apart. */
  const play = (run: SampleRun, batches: readonly (readonly EventDraft[])[]) => {
    batches.forEach((batch, index) => {
      if (stepMs <= 0) append(run, batch);
      else window.setTimeout(() => append(run, batch), stepMs * (index + 1));
    });
  };

  const setAwaiting = (run: SampleRun, awaiting: RunAwaiting | null, status: string) => {
    if (!isLive(run)) return;
    run.item = { ...run.item, awaiting, status } as QdRun;
    run.waitingSince = awaiting ? clock() : null;
    emit();
  };

  const proposedChange = (run: SampleRun): Record<string, string> => {
    for (let i = run.events.length - 1; i >= 0; i -= 1) {
      const event = run.events[i];
      if (event.event_type === "workflow.approval_required") return event.payload.proposed_change as Record<string, string>;
    }
    return {};
  };

  const labelOf = (field: string) =>
    field === "title" ? "Tiêu đề" : field === "description" ? "Mô tả" : field === "main_images" ? "Ảnh bìa" : field;

  const pendingWrite = new Map<string, Record<string, string>>();

  function onFinished(run: SampleRun, stopReason: string) {
    if (stopReason !== "final_response") return;
    const doneMs = clock();
    if (run.kind === "revert") {
      const original = run.revertsRunId ? runs.get(run.revertsRunId) : undefined;
      run.changes = sampleChanges(run.id, original?.changes.changes.map((c) => ({ ...c, before: c.after, after: c.before })) ?? [], {
        reverts_run_id: run.revertsRunId,
        revert: { available: false, reason_code: null, message: null, runs: [] },
      });
      if (original) {
        original.changes = {
          ...original.changes,
          revert: { ...original.changes.revert, available: false, runs: [{ run_id: run.id, status: "completed", stop_reason: "final_response" }] },
        };
      }
      return;
    }
    if (run.kind === "content" && run.contentSpec && run.content) {
      // No listing write is recorded for a content run: the card stays "running" (`_status`).
      run.content.stage = "measuring";
      run.content.stepAt[4] = iso(doneMs);
      run.changes = sampleChanges(run.id, [], { revert: { available: false, reason_code: "content", message: null, runs: [] } });
      run.measurement = sampleContentMeasurement(doneMs, run.contentSpec);
      return;
    }
    // The card's "applied" follows from the recorded write below (`sellerStatus`).
    if (run.kind === "listing") {
      const written = pendingWrite.get(run.id) ?? {};
      const changes: FieldChange[] = Object.entries(written).map(([field, after]) => ({
        field,
        label: labelOf(field),
        before: run.card?.beforeAfter?.find((entry) => entry.field === field)?.before ?? "",
        after,
        after_source: "read",
        recorded_at: iso(doneMs),
      }));
      run.changes = sampleChanges(run.id, changes);
    } else if (run.kind === "photo") {
      run.changes = sampleChanges(run.id, [
        { field: "main_images", label: "Ảnh bìa", before: { count: 1 }, after: { count: 1 }, after_source: "read", recorded_at: iso(doneMs) },
      ]);
    } else {
      // Seller Center / promotion: Juli verified it but wrote nothing → no recorded write.
      run.changes = sampleChanges(run.id, [], { revert: { available: false, reason_code: "seller_center", message: null, runs: [] } });
    }
    if (run.card) run.measurement = sampleWaitingMeasurement(doneMs, run.card);
  }

  const newRunId = () => {
    counter += 1;
    return `sample-run-${counter}`;
  };

  const startRunFor = (card: SampleCardSpec): SampleRun => {
    const id = newRunId();
    const executor = executorOf(card);
    const kind: RunKindSample = executor === "juli_with_photo" ? "photo" : executor === "seller_center" ? "manual" : "listing";
    const run: SampleRun = {
      id,
      kind,
      card,
      item: runItem(id, card.name, { status: "queued", decision_id: card.id } as Partial<QdRun>),
      events: EMPTY_EVENTS,
      changes: sampleChanges(id, [], { revert: { available: false, reason_code: null, message: null, runs: [] } }),
      measurement: null,
      photo: null,
      waitingSince: null,
      revertsRunId: null,
    };
    runs.set(id, run);
    later(() => {
      const expires = iso(clock() + CONSENT_VALIDITY_MS);
      if (kind === "listing") append(run, listingUntilConsent(card, expires));
      else if (kind === "photo") {
        append(run, photoUntilUpload(card));
        setAwaiting(run, "photo", "waiting_external");
      } else {
        append(run, manualUntilGuide());
        setAwaiting(run, "seller_action", "waiting_external");
      }
    });
    return run;
  };

  /** P14-E: approve a content card → reads → bản 1 → waits for the seller's choice. */
  const startContentRun = (spec: SampleContentSpec): SampleRun => {
    const id = newRunId();
    const run: SampleRun = {
      id,
      kind: "content",
      card: null,
      contentSpec: spec,
      content: { stage: "drafting", version: 1, chosenVersion: null, edited: false, stepAt: [null, null, null, null, null, null] },
      item: runItem(id, spec.name, { status: "queued", decision_id: spec.id } as Partial<QdRun>),
      events: EMPTY_EVENTS,
      changes: sampleChanges(id, [], { revert: { available: false, reason_code: "content", message: null, runs: [] } }),
      measurement: null,
      photo: null,
      waitingSince: null,
      revertsRunId: null,
    };
    runs.set(id, run);
    later(() => {
      if (!isLive(run)) return;
      append(run, contentUntilChoice(spec));
      const at = run.events.map((event) => event.timestamp);
      run.content = { ...run.content!, stage: "choice", stepAt: [at[2] ?? null, at[at.length - 3] ?? null, at[at.length - 2] ?? null, null, null, null] };
      setAwaiting(run, "content_choice", "waiting_external");
    });
    return run;
  };

  const contentRun = (runId: string): SampleRun & { contentSpec: SampleContentSpec; content: SampleContentState } => {
    const run = getRun(runId);
    if (run.kind !== "content" || !run.contentSpec || !run.content) throw new Error("Lượt chạy này không phải kịch bản nội dung.");
    return run as SampleRun & { contentSpec: SampleContentSpec; content: SampleContentState };
  };

  const resolved = <T,>(value: T): Promise<T> => Promise.resolve(value);
  const snapshotRuns = (): QdRun[] => [...runs.values()].map((run) => run.item).reverse();

  const subscribe = (listener: () => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  };

  function useSampleRunEvents(runId: string): RunEventsState {
    const getSnapshot = useCallback(() => runs.get(runId)?.events ?? EMPTY_EVENTS, [runId]);
    const events = useSyncExternalStore(subscribe, getSnapshot, () => EMPTY_EVENTS);
    return { events, streamStatus: "open" };
  }

  const simulateMeasurement = (stage: "day7" | "final"): number => {
    let moved = 0;
    for (const run of runs.values()) {
      if (run.kind === "revert" || !run.measurement || run.changes.reverts_run_id) continue;
      if (run.changes.revert.runs.length > 0) continue;
      if (run.measurement.stage === "final" || run.measurement.stage === stage) continue;
      run.measurement = sampleSimulatedMeasurement(run.measurement, stage);
      moved += 1;
    }
    if (moved > 0) emit();
    return moved;
  };

  const lastConsentExpiry = (run: SampleRun): number | null => {
    for (let i = run.events.length - 1; i >= 0; i -= 1) {
      const event = run.events[i];
      if (event.event_type === "workflow.approval_required") return Date.parse(event.payload.expires_at);
    }
    return null;
  };

  const advanceTime = (ms: number) => {
    offsetMs += Math.max(0, ms);
    const at = clock();
    for (const run of [...runs.values()]) {
      if (run.item.status === "waiting_approval") {
        const expires = lastConsentExpiry(run);
        if (expires !== null && expires <= at) append(run, [failDraft("cancelled", "confirmation_expired")]);
      } else if (run.item.status === "waiting_external" && run.waitingSince !== null && at - run.waitingSince >= SAMPLE_EXTERNAL_WAIT_MS) {
        append(run, [failDraft("timed_out", "external_wait_expired")]);
      }
    }
    notifyCards();
    emit();
  };

  const failRun = (runId: string, outcome: SampleRunFailure = "failed"): boolean => {
    const run = runs.get(runId);
    if (!run || !isLive(run)) return false;
    append(run, [failDraft(outcome, FAILURE_STOP[outcome])]);
    return true;
  };

  const decisionItems = (onDesk: boolean): DemoDecisionItem[] => {
    const keep = (id: string) => !onDesk || cards.get(id)?.desk === "active";
    const shownAt = (id: string) => (cards.get(id)?.surfacedAt ?? surfacedAt) + HOUR_MS;
    return [
      ...SAMPLE_CARDS.filter((card) => keep(card.id)).map((card) =>
        sampleDecision({ ...card, status: sellerStatus(card.id) }, shownAt(card.id)),
      ),
      ...SAMPLE_CONTENT_CARDS.filter((card) => keep(card.id)).map((card) =>
        sampleContentDecision(card, shownAt(card.id), sellerStatus(card.id)),
      ),
    ];
  };

  return {
    snapshotRuns,
    simulateMeasurement,
    cardStatus: (cardId) => (cards.has(cardId) ? sellerStatus(cardId) : null),
    advanceTime,
    failRun,
    fetchDeskDecisions: () => resolved(decisionItems(true)),
    subscribeDecisions: (listener) => {
      cardListeners.add(listener);
      return () => {
        cardListeners.delete(listener);
      };
    },
    useRunEvents: useSampleRunEvents,
    analysisClients: () => SAMPLE_ANALYSIS_CLIENTS,

    fetchDecisions: () => resolved(decisionItems(false)),
    approve: (cardId) => {
      const content = SAMPLE_CONTENT_CARDS.find((entry) => entry.id === cardId);
      const card = SAMPLE_CARDS.find((entry) => entry.id === cardId);
      if (!content && !card) return Promise.reject(new Error("Không tìm thấy thẻ này trong dữ liệu mẫu."));
      // The real approve only takes a card still on the desk (`get_surfaced_decision`).
      if (sellerStatus(cardId) !== "pending") return Promise.reject(new Error("Thẻ này không còn chờ duyệt."));
      cards.get(cardId)!.desk = "approved";
      const run = content ? startContentRun(content) : startRunFor(card!);
      notifyCards();
      emit();
      return resolved({ runId: run.id });
    },
    reject: (_auth, cardId) => {
      if (sellerStatus(cardId) !== "pending") return Promise.reject(new Error("Thẻ này không còn trên danh sách đề xuất."));
      closeCard(cardId);
      notifyCards();
      return resolved({ status: "rejected", cooldown_until: iso(cards.get(cardId)?.cooldownUntil ?? clock() + COOLDOWN_MS) });
    },
    fetchRuns: () => resolved(snapshotRuns() as WorkflowRunListItem[]),
    fetchRules: () => resolved(rules),
    putRule: (_auth, ruleKey, value, setBy, scopeRef = null) => {
      const entry = { value, set_by: setBy, set_by_user_id: "sample", set_at: iso(clock()) };
      const current = rules[ruleKey] as unknown;
      rules = {
        ...rules,
        [ruleKey]: scopeRef !== null ? { ...(current as Record<string, unknown>), [scopeRef]: entry } : entry,
      } as ShopRules;
      return resolved(undefined);
    },
    deleteRule: (_auth, ruleKey, scopeRef = null) => {
      const current = rules[ruleKey] as unknown;
      if (scopeRef !== null) {
        const next = { ...(current as Record<string, unknown>) };
        delete next[scopeRef];
        rules = { ...rules, [ruleKey]: next } as ShopRules;
      } else {
        rules = { ...rules, [ruleKey]: { value: null, set_by: null, set_by_user_id: null, set_at: null } } as ShopRules;
      }
      return resolved(undefined);
    },
    fetchChanges: (_auth, runId) => resolved(getRun(runId).changes),
    startRevert: (_auth, runId) => {
      const original = getRun(runId);
      const id = newRunId();
      const before = Object.fromEntries(original.changes.changes.map((change) => [change.field, String(change.before ?? "")]));
      const run: SampleRun = {
        id,
        kind: "revert",
        card: original.card,
        item: runItem(id, original.item.product_name ?? "", { status: "running", decision_id: original.card?.id ?? null } as Partial<QdRun>),
        events: EMPTY_EVENTS,
        changes: sampleChanges(id, [], { reverts_run_id: runId, revert: { available: false, reason_code: null, message: null, runs: [] } }),
        measurement: null,
        photo: null,
        waitingSince: null,
        revertsRunId: runId,
      };
      runs.set(id, run);
      // `demo_run_changes.start_revert`: the reason is stored and the card closed at once.
      closeCard(cardIdOf(original));
      append(run, revertUntilConsent(before, iso(clock() + CONSENT_VALIDITY_MS)));
      notifyCards();
      return resolved({ runId: id });
    },
    fetchQuestions: () => resolved([]),
    dismissQuestion: () => resolved(undefined),
    confirm: (runId, toolCallId, decision, optionId, confirmOptions = {}) => {
      const run = getRun(runId);
      if (decision === "decline") {
        // A declined consent closes the card (a revert's card is closed already).
        if (run.kind !== "revert") closeCard(cardIdOf(run));
        append(run, [endDraft("confirmation_declined")]);
        return resolved({ decision, status: "accepted", celeryTaskId: "sample" });
      }
      const edited = confirmOptions.editedValues ?? {};
      const written = { ...proposedChange(run), ...edited } as Record<string, string>;
      delete written.attach_staged_image;
      pendingWrite.set(run.id, written);
      const fields = Object.keys(written).map(labelOf).join(", ");
      const byYou = Object.keys(edited).length > 0 ? " theo bản bạn sửa" : "";
      const writtenText =
        run.kind === "photo"
          ? "Đã thay ảnh bìa · ảnh cũ đã lưu"
          : run.kind === "revert"
            ? `Đã khôi phục ${fields}`
            : `Đã ghi ${fields}${byYou} · giá trị cũ đã lưu`;
      const reviewed = run.kind === "revert" ? "Phiên bản cũ đã được duyệt" : "Phiên bản mới đã được duyệt";
      void optionId;
      play(run, writeAndReview(toolCallId, writtenText, reviewed));
      return resolved({ decision, status: "accepted", celeryTaskId: "sample" });
    },
    decline: (_auth, runId) => {
      const run = getRun(runId);
      if (run.content) run.content.stage = "declined";
      // "Không thực hiện": the reason is stored and the card closed (`close_card`).
      if (run.kind !== "revert") closeCard(cardIdOf(run));
      // A wait the seller stops is `cancelled` (workflow.failed); a declined consent completes.
      append(run, [run.item.awaiting ? failDraft("cancelled", "cancelled_by_seller") : endDraft("confirmation_declined")]);
      return resolved({ status: "declined", cooldown_until: iso(clock() + COOLDOWN_MS) });
    },
    uploadPhoto: (_auth, runId, file) => {
      const run = getRun(runId);
      let afterUrl: string | null = null;
      try {
        afterUrl = typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : null;
      } catch {
        afterUrl = null;
      }
      const checks: PhotoCheck[] = [...SAMPLE_PHOTO_CHECKS];
      run.photo = { before_url: null, after_url: afterUrl, checks };
      setAwaiting(run, null, "running");
      play(run, [photoToConsent(iso(clock() + 3 * DAY_MS))]);
      return resolved(checks);
    },
    fetchInstructions: () => resolved(SAMPLE_INSTRUCTIONS),
    markApplied: (_auth, runId) => {
      const run = getRun(runId);
      setAwaiting(run, null, "running");
      play(run, manualVerify());
      return resolved(undefined);
    },
    fetchMeasurement: (_auth, runId) => resolved(getRun(runId).measurement),
    useContent: (_auth, runId, version, editedBlocks) => {
      const run = contentRun(runId);
      run.content.chosenVersion = version;
      run.content.edited = Boolean(editedBlocks && Object.keys(editedBlocks).length > 0);
      run.content.stage = "publish";
      run.content.stepAt[3] = iso(clock());
      append(run, contentPublishWait(run.contentSpec));
      setAwaiting(run, "content_publish", "waiting_external");
      return resolved(undefined);
    },
    redraftContent: (_auth, runId) => {
      const run = contentRun(runId);
      if (run.content.version >= 2) return Promise.reject(new Error("Juli đã soạn lại một lần."));
      run.content.version = 2;
      append(run, contentRedraft());
      run.content.stepAt[2] = iso(clock());
      setAwaiting(run, "content_choice", "waiting_external");
      return resolved(undefined);
    },
    markPublished: (_auth, runId) => {
      const run = contentRun(runId);
      setAwaiting(run, null, "running");
      play(run, contentPublished(run.contentSpec));
      return resolved(undefined);
    },
    fetchRunDetail: (_auth, runId) => {
      const run = getRun(runId);
      if (run.kind === "content" && run.contentSpec && run.content) {
        return resolved({
          id: run.id,
          status: run.item.status,
          awaiting: run.item.awaiting ?? null,
          awaiting_expires_at: run.item.awaiting ? iso((run.waitingSince ?? clock()) + SAMPLE_EXTERNAL_WAIT_MS) : null,
          decision_id: run.contentSpec.id,
          lever: { code: run.contentSpec.kind === "video" ? "video_script" : "live_script", kind: "content" },
          photo: null,
          promotion: null,
          content: sampleContentDetail(run.contentSpec, run.content),
        });
      }
      return resolved({
        id: run.id,
        status: run.item.status,
        awaiting: run.item.awaiting ?? null,
        awaiting_expires_at: run.item.awaiting ? iso((run.waitingSince ?? clock()) + SAMPLE_EXTERNAL_WAIT_MS) : null,
        decision_id: run.card?.id ?? null,
        lever: run.card ? { code: run.card.lever, kind: run.kind } : null,
        photo: run.photo,
        promotion: null,
      });
    },
  };
}

