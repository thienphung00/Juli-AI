import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchReviewerMe } from "../../lib/reviewer/api-client";
import {
  REVIEWER_BANNER_COPY,
  REVIEWER_SAMPLE_SHOP_BANNER_COPY,
  REVIEWER_SAMPLE_SHOP_LABEL,
  reviewerShopLabel,
} from "../../lib/reviewer/copy";
import { isSampleShopReviewer, isSandboxReviewer } from "../../lib/reviewer/mode";
import { parseReviewerShops, readReviewerRecord, storeReviewerRecord, type ReviewerRecord } from "../../lib/reviewer/session";
import { ReviewerBanner } from "../app-shell/reviewer-banner";

/**
 * P100 S2-B: the reviewer's third pin mode, "sample" — the synthetic Shopee
 * sample shop "Dữ liệu mẫu". Names shown (synthetic), read-only, Duyệt /
 * Thực thi simulated as on a masked shop. Nothing visible says "demo".
 */

const EXPIRES = "2026-11-25T00:00:00Z";
const SAMPLE_SHOP: ReviewerRecord = { platform: "shopee", expiresAt: EXPIRES, mode: "sample" };

beforeEach(() => window.localStorage.clear());
afterEach(() => cleanup());

describe("P100 S2-B reviewer sample shop", () => {
  it("fetchReviewerMe accepts the sample mode and its shop option", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(
        JSON.stringify({
          reviewer: true,
          platform: "shopee",
          expires_at: EXPIRES,
          shop: { id: "s-1", name: "Dữ liệu mẫu" },
          mode: "sample",
          writes_enabled: false,
          shops: [
            { id: "s-1", name: "Dữ liệu mẫu", mode: "sample", writes_enabled: false },
            { id: "sbx-1", name: "SANDBOX_VN", mode: "sandbox", writes_enabled: true },
            { id: "x-1", name: "?", mode: "live" },
          ],
        }),
        { status: 200 },
      ),
    );
    const result = await fetchReviewerMe("at", fetchImpl, "s-1");
    expect(result.status).toBe("reviewer");
    if (result.status !== "reviewer") return;
    expect(result.me.mode).toBe("sample");
    expect(result.me.writesEnabled).toBeUndefined();
    expect(result.me.shops?.map((shop) => shop.mode)).toEqual(["sample", "sandbox"]);
  });

  it("an unknown mode is dropped, never widened", () => {
    expect(parseReviewerShops([{ id: "a", name: "A", mode: "live" }])).toEqual([]);
    storeReviewerRecord({ platform: "shopee", expiresAt: null, mode: "live" as unknown as "masked" });
    expect(readReviewerRecord()?.mode).toBeUndefined();
  });

  it("the stored record keeps the sample mode", () => {
    storeReviewerRecord(SAMPLE_SHOP);
    expect(readReviewerRecord()?.mode).toBe("sample");
  });

  it("the mode helper tells the sample shop from the sandbox and the no-pin sample", () => {
    expect(isSampleShopReviewer(SAMPLE_SHOP)).toBe(true);
    expect(isSandboxReviewer(SAMPLE_SHOP)).toBe(false);
    expect(isSampleShopReviewer({ ...SAMPLE_SHOP, sample: true })).toBe(false);
    expect(isSampleShopReviewer({ platform: "shopee", expiresAt: null, mode: "masked" })).toBe(false);
    expect(isSampleShopReviewer(null)).toBe(false);
  });

  it("the banner reads Dữ liệu mẫu, offers no reset and never says demo", () => {
    render(<ReviewerBanner onReset={vi.fn()} reviewer={SAMPLE_SHOP} />);
    const banner = screen.getByTestId("reviewer-banner");
    expect(banner.textContent).toContain(REVIEWER_SAMPLE_SHOP_BANNER_COPY);
    expect(banner.textContent).toContain("Dữ liệu mẫu");
    expect(banner.textContent).not.toContain(REVIEWER_BANNER_COPY);
    expect(banner.querySelector("button")).toBeNull();
    // User-visible only: the text, titles and aria labels (a CSS class name is not shown).
    const visible = [banner.textContent ?? ""];
    for (const node of [banner, ...Array.from(banner.querySelectorAll("*"))]) {
      for (const attribute of ["title", "aria-label", "alt"]) visible.push(node.getAttribute(attribute) ?? "");
    }
    expect(visible.join(" ").toLowerCase()).not.toContain("demo");
  });

  it("the masked banner is unchanged", () => {
    render(<ReviewerBanner reviewer={{ platform: "shopee", expiresAt: EXPIRES, mode: "masked" }} />);
    expect(screen.getByTestId("reviewer-banner").textContent).toContain(REVIEWER_BANNER_COPY);
  });

  it("the shop menu labels the sample shop without the word demo", () => {
    const label = reviewerShopLabel({ name: "Dữ liệu mẫu", mode: "sample" });
    expect(label).toBe(REVIEWER_SAMPLE_SHOP_LABEL);
    for (const copy of [label, REVIEWER_SAMPLE_SHOP_BANNER_COPY]) expect(copy.toLowerCase()).not.toContain("demo");
  });
});
