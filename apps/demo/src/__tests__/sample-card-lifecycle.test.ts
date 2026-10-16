import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SAMPLE_EXTERNAL_WAIT_MS,
  SAMPLE_PROPOSAL_VALIDITY_MS,
  createSampleQdClients,
  type SampleQdClients,
  type SampleRunFailure,
} from "../lib/quyet-dinh/sample-clients";
import {
  SAMPLE_APPLIED_CARD,
  SAMPLE_CONTENT_VIDEO,
  SAMPLE_DESCRIPTION_CARD,
  SAMPLE_FINISHED_RUN_ID,
  SAMPLE_MAIN_CARD,
  SAMPLE_MANUAL_CARD,
  SAMPLE_PHOTO_CARD,
} from "../lib/quyet-dinh/sample-data";

/**
 * P37 (D47.2, owner 2026-10-16): the sample store walks the real card
 * lifecycle — `ActionCard.status` + `card_view._status` + the run states of
 * `services/agent/status.py`. One test per transition of D47.2.
 */

const DAY_MS = 86_400_000;
const HOUR_MS = 3_600_000;
const T0 = Date.parse("2026-10-16T03:00:00Z");
const A = { token: "sample", shopId: "sample-shop" };
const REASON = { reason_code: "other" };

function store(stepMs = 0): SampleQdClients {
  return createSampleQdClients({ stepMs, now: () => T0 });
}

const runOf = (clients: SampleQdClients, runId: string) => clients.snapshotRuns().find((run) => run.id === runId)!;

async function approve(clients: SampleQdClients, cardId: string): Promise<string> {
  return (await clients.approve(cardId, A)).runId;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("sample card lifecycle (D47.2)", () => {
  it("seeds pending cards and the applied card whose finished run recorded a write", () => {
    const clients = store();
    expect(clients.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("pending");
    expect(clients.cardStatus(SAMPLE_CONTENT_VIDEO.id)).toBe("pending");
    expect(clients.cardStatus(SAMPLE_APPLIED_CARD.id)).toBe("applied");
    expect(clients.cardStatus("no-such-card")).toBeNull();
  });

  it("Duyệt → running; the run is queued, then running once the worker picks it up", async () => {
    vi.useFakeTimers();
    const clients = store(10);
    const runId = await approve(clients, SAMPLE_MAIN_CARD.id);
    expect(clients.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("running");
    expect(runOf(clients, runId).status).toBe("queued");
    vi.advanceTimersByTime(10);
    expect(runOf(clients, runId).status).toBe("waiting_approval");
    expect(clients.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("running");
  });

  it("consent → completed → applied, measurement waiting → day 7 → final", async () => {
    const clients = store();
    const runId = await approve(clients, SAMPLE_MAIN_CARD.id);
    expect(runOf(clients, runId).status).toBe("waiting_approval");
    await clients.confirm(runId, "w1", "approve", "opt-1", A);
    expect(runOf(clients, runId)).toMatchObject({ status: "completed", stop_reason: "final_response" });
    expect(clients.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("applied");
    expect((await clients.fetchChanges(A, runId)).changes.length).toBeGreaterThan(0);
    expect((await clients.fetchMeasurement(A, runId))?.stage).toBe("waiting");
    clients.simulateMeasurement("day7");
    expect((await clients.fetchMeasurement(A, runId))?.stage).toBe("day7");
    clients.simulateMeasurement("final");
    const final = await clients.fetchMeasurement(A, runId);
    expect(final?.stage).toBe("final");
    expect(final?.final).not.toBeNull();
  });

  it("cover photo: waiting_external (photo) → upload → consent → applied", async () => {
    const clients = store();
    const runId = await approve(clients, SAMPLE_PHOTO_CARD.id);
    expect(runOf(clients, runId)).toMatchObject({ status: "waiting_external", awaiting: "photo" });
    await clients.uploadPhoto(A, runId, new File(["x"], "cover.png", { type: "image/png" }));
    expect(runOf(clients, runId).status).toBe("waiting_approval");
    await clients.confirm(runId, "p3", "approve", "opt-1", A);
    expect(runOf(clients, runId).status).toBe("completed");
    expect(clients.cardStatus(SAMPLE_PHOTO_CARD.id)).toBe("applied");
  });

  it("Seller Center: the run completes with no recorded write, so the card stays running (real _status)", async () => {
    const clients = store();
    const runId = await approve(clients, SAMPLE_MANUAL_CARD.id);
    expect(runOf(clients, runId)).toMatchObject({ status: "waiting_external", awaiting: "seller_action" });
    await clients.markApplied(A, runId);
    expect(runOf(clients, runId)).toMatchObject({ status: "completed", stop_reason: "final_response" });
    expect((await clients.fetchChanges(A, runId)).changes).toEqual([]);
    expect(clients.cardStatus(SAMPLE_MANUAL_CARD.id)).toBe("running");
    expect((await clients.fetchMeasurement(A, runId))?.stage).toBe("waiting");
  });

  it("content card: drafts → published → completed, no listing write → stays running", async () => {
    const clients = store();
    const runId = await approve(clients, SAMPLE_CONTENT_VIDEO.id);
    expect(runOf(clients, runId)).toMatchObject({ status: "waiting_external", awaiting: "content_choice" });
    await clients.useContent(A, runId, 1);
    await clients.markPublished(A, runId);
    expect(runOf(clients, runId).status).toBe("completed");
    expect(clients.cardStatus(SAMPLE_CONTENT_VIDEO.id)).toBe("running");
  });

  it("declined consent (Không thực hiện at the consent) → rejected + 7-day cooldown", async () => {
    const clients = store();
    const runId = await approve(clients, SAMPLE_MAIN_CARD.id);
    const result = await clients.decline(A, runId, REASON);
    expect(result.cooldown_until).toBe(new Date(T0 + 7 * DAY_MS).toISOString());
    expect(runOf(clients, runId)).toMatchObject({ status: "completed", stop_reason: "confirmation_declined" });
    expect(clients.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("rejected");
  });

  it("a consent declined through the confirmation → rejected", async () => {
    const clients = store();
    const runId = await approve(clients, SAMPLE_DESCRIPTION_CARD.id);
    await clients.confirm(runId, "w1", "decline", null, A);
    expect(runOf(clients, runId).stop_reason).toBe("confirmation_declined");
    expect(clients.cardStatus(SAMPLE_DESCRIPTION_CARD.id)).toBe("rejected");
  });

  it("Không thực hiện on a wait → run cancelled (cancelled_by_seller), card rejected, not back to pending", async () => {
    const clients = store();
    const runId = await approve(clients, SAMPLE_MANUAL_CARD.id);
    await clients.decline(A, runId, REASON);
    expect(runOf(clients, runId)).toMatchObject({ status: "cancelled", stop_reason: "cancelled_by_seller" });
    expect(clients.cardStatus(SAMPLE_MANUAL_CARD.id)).toBe("rejected");
  });

  it("Từ chối → rejected + 7-day cooldown; a closed card cannot be rejected or approved again", async () => {
    const clients = store();
    const result = await clients.reject(A, SAMPLE_PHOTO_CARD.id, REASON);
    expect(result).toEqual({ status: "rejected", cooldown_until: new Date(T0 + 7 * DAY_MS).toISOString() });
    expect(clients.cardStatus(SAMPLE_PHOTO_CARD.id)).toBe("rejected");
    await expect(clients.reject(A, SAMPLE_PHOTO_CARD.id, REASON)).rejects.toThrow();
    await expect(clients.approve(SAMPLE_PHOTO_CARD.id, A)).rejects.toThrow("Thẻ này không còn chờ duyệt.");
  });

  it("Hoàn tác → rejected as soon as the revert starts, and stays rejected when it completes", async () => {
    const clients = store();
    const { runId } = await clients.startRevert(A, SAMPLE_FINISHED_RUN_ID, REASON);
    expect(clients.cardStatus(SAMPLE_APPLIED_CARD.id)).toBe("rejected");
    await clients.confirm(runId, "rw", "approve", "opt-1", A);
    expect(runOf(clients, runId).status).toBe("completed");
    expect(clients.cardStatus(SAMPLE_APPLIED_CARD.id)).toBe("rejected");
    expect((await clients.fetchChanges(A, SAMPLE_FINISHED_RUN_ID)).revert.runs).toHaveLength(1);
  });

  it.each<[SampleRunFailure, string]>([
    ["failed", "tool_error_unrecoverable"],
    ["cancelled", "confirmation_expired"],
    ["timed_out", "external_wait_expired"],
  ])("a %s run puts the card back to pending, and it can be approved again", async (outcome, stop) => {
    const clients = store();
    const runId = await approve(clients, SAMPLE_MAIN_CARD.id);
    expect(clients.failRun(runId, outcome)).toBe(true);
    expect(runOf(clients, runId)).toMatchObject({ status: outcome, stop_reason: stop });
    expect(clients.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("pending");
    expect(clients.failRun(runId, outcome)).toBe(false);
    const again = await approve(clients, SAMPLE_MAIN_CARD.id);
    expect(again).not.toBe(runId);
    expect(clients.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("running");
  });

  it("a failed content run puts the content card back to pending", async () => {
    const clients = store();
    const runId = await approve(clients, SAMPLE_CONTENT_VIDEO.id);
    clients.failRun(runId);
    expect(clients.cardStatus(SAMPLE_CONTENT_VIDEO.id)).toBe("pending");
  });

  it("a run that failed takes no later events (timers scheduled before it ended)", async () => {
    vi.useFakeTimers();
    const clients = store(10);
    const runId = await approve(clients, SAMPLE_PHOTO_CARD.id);
    clients.failRun(runId);
    vi.advanceTimersByTime(100);
    expect(runOf(clients, runId).status).toBe("failed");
    expect(runOf(clients, runId).awaiting ?? null).toBeNull();
    expect(clients.cardStatus(SAMPLE_PHOTO_CARD.id)).toBe("pending");
  });

  it("tua nhanh past the 4-hour consent window → cancelled (confirmation_expired) → pending", async () => {
    const clients = store();
    const runId = await approve(clients, SAMPLE_MAIN_CARD.id);
    clients.advanceTime(3 * HOUR_MS);
    expect(runOf(clients, runId).status).toBe("waiting_approval");
    clients.advanceTime(HOUR_MS);
    expect(runOf(clients, runId)).toMatchObject({ status: "cancelled", stop_reason: "confirmation_expired" });
    expect(clients.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("pending");
  });

  it("tua nhanh past the external wait → timed_out (external_wait_expired) → pending", async () => {
    const clients = store();
    const runId = await approve(clients, SAMPLE_PHOTO_CARD.id);
    const detail = await clients.fetchRunDetail(A, runId);
    expect(detail.awaiting_expires_at).toBe(new Date(T0 + SAMPLE_EXTERNAL_WAIT_MS).toISOString());
    clients.advanceTime(SAMPLE_EXTERNAL_WAIT_MS);
    expect(runOf(clients, runId)).toMatchObject({ status: "timed_out", stop_reason: "external_wait_expired" });
    expect(clients.cardStatus(SAMPLE_PHOTO_CARD.id)).toBe("pending");
  });

  it("7 days untouched → expired; an expired card cannot be approved; decided cards keep their status", async () => {
    const clients = store();
    await clients.reject(A, SAMPLE_PHOTO_CARD.id, REASON);
    clients.advanceTime(SAMPLE_PROPOSAL_VALIDITY_MS - 2 * HOUR_MS);
    expect(clients.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("pending");
    clients.advanceTime(HOUR_MS);
    expect(clients.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("expired");
    expect(clients.cardStatus(SAMPLE_CONTENT_VIDEO.id)).toBe("expired");
    expect(clients.cardStatus(SAMPLE_PHOTO_CARD.id)).toBe("rejected");
    expect(clients.cardStatus(SAMPLE_APPLIED_CARD.id)).toBe("applied");
    await expect(clients.approve(SAMPLE_MAIN_CARD.id, A)).rejects.toThrow("Thẻ này không còn chờ duyệt.");
    const items = await clients.fetchDecisions(A);
    const main = items.find((item) => item.id === SAMPLE_MAIN_CARD.id)!;
    expect((main.recommendation as unknown as { card: { status: string } }).card.status).toBe("expired");
  });

  it("the desk list (Phân tích) holds only active cards — pending or past 7 days — like GET /v1/demo/decisions", async () => {
    const clients = store();
    await approve(clients, SAMPLE_MAIN_CARD.id);
    await clients.reject(A, SAMPLE_PHOTO_CARD.id, REASON);
    const ids = (await clients.fetchDeskDecisions()).map((item) => item.id);
    expect(ids).not.toContain(SAMPLE_MAIN_CARD.id);
    expect(ids).not.toContain(SAMPLE_PHOTO_CARD.id);
    expect(ids).not.toContain(SAMPLE_APPLIED_CARD.id);
    expect(ids).toContain(SAMPLE_MANUAL_CARD.id);
    clients.advanceTime(SAMPLE_PROPOSAL_VALIDITY_MS);
    expect((await clients.fetchDeskDecisions()).map((item) => item.id)).toContain(SAMPLE_MANUAL_CARD.id);
  });

  it("tells subscribers whenever a card's status may have moved", async () => {
    const clients = store();
    const listener = vi.fn();
    const stop = clients.subscribeDecisions(listener);
    const runId = await approve(clients, SAMPLE_MAIN_CARD.id);
    expect(listener).toHaveBeenCalled();
    listener.mockClear();
    clients.failRun(runId);
    expect(listener).toHaveBeenCalled();
    stop();
    listener.mockClear();
    await clients.reject(A, SAMPLE_MANUAL_CARD.id, REASON);
    expect(listener).not.toHaveBeenCalled();
  });
});
