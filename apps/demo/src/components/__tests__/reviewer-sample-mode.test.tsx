import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SAMPLE_MAIN_CARD, SAMPLE_MANUAL_CARD } from "../../lib/quyet-dinh/sample-data";
import { fetchReviewerMe } from "../../lib/reviewer/api-client";
import { REVIEWER_BANNER_COPY, REVIEWER_SAMPLE_BANNER_COPY, REVIEWER_SIMULATED_LABEL } from "../../lib/reviewer/copy";
import { simulateSampleDecision } from "../../lib/reviewer/sample-simulation";
import { resetReviewerSample } from "../../lib/reviewer/sample-store";
import { readReviewerRecord, storeReviewerRecord } from "../../lib/reviewer/session";
import { readActiveShop, storeActiveShop } from "../../lib/shop-session";
import { storeAuthSession } from "../../lib/supabase-auth";
import { ReviewerBanner } from "../app-shell/reviewer-banner";
import { DecisionsPageClient } from "../decisions-page-client";
import { DemoShell } from "../demo-shell";
import { PartnerSignIn } from "../partner-sign-in";

/**
 * P32-D (D42 amendment, owner 2026-10-15): with `REVIEWER_SHOP_ID` unset the
 * API answers `/v1/reviewer/me` with `shop: null`, and the partner trial
 * account lands on the sample shop ("Cửa hàng Mẫu Hoa Mai", P11/P13) — the
 * reviewer banner, no connect strip, no shop API call, and Duyệt → Thực thi as
 * a visibly simulated flow that sends nothing.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const EXPIRES = "2026-11-13T00:00:00Z";
const SESSION = { accessToken: "at", refreshToken: null, expiresIn: 3600, tokenType: "bearer" };

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  window.localStorage.clear();
  resetReviewerSample({ stepMs: 0 });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("shop: null from /v1/reviewer/me", () => {
  it("parses as a reviewer with no shop", async () => {
    const result = await fetchReviewerMe("at", async () =>
      json({ reviewer: true, platform: "shopee", expires_at: EXPIRES, shop: null }),
    );
    expect(result).toEqual({ status: "reviewer", me: { reviewer: true, platform: "shopee", expiresAt: EXPIRES, shop: null } });
  });

  it("sign-in stores no active shop and a sample reviewer record", async () => {
    storeActiveShop({ id: "stale", name: "Stale" });
    const onSignedIn = vi.fn();
    render(
      <PartnerSignIn
        fetchMe={vi.fn().mockResolvedValue({
          status: "reviewer",
          me: { reviewer: true, platform: "shopee", expiresAt: EXPIRES, shop: null },
        })}
        onSignedIn={onSignedIn}
        signIn={vi.fn().mockResolvedValue({ ok: true, session: SESSION })}
      />,
    );
    await userEvent.type(screen.getByLabelText("Email"), "shopee-review@app-juli.com");
    await userEvent.type(screen.getByLabelText("Mật khẩu"), "s3cret");
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
    await waitFor(() => expect(onSignedIn).toHaveBeenCalled());
    expect(readActiveShop()).toBeNull();
    expect(readReviewerRecord()).toEqual({ platform: "shopee", expiresAt: EXPIRES, sample: true });
  });

  it("the banner says thao tác chỉ mô phỏng in sample mode, ẩn tên when pinned", () => {
    const { rerender } = render(<ReviewerBanner reviewer={{ platform: "shopee", expiresAt: EXPIRES, sample: true }} />);
    expect(screen.getByTestId("reviewer-banner")).toHaveTextContent(REVIEWER_SAMPLE_BANNER_COPY);
    expect(screen.getByTestId("reviewer-banner")).toHaveTextContent("thao tác chỉ mô phỏng");
    expect(screen.getByTestId("reviewer-banner")).toHaveTextContent("Đối tác Shopee");
    rerender(<ReviewerBanner reviewer={{ platform: "shopee", expiresAt: EXPIRES }} />);
    expect(screen.getByTestId("reviewer-banner")).toHaveTextContent(REVIEWER_BANNER_COPY);
  });
});

describe("the sample shop for a reviewer, in the real shell", () => {
  it("banner, no connect strip, simulated Duyệt → Thực thi, and no request but /v1/reviewer/me", async () => {
    const urls: string[] = [];
    const fetchImpl = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      urls.push(`${init?.method ?? "GET"} ${url}`);
      if (url === "/v1/reviewer/me") {
        return json({ reviewer: true, platform: "shopee", expires_at: EXPIRES, shop: null });
      }
      throw new Error(`no request expected in sample mode: ${url}`);
    });
    vi.stubGlobal("fetch", fetchImpl);
    storeAuthSession(SESSION);
    storeReviewerRecord({ platform: "shopee", expiresAt: EXPIRES, sample: true });

    render(
      <DemoShell>
        <DecisionsPageClient />
      </DemoShell>,
    );

    const banner = await screen.findByTestId("reviewer-banner");
    expect(banner).toHaveTextContent(REVIEWER_SAMPLE_BANNER_COPY);
    const cards = await screen.findAllByTestId("recommendation-card");
    expect(screen.queryByTestId("no-shop-sample-strip")).toBeNull();
    expect(screen.queryByText("Kết nối TikTok Shop ›")).toBeNull();

    const card = cards.find((element) => element.textContent?.includes(SAMPLE_MAIN_CARD.name)) ?? cards[0];
    // P32-E: nothing is read-only in the sample shop any more.
    expect(within(card).getByRole("button", { name: "Từ chối" })).toBeEnabled();
    await userEvent.click(within(card).getByRole("button", { name: "Duyệt" }));
    const panel = await screen.findByTestId("reviewer-simulation");
    expect(panel).toHaveTextContent(REVIEWER_SIMULATED_LABEL);
    expect(await within(panel).findByText("Đã duyệt (mô phỏng)")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Thực thi (mô phỏng)" }));
    const change = await within(panel).findByTestId("reviewer-simulation-change");
    // P41 (D47.7): Trước/Sau and one short line — no endpoint, no second disclaimer.
    expect(change).toHaveTextContent("Với shop thật, Juli ghi thay đổi này lên TikTok Shop sau khi bạn xác nhận, rồi đo ở ngày 7 và 14.");
    expect(panel).not.toHaveTextContent("/product/");
    expect(panel).not.toHaveTextContent("update_product_listing");
    expect(panel).not.toHaveTextContent("Không có thay đổi nào được gửi tới TikTok Shop.");

    // The card stays pending in the sample: no run was started, not even in memory.
    await userEvent.click(within(panel).getByRole("button", { name: "Đóng" }));
    expect(screen.queryByTestId("reviewer-simulation")).toBeNull();
    expect(within(card).getByRole("button", { name: "Duyệt" })).toBeEnabled();

    // The only request of the whole session: who am I. No write, no shop read.
    expect(urls).toEqual(["GET /v1/reviewer/me"]);
    expect(readActiveShop()).toBeNull();
  });

  it("the sample simulation mirrors the API's: listing edit, promotion without a TikTok write, unknown card 404", async () => {
    const listing = await simulateSampleDecision(SAMPLE_MAIN_CARD.id, "execute");
    expect(listing).toMatchObject({ simulated: true, enqueued: false, tiktok_write: false, label: REVIEWER_SIMULATED_LABEL });
    expect(listing.change.request?.operation).toBe("update_product_listing");
    expect(listing.change.product.title).toBe(SAMPLE_MAIN_CARD.name);
    expect(listing.steps.every((step) => step.done)).toBe(true);
    const promo = await simulateSampleDecision(SAMPLE_MANUAL_CARD.id, "approve");
    expect(promo.change.request).toBeNull();
    expect(promo.steps.map((step) => step.done)).toEqual([true, false]);
    await expect(simulateSampleDecision("nope", "approve")).rejects.toMatchObject({ status: 404 });
  });
});
