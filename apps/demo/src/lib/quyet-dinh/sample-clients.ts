/**
 * The signed-out Quyết định's data source: `QdClients` over an in-memory
 * store seeded from `sample-data.ts` (ADR-094 d.1 — no fetch call site, no
 * backend route literal anywhere in this module's graph). Approving,
 * rejecting, confirming, uploading a photo, "Tôi đã áp dụng" and Hoàn tác
 * change this store only; the run then plays its next contract events on
 * a short timer so the P10 timeline moves the way a real run does. Nothing
 * survives a reload, nothing reaches TikTok Shop.
 */

import { useCallback, useSyncExternalStore } from "react";

import type { AgentEvent, WorkflowRunListItem } from "@juli/contracts";

import type { QdClients, RunEventsState } from "./client-types";
import type { Measurement, PhotoCheck, QdRun, RunAwaiting, RunDetail } from "./p10-types";
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
const CONSENT_VALIDITY_MS = 4 * 3_600_000;

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
}

const EMPTY_EVENTS: readonly AgentEvent[] = [];

export function createSampleQdClients(options: SampleClientsOptions = {}): SampleQdClients {
  const stepMs = options.stepMs ?? 700;
  const now = options.now ?? (() => Date.now());
  const startedAt = now();

  const cardStatus = new Map<string, string>([
    ...SAMPLE_CARDS.map((card): [string, string] => [card.id, card.status ?? "pending"]),
    ...SAMPLE_CONTENT_CARDS.map((card): [string, string] => [card.id, "pending"]),
  ]);
  let rules: ShopRules = sampleRules();
  const runs = new Map<string, SampleRun>();
  const listeners = new Set<() => void>();
  let counter = 0;

  const emit = () => {
    for (const listener of listeners) listener();
  };

  const iso = (ms: number) => new Date(ms).toISOString();
  const runItem = (id: string, name: string, over: Partial<QdRun> & { decision_id?: string | null }): QdRun =>
    ({
      id,
      status: "running",
      stop_reason: null,
      product_name: name,
      created_at: iso(now()),
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
      revertsRunId: null,
    });
  }

  const getRun = (runId: string): SampleRun => {
    const run = runs.get(runId);
    if (!run) throw new Error("Không tìm thấy lượt chạy này trong bản minh họa.");
    return run;
  };

  const append = (run: SampleRun, drafts: readonly EventDraft[]) => {
    if (drafts.length === 0) return;
    // Timestamps run up to "now", never before the run's last event.
    const last = run.events.length > 0 ? Date.parse(run.events[run.events.length - 1].timestamp) : -Infinity;
    const start = Math.max(now() - (drafts.length - 1) * 1000, last + 1000);
    const next = toEvents(run.id, drafts, run.events.length + 1, start);
    run.events = [...run.events, ...next];
    for (const event of next) {
      if (event.event_type === "workflow.completed") {
        run.item = { ...run.item, status: "completed", stop_reason: event.payload.stop_reason, completed_at: event.timestamp, awaiting: null };
        onFinished(run, event.payload.stop_reason);
      } else if (event.event_type === "workflow.approval_required") {
        run.item = { ...run.item, status: "waiting_approval" };
      } else if (event.event_type === "tool.started" && run.item.status !== "running") {
        run.item = { ...run.item, status: "running", awaiting: null };
      }
    }
    emit();
  };

  /** Play each batch `stepMs` apart. */
  const play = (run: SampleRun, batches: readonly (readonly EventDraft[])[]) => {
    batches.forEach((batch, index) => {
      if (stepMs <= 0) append(run, batch);
      else window.setTimeout(() => append(run, batch), stepMs * (index + 1));
    });
  };

  const setAwaiting = (run: SampleRun, awaiting: RunAwaiting | null, status: string) => {
    run.item = { ...run.item, awaiting, status } as QdRun;
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
    const doneMs = now();
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
      cardStatus.set(run.contentSpec.id, "applied");
      run.content.stage = "measuring";
      run.content.stepAt[4] = iso(doneMs);
      run.changes = sampleChanges(run.id, [], { revert: { available: false, reason_code: "content", message: null, runs: [] } });
      run.measurement = sampleContentMeasurement(doneMs, run.contentSpec);
      return;
    }
    if (run.card) cardStatus.set(run.card.id, "applied");
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
      item: runItem(id, card.name, { status: "running", decision_id: card.id } as Partial<QdRun>),
      events: EMPTY_EVENTS,
      changes: sampleChanges(id, [], { revert: { available: false, reason_code: null, message: null, runs: [] } }),
      measurement: null,
      photo: null,
      revertsRunId: null,
    };
    runs.set(id, run);
    const expires = iso(now() + CONSENT_VALIDITY_MS);
    if (kind === "listing") append(run, listingUntilConsent(card, expires));
    else if (kind === "photo") {
      append(run, photoUntilUpload(card));
      setAwaiting(run, "photo", "waiting_external");
    } else {
      append(run, manualUntilGuide());
      setAwaiting(run, "seller_action", "waiting_external");
    }
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
      item: runItem(id, spec.name, { status: "running", decision_id: spec.id } as Partial<QdRun>),
      events: EMPTY_EVENTS,
      changes: sampleChanges(id, [], { revert: { available: false, reason_code: "content", message: null, runs: [] } }),
      measurement: null,
      photo: null,
      revertsRunId: null,
    };
    runs.set(id, run);
    append(run, contentUntilChoice(spec));
    const at = run.events.map((event) => event.timestamp);
    run.content = { ...run.content!, stage: "choice", stepAt: [at[2] ?? null, at[at.length - 3] ?? null, at[at.length - 2] ?? null, null, null, null] };
    setAwaiting(run, "content_choice", "waiting_external");
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

  return {
    snapshotRuns,
    useRunEvents: useSampleRunEvents,

    fetchDecisions: () =>
      resolved([
        ...SAMPLE_CARDS.map((card) => sampleDecision({ ...card, status: cardStatus.get(card.id) as SampleCardSpec["status"] }, startedAt)),
        ...SAMPLE_CONTENT_CARDS.map((card) => sampleContentDecision(card, startedAt, cardStatus.get(card.id) ?? "pending")),
      ]),
    approve: (cardId) => {
      const content = SAMPLE_CONTENT_CARDS.find((entry) => entry.id === cardId);
      if (content) {
        cardStatus.set(cardId, "running");
        return resolved({ runId: startContentRun(content).id });
      }
      const card = SAMPLE_CARDS.find((entry) => entry.id === cardId);
      if (!card) return Promise.reject(new Error("Không tìm thấy thẻ này trong bản minh họa."));
      cardStatus.set(cardId, "running");
      return resolved({ runId: startRunFor(card).id });
    },
    reject: (_auth, cardId) => {
      cardStatus.set(cardId, "rejected");
      return resolved({ status: "rejected", cooldown_until: iso(now() + 7 * DAY_MS) });
    },
    fetchRuns: () => resolved(snapshotRuns() as WorkflowRunListItem[]),
    fetchRules: () => resolved(rules),
    putRule: (_auth, ruleKey, value, setBy, scopeRef = null) => {
      const entry = { value, set_by: setBy, set_by_user_id: "sample", set_at: iso(now()) };
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
        revertsRunId: runId,
      };
      runs.set(id, run);
      append(run, revertUntilConsent(before, iso(now() + CONSENT_VALIDITY_MS)));
      return resolved({ runId: id });
    },
    fetchQuestions: () => resolved([]),
    dismissQuestion: () => resolved(undefined),
    confirm: (runId, toolCallId, decision, optionId, confirmOptions = {}) => {
      const run = getRun(runId);
      if (decision === "decline") {
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
      const stop = run.item.awaiting ? "cancelled_by_seller" : "confirmation_declined";
      if (run.content) run.content.stage = "declined";
      append(run, [endDraft(stop)]);
      return resolved({ status: "declined", cooldown_until: iso(now() + 7 * DAY_MS) });
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
      play(run, [photoToConsent(iso(now() + 3 * DAY_MS))]);
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
      run.content.stepAt[3] = iso(now());
      append(run, contentPublishWait(run.contentSpec));
      setAwaiting(run, "content_publish", "waiting_external");
      return resolved(undefined);
    },
    redraftContent: (_auth, runId) => {
      const run = contentRun(runId);
      if (run.content.version >= 2) return Promise.reject(new Error("Juli đã soạn lại một lần."));
      run.content.version = 2;
      append(run, contentRedraft());
      run.content.stepAt[2] = iso(now());
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
          awaiting_expires_at: run.item.awaiting ? iso(now() + 3 * DAY_MS) : null,
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
        awaiting_expires_at: run.item.awaiting ? iso(now() + 3 * DAY_MS) : null,
        decision_id: run.card?.id ?? null,
        lever: run.card ? { code: run.card.lever, kind: run.kind } : null,
        photo: run.photo,
        promotion: null,
      });
    },
  };
}

