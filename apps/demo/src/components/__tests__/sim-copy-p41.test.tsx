import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { runChip, runPhase } from "../../lib/quyet-dinh/run-model";
import {
  NO_TIKTOK_FLAG_SUMMARY,
  SAMPLE_CARDS,
  SAMPLE_CONTENT_CARDS,
  SAMPLE_DESCRIPTION_CARD,
  SAMPLE_MAIN_CARD,
  listingUntilConsent,
  toEvents,
} from "../../lib/quyet-dinh/sample-data";
import type { QdRun } from "../../lib/quyet-dinh/p10-types";
import { buildRunTimeline } from "../../lib/quyet-dinh/timeline";
import {
  REVIEWER_SAMPLE_NOTICE,
  REVIEWER_SIMULATED_LABEL,
  REVIEWER_SIMULATION_NOTES,
} from "../../lib/reviewer/copy";
import { simulateSampleDecision } from "../../lib/reviewer/sample-simulation";
import { resetReviewerSample } from "../../lib/reviewer/sample-store";
import { storeReviewerRecord } from "../../lib/reviewer/session";
import { storeAuthSession } from "../../lib/supabase-auth";
import { DecisionsPageClient } from "../decisions-page-client";
import { DemoShell } from "../demo-shell";

/**
 * P41 (D47.7, owner 2026-10-16): the simulation copy a partner reviewer or a
 * seller sees is short and shows no backend internals — no endpoint, method or
 * operation name, no model name, no "mã" for TikTok's flags — and the sample's
 * canned run text matches its product.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

/** Text no seller- or reviewer-facing screen may show. */
const INTERNALS = [/\/product\//, /\bPUT\b/, /\bPOST\b/, /\/v1\//, /update_product/, /upload_product/, /gpt-/, /JSON schema/, /Có mã/, /mã chẩn đoán/];

function expectNoInternals(text: string) {
  for (const pattern of INTERNALS) expect(text).not.toMatch(pattern);
}

const EXPIRES = "2026-11-13T00:00:00Z";
const SESSION = { accessToken: "at", refreshToken: null, expiresIn: 3600, tokenType: "bearer" };

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("P41 — the simulated Thực thi", () => {
  it("every sample card: one short note per executor, no endpoint in the note or the fields", async () => {
    for (const spec of [...SAMPLE_CARDS, ...SAMPLE_CONTENT_CARDS]) {
      const result = await simulateSampleDecision(spec.id, "execute");
      const note = result.change.note ?? "";
      expect(Object.values(REVIEWER_SIMULATION_NOTES)).toContain(note);
      expect(note.length).toBeLessThanOrEqual(120);
      expectNoInternals([note, ...result.change.fields.flatMap((f) => [f.label, f.before ?? "", f.after ?? ""])].join(" "));
    }
  });

  it("a promotion card's Sau cell says the seller applies it, not that Juli drafts content", async () => {
    const promo = SAMPLE_CARDS.find((card) => card.lever === "product_discount")!;
    const result = await simulateSampleDecision(promo.id, "execute");
    expect(result.change.fields[0]?.after).toBe("Bạn áp dụng trên Seller Center");
    expect(result.change.note).toBe(REVIEWER_SIMULATION_NOTES.seller_center);
  });
});

describe("P41 — sample runs match their product", () => {
  it("the diagnoses step names the flag in plain words; the keyword step names the product's words", () => {
    const main = toEvents("r1", listingUntilConsent(SAMPLE_MAIN_CARD, EXPIRES), 1, Date.now());
    const mask = toEvents("r2", listingUntilConsent(SAMPLE_DESCRIPTION_CARD, EXPIRES), 1, Date.now());
    const summaries = (events: typeof main) =>
      events.flatMap((event) => (event.event_type === "tool.completed" ? [`${event.payload.tool_name}=${event.payload.summary}`] : []));
    expect(summaries(mask)).toContain("get_product_diagnoses=Mô tả quá ngắn");
    const maskKeywords = summaries(mask).find((line) => line.startsWith("get_seo_keywords="))!;
    expect(maskKeywords).toMatch(/mặt nạ đất sét/);
    expect(maskKeywords).not.toMatch(/son lì|ruby/);
    expect(summaries(main).find((line) => line.startsWith("get_seo_keywords="))).toMatch(/son lì/);
    for (const line of [...summaries(main), ...summaries(mask)]) expect(line).not.toMatch(/Có mã|mã chẩn đoán/);
    expect(NO_TIKTOK_FLAG_SUMMARY).not.toMatch(/mã/);
  });
});

describe("P41 — the run chip follows the run's events, not a stale list row", () => {
  it("a list row still `queued` whose events reached the consent shows Đang chờ bạn", () => {
    const events = toEvents("r1", listingUntilConsent(SAMPLE_DESCRIPTION_CARD, EXPIRES), 1, Date.now());
    const timeline = buildRunTimeline(events, { kind: "listing" });
    const stale = { id: "r1", status: "queued", stop_reason: null, awaiting: null } as unknown as QdRun;
    const phase = runPhase(stale, "listing", timeline);
    expect(phase).toBe("consent");
    expect(runChip(stale, "listing", phase).label).toBe("Đang chờ bạn");
    // No event yet: still in the queue.
    expect(runPhase(stale, "listing", buildRunTimeline([], { kind: "listing" }))).toBe("queued");
  });

  it("in the reviewer's sample shop, with the real pick-up delay, the queue row matches the open run", async () => {
    resetReviewerSample({ stepMs: 30 });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => {
        const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (url === "/v1/reviewer/me") {
          return new Response(JSON.stringify({ reviewer: true, platform: "shopee", expires_at: EXPIRES, shop: null }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(`no request expected: ${url}`);
      }),
    );
    storeAuthSession(SESSION);
    storeReviewerRecord({ platform: "shopee", expiresAt: EXPIRES, sample: true });
    render(
      <DemoShell>
        <DecisionsPageClient />
      </DemoShell>,
    );

    // The page label: one short line.
    await waitFor(() => expect(screen.getAllByTestId("recommendation-card").length).toBeGreaterThanOrEqual(4));
    expect(screen.getAllByTestId("simulated-label")[0].textContent).toBe(`${REVIEWER_SIMULATED_LABEL} · ${REVIEWER_SAMPLE_NOTICE}`);

    const card = screen
      .getAllByTestId("recommendation-card")
      .find((element) => element.textContent?.includes(SAMPLE_DESCRIPTION_CARD.name) && !within(element).queryByTestId("drafts-chip"))!;
    await userEvent.click(within(card).getByRole("button", { name: "Duyệt" }));
    const dialog = await screen.findByTestId("reviewer-simulation");
    await userEvent.click(await within(dialog).findByRole("button", { name: "Thực thi (mô phỏng)" }));
    const change = await within(dialog).findByTestId("reviewer-simulation-change");
    expect(within(change).getByRole("table")).toHaveTextContent("Trước");
    expectNoInternals(dialog.textContent ?? "");
    expect(dialog.textContent?.match(/không gửi tới TikTok|Không có thay đổi nào được gửi/gi)?.length).toBe(1);
    await userEvent.click(within(dialog).getByRole("button", { name: "Theo dõi lượt chạy (mô phỏng) ›" }));

    await screen.findByTestId("consent-block");
    const queue = screen.getByTestId("run-queue");
    const row = within(queue)
      .getAllByRole("button")
      .find((button) => button.textContent?.includes(SAMPLE_DESCRIPTION_CARD.name))!;
    await waitFor(() => expect(row).toHaveTextContent("Đang chờ bạn"));
    expect(row).not.toHaveTextContent("Trong hàng đợi");

    const timeline = screen.getByTestId("run-timeline");
    expect(timeline).toHaveTextContent("Mô tả quá ngắn");
    expect(timeline).toHaveTextContent("mặt nạ đất sét");
    expect(timeline).not.toHaveTextContent("son lì");
    expectNoInternals(document.body.textContent ?? "");
  }, 30_000);
});
