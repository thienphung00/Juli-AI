import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ShopeeApiError } from "../../lib/shopee-analytics/client";
import { StaticReviewerProvider } from "../../lib/reviewer/mode";
import type { ReviewerRecord } from "../../lib/reviewer/session";
import type { RecoApi } from "../../lib/shopee-decisions/client";
import { RecoHostProvider } from "../../lib/shopee-decisions/context";
import { detailOf, fakeReco, voucherCard } from "../../lib/shopee-decisions/__tests__/fixtures";
import type { ExecutionCard, ExecutionStates } from "../../lib/shopee-decisions/types";
import { AUTH_SESSION_STORAGE_KEY } from "../../lib/supabase-auth";
import { ResourceState } from "../shopee-analytics/ui";
import { CardPage } from "../shopee-decisions/card-page";
import { hostOf } from "../shopee-decisions/__tests__/harness";
import { ThucHienView } from "../shopee-decisions/thuc-hien";

/**
 * P100 S2-D4 (owner, 2026-11-14): the reviewer's sample shop has no Juli Connector — no Connector
 * bar, status, fill button, "Mở Seller Centre" or fill-queue call — and Thực hiện still works
 * ("Đã làm"). Synthetic data only.
 */

const SAMPLE: ReviewerRecord = { platform: "shopee", expiresAt: "2026-11-25T00:00:00Z", mode: "sample" };

const exec = (over: Partial<ExecutionCard>): ExecutionCard => ({
  card_id: "c1",
  code: "JC-2611-0001",
  title: "Tiêu đề đưa từ khóa lên đầu",
  family: "listing",
  family_label: "Listing · Tiêu đề",
  change_kind: "title",
  product_id: "P1",
  state: "cho_dien",
  completed: 1,
  bad: null,
  fields: { filled: 0, total: 0 },
  jobs: { total: 0, filled: 0, saved: 0, failed: 0 },
  noun: "tiêu đề",
  not_seen: false,
  mismatch: null,
  executed_at: null,
  verified_at: null,
  measure_start: null,
  measure_days: null,
  open_job: { id: "11111111-2222-4333-8444-555555555555", open_path: "/portal/product/1" },
  ...over,
});

const states = (cards: ExecutionCard[]): ExecutionStates => ({
  platform: "shopee",
  connector: { version: "0.3.18", last_check_at: "2026-11-13T09:05:00", connected: false, seller_centre_open: false },
  cards,
  counts: {},
});

function asSample(ui: ReactElement, reco: RecoApi = fakeReco()) {
  return render(
    <StaticReviewerProvider reviewer={SAMPLE}>
      <RecoHostProvider host={hostOf(reco)}>{ui}</RecoHostProvider>
    </StaticReviewerProvider>,
  );
}

beforeEach(() => {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});
afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("S2-D4 · the sample shop has no Juli Connector", () => {
  it("Thực hiện: no Connector bar or step, no Mở Seller Centre, and Đã làm moves the card on", async () => {
    const reco = fakeReco({ execution: states([exec({ card_id: "a" }), exec({ card_id: "b", state: "khop", completed: 4, measure_start: "2026-11-05", measure_days: 30 })]) });
    asSample(<ThucHienView />, reco);
    const row = await screen.findByTestId("sd-th-a");
    expect(screen.queryByTestId("sd-th-bar")).toBeNull();
    expect(screen.getByTestId("sd-thuc-hien").textContent).not.toMatch(/Connector|Đối chiếu ngay/);
    expect(screen.getByTestId("sd-th-step-a-2")).toHaveTextContent("Bạn điền");
    expect(within(row).queryByRole("link", { name: "Mở Seller Centre" })).toBeNull();
    expect(within(row).queryByRole("button", { name: "Mở Seller Centre" })).toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: "Đã làm" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "executed" && c.args[0] === "a")).toBe(true));
  });

  it("the card's execution panel never asks for the fill queue nor links to Seller Centre", async () => {
    const f = vi.fn(async () => new Response(JSON.stringify({ data: { enabled: true, jobs: [] } }), { status: 200 }));
    vi.stubGlobal("fetch", f);
    asSample(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(voucherCard(), { status: "approved" }) }));
    const panel = await screen.findByTestId("sd-execution");
    expect(panel.textContent).not.toMatch(/Connector/);
    expect(within(panel).queryAllByRole("link")).toHaveLength(0);
    expect(within(panel).getByRole("button", { name: "Đã làm" })).toBeInTheDocument();
    expect(f.mock.calls.map((c) => String((c as unknown[])[0]))).not.toEqual(expect.arrayContaining([expect.stringMatching(/fill-jobs|connector-fill/)]));
  });

  it("S2-F2: a voucher card's Đã làm asks for no Seller Centre code on the sample shop", async () => {
    const reco = fakeReco({ detail: detailOf(voucherCard(), { status: "approved" }) });
    asSample(<CardPage from={null} id="card-voucher" />, reco);
    const panel = await screen.findByTestId("sd-execution");
    expect(within(panel).queryByPlaceholderText("Ví dụ: 1234567890")).toBeNull();
    const done = within(panel).getByRole("button", { name: "Đã làm" });
    expect(done).toBeEnabled();
    fireEvent.click(done);
    await waitFor(() => expect(reco.calls.some((c) => c.name === "executed")).toBe(true));
  });

  it("S2-F2: a refused Đã làm on Thực hiện is said, not silent", async () => {
    const reco = fakeReco({ execution: states([exec({ card_id: "v", family: "voucher", change_kind: "min_spend_voucher" })]) }, { executed: new ShopeeApiError(422, "reco_invalid", "voucher_id is required to verify a voucher") });
    asSample(<ThucHienView />, reco);
    const row = await screen.findByTestId("sd-th-v");
    fireEvent.click(within(row).getByRole("button", { name: "Đã làm" }));
    expect(await screen.findByTestId("sd-th-error-v")).toBeInTheDocument();
  });

  it("an empty shop's notice does not name the Connector on the sample shop", () => {
    render(
      <StaticReviewerProvider reviewer={SAMPLE}>
        <ResourceState resource={{ status: "refused", refusal: "no-data", error: null } as never}>{() => null}</ResourceState>
      </StaticReviewerProvider>,
    );
    expect(screen.getByTestId("sa-refusal-no-data").textContent).not.toMatch(/Connector/);
  });
});
