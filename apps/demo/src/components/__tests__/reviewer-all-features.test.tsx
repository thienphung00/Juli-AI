import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SAMPLE_CONTENT_VIDEO,
  SAMPLE_DESCRIPTION_CARD,
  SAMPLE_FINISHED_RUN_ID,
  SAMPLE_MAIN_CARD,
  SAMPLE_MANUAL_CARD,
  SAMPLE_PHOTO_CARD,
} from "../../lib/quyet-dinh/sample-data";
import {
  REVIEWER_RESET_LABEL,
  REVIEWER_SAMPLE_NOTICE,
  REVIEWER_SIMULATED_LABEL,
  REVIEWER_SIMULATED_SETTINGS_LABEL,
} from "../../lib/reviewer/copy";
import { StaticReviewerProvider } from "../../lib/reviewer/mode";
import { resetReviewerSample, reviewerSampleClients } from "../../lib/reviewer/sample-store";
import { storeReviewerRecord } from "../../lib/reviewer/session";
import { storeActiveShop } from "../../lib/shop-session";
import { storeAuthSession } from "../../lib/supabase-auth";
import { DecisionsPageClient } from "../decisions-page-client";
import { DemoShell } from "../demo-shell";
import { RulesEditor } from "../quyet-dinh/rules-editor";
import { SettingsPageClient } from "../quyet-dinh/settings-rules";

/**
 * P32-E (D42 amendment 2, owner 2026-10-15): Shopee's ISV criteria want "all
 * features enabled for Shopee testing". The partner trial account stays on
 * the sample shop and EVERY seller write works there as a visible simulation
 * over the bundled fixtures — Từ chối, Duyệt → Thực thi → the run, consent
 * edits, cover photo, Seller Center, content drafts, Hoàn tác, Đo lường day
 * 7 / day 14, Quy tắc, Phân tích video — computed in the browser. The proof:
 * one full session through the real shell that uses all of them, and the only
 * request it makes is `GET /v1/reviewer/me`.
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

/** Every request of the session, as "METHOD url"; only "who am I" is answered. */
function spyNetwork(): string[] {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      requests.push(`${init?.method ?? (input instanceof Request ? input.method : "GET")} ${url}`);
      if (url === "/v1/reviewer/me") return json({ reviewer: true, platform: "shopee", expires_at: EXPIRES, shop: null });
      throw new Error(`no request expected in the reviewer's sample shop: ${url}`);
    }),
  );
  const send = vi.fn(() => {
    requests.push("XHR");
  });
  vi.stubGlobal(
    "XMLHttpRequest",
    vi.fn(() => ({ open: vi.fn(), send, setRequestHeader: vi.fn(), upload: {}, abort: vi.fn() })),
  );
  vi.stubGlobal("EventSource", vi.fn(() => requests.push("EventSource")));
  if (typeof navigator.sendBeacon === "function") vi.spyOn(navigator, "sendBeacon").mockImplementation(() => Boolean(requests.push("beacon")));
  return requests;
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  resetReviewerSample({ stepMs: 0 });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const productCard = (name: string) =>
  screen
    .getAllByTestId("recommendation-card")
    .find((card) => card.textContent?.includes(name) && !card.closest('[data-group-key="content"]') && !within(card).queryByTestId("drafts-chip"))!;
const contentCard = (name: string) =>
  screen.getAllByTestId("recommendation-card").find((card) => card.textContent?.includes(name) && within(card).queryByTestId("drafts-chip"))!;

/** Duyệt on a card → the simulated Duyệt → Thực thi → "Theo dõi lượt chạy (mô phỏng)". */
async function approveAndFollow(card: HTMLElement) {
  await userEvent.click(within(card).getByRole("button", { name: "Duyệt" }));
  const dialog = await screen.findByTestId("reviewer-simulation");
  expect(dialog).toHaveTextContent(REVIEWER_SIMULATED_LABEL);
  await userEvent.click(await within(dialog).findByRole("button", { name: "Thực thi (mô phỏng)" }));
  await within(dialog).findByTestId("reviewer-simulation-change");
  await userEvent.click(within(dialog).getByRole("button", { name: "Theo dõi lượt chạy (mô phỏng) ›" }));
  await waitFor(() => expect(screen.queryByTestId("reviewer-simulation")).toBeNull());
}

async function openTab(name: string) {
  await userEvent.click(screen.getByRole("tab", { name }));
}

function Shell({ children }: { readonly children: ReactNode }) {
  return <DemoShell>{children}</DemoShell>;
}

describe("P32-E — every feature simulated for the reviewer in the sample shop", () => {
  it("a full session uses every simulated write and sends nothing but GET /v1/reviewer/me", async () => {
    const requests = spyNetwork();
    storeAuthSession(SESSION);
    storeReviewerRecord({ platform: "shopee", expiresAt: EXPIRES, sample: true });

    const { rerender } = render(
      <Shell>
        <DecisionsPageClient />
      </Shell>,
    );
    await screen.findByTestId("reviewer-banner");
    await waitFor(() => expect(screen.getAllByTestId("recommendation-card").length).toBeGreaterThanOrEqual(4));
    const pageLabel = screen.getAllByTestId("simulated-label")[0];
    expect(pageLabel).toHaveTextContent(REVIEWER_SIMULATED_LABEL);
    expect(pageLabel).toHaveTextContent(REVIEWER_SAMPLE_NOTICE);
    // Nothing is read-only in the sample shop.
    expect(document.querySelector("[data-read-only]")).toBeNull();

    // -- Từ chối, with its reasons --------------------------------------------------
    const description = productCard(SAMPLE_DESCRIPTION_CARD.name);
    await userEvent.click(within(description).getByRole("button", { name: "Từ chối" }));
    const reject = screen.getByRole("dialog", { name: "Từ chối thẻ này?" });
    expect(within(reject).getByTestId("simulated-label")).toHaveTextContent(REVIEWER_SIMULATED_LABEL);
    await userEvent.click(within(reject).getByRole("radio", { name: "Lý do hoặc số liệu chưa thuyết phục" }));
    await userEvent.click(within(reject).getByRole("button", { name: "Từ chối thẻ" }));
    await waitFor(() => expect(within(description).getByTestId("card-status")).toHaveTextContent("Đã từ chối"));

    // -- Duyệt → Thực thi → the run; Sửa nội dung trước khi áp dụng ----------------------
    await approveAndFollow(productCard(SAMPLE_MAIN_CARD.name));
    const consent = await screen.findByTestId("consent-block");
    expect(screen.getByTestId("run-timeline")).toBeInTheDocument();
    await userEvent.click(within(consent).getByRole("button", { name: "✎ Sửa nội dung trước khi áp dụng" }));
    const editedDescription = screen.getByLabelText("Mô tả (bạn sửa)");
    await userEvent.clear(editedDescription);
    await userEvent.type(editedDescription, "Son lì đỏ ruby, giữ màu 8 giờ.");
    await userEvent.click(screen.getByRole("button", { name: "Lưu bản sửa" }));
    await userEvent.click(within(consent).getByRole("button", { name: "Xác nhận thay đổi này" }));
    await waitFor(() => expect(screen.getByTestId("run-timeline")).toHaveTextContent("Phiên bản mới đã được duyệt"));
    expect(screen.getByTestId("run-timeline")).toHaveTextContent("theo bản bạn sửa");

    // -- Hoàn tác on that applied simulated card ---------------------------------------
    await userEvent.click(await screen.findByRole("button", { name: "Hoàn tác" }));
    const revert = screen.getByRole("dialog", { name: "Hoàn tác thay đổi này?" });
    expect(within(revert).getByTestId("simulated-label")).toBeInTheDocument();
    await userEvent.click(within(revert).getByRole("radio", { name: "Khách phản hồi không tốt" }));
    await userEvent.click(within(revert).getByRole("button", { name: "Bắt đầu hoàn tác" }));
    const restore = await screen.findByTestId("consent-block");
    await userEvent.click(restore.querySelector(".qv-option") as HTMLElement);
    await userEvent.click(within(restore).getByRole("button", { name: "Xác nhận khôi phục" }));
    expect(await screen.findByTestId("reason-done")).toHaveTextContent("Hoàn tác hoàn thành · đã khôi phục nội dung cũ");

    // -- Cover image: the photo step ---------------------------------------------------
    await openTab("Đề xuất");
    await approveAndFollow(await waitFor(() => productCard(SAMPLE_PHOTO_CARD.name)));
    await screen.findByTestId("photo-request");
    await act(async () => {
      await userEvent.upload(screen.getByTestId("photo-input") as HTMLInputElement, new File(["png"], "a.png", { type: "image/png" }));
    });
    expect(await screen.findByTestId("consent-block")).toBeInTheDocument();

    // -- Promotion: "đã làm trên Seller Center" ----------------------------------------
    await openTab("Đề xuất");
    await approveAndFollow(await waitFor(() => productCard(SAMPLE_MANUAL_CARD.name)));
    const guide = await screen.findByTestId("seller-guide");
    await waitFor(() => expect(guide).toHaveTextContent("Làm theo 4 bước trên Seller Center"));
    for (const box of within(guide).getAllByRole("checkbox")) await userEvent.click(box);
    await userEvent.click(within(guide).getByRole("button", { name: "Tôi đã áp dụng" }));
    await waitFor(() => expect(screen.getByTestId("run-timeline")).toHaveTextContent("Tìm thấy: Giảm giá sản phẩm"));

    // -- Content card "Juli soạn · bạn làm": redraft / use / published + Phân tích video --
    await openTab("Đề xuất");
    await approveAndFollow(await waitFor(() => contentCard(SAMPLE_CONTENT_VIDEO.name)));
    const script = await screen.findByTestId("content-script");
    await userEvent.click(within(script).getByRole("button", { name: "Soạn lại" }));
    await waitFor(() => expect(screen.getByTestId("content-script")).toHaveTextContent("Bản 2 · bạn sửa trực tiếp được"));
    const analysis = await screen.findByTestId("video-analysis");
    const input = within(analysis).getByTestId("video-analysis-input") as HTMLInputElement;
    expect(input).toBeEnabled();
    await act(async () => {
      await userEvent.upload(input, new File(["mp4"], "video-cua-toi.mp4", { type: "video/mp4" }));
    });
    await waitFor(() => expect(within(analysis).getByTestId("simulated-label")).toHaveTextContent("video-cua-toi.mp4"));
    expect(within(analysis).getByTestId("video-analysis-result")).toHaveTextContent("Hook (3 giây đầu)");
    await userEvent.click(screen.getByRole("button", { name: "Dùng kịch bản này" }));
    const wait = await screen.findByTestId("content-wait");
    await userEvent.click(within(wait).getByRole("button", { name: "Tôi đã đăng video" }));
    expect(await screen.findByTestId("content-measuring")).toHaveTextContent("Đang đo kết quả");

    // -- Đo lường: day 7 / day 14 on the simulated results -------------------------------
    await openTab("Đo lường");
    const forward = await screen.findByTestId("reviewer-fast-forward");
    expect(within(forward).getByTestId("simulated-label")).toHaveTextContent(REVIEWER_SIMULATED_LABEL);
    await userEvent.click(within(forward).getByRole("button", { name: "Ngày 14 (mô phỏng)" }));
    await openTab("Ngày 14 · chốt");
    await waitFor(() => expect(screen.getAllByTestId("measure-panel").length).toBeGreaterThanOrEqual(3));
    const measured = screen.getAllByTestId("measure-panel");
    expect(measured.every((panel) => within(panel).getByTestId("measure-chip").textContent === "Đạt")).toBe(true);
    expect(measured.some((panel) => panel.textContent?.includes(SAMPLE_MANUAL_CARD.name))).toBe(true);
    expect(measured.some((panel) => panel.textContent?.includes(SAMPLE_CONTENT_VIDEO.name))).toBe(true);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Ngày 14");

    // -- Quy tắc: edit and save, kept in session memory -------------------------------
    rerender(
      <Shell>
        <SettingsPageClient />
      </Shell>,
    );
    const editor = await screen.findByTestId("rules-editor");
    expect(within(editor).getAllByTestId("simulated-label")[0]).toHaveTextContent(REVIEWER_SIMULATED_SETTINGS_LABEL);
    const margin = within(editor).getByTestId("rule-default_gross_margin_pct");
    await userEvent.clear(within(margin).getByRole("textbox"));
    await userEvent.type(within(margin).getByRole("textbox"), "35,5");
    await userEvent.click(within(margin).getByRole("button", { name: "Lưu" }));
    await waitFor(async () =>
      expect((await reviewerSampleClients().fetchRules({ token: "", shopId: "" })).default_gross_margin_pct).toMatchObject({
        value: 35.5,
        set_by: "seller",
      }),
    );

    // The same rules in Quyết định, and the runs started above are still there.
    rerender(
      <Shell>
        <DecisionsPageClient />
      </Shell>,
    );
    await waitFor(() => expect(within(productCard(SAMPLE_MAIN_CARD.name)).getByTestId("card-status")).not.toHaveTextContent("Chờ duyệt"));
    expect(reviewerSampleClients().snapshotRuns().length).toBeGreaterThan(4);

    // -- Đặt lại mô phỏng --------------------------------------------------------
    await userEvent.click(screen.getByRole("button", { name: REVIEWER_RESET_LABEL }));
    await waitFor(() => expect(within(productCard(SAMPLE_MAIN_CARD.name)).getByTestId("card-status")).toHaveTextContent("Chờ duyệt"));
    expect(reviewerSampleClients().snapshotRuns().map((run) => run.id)).toEqual([SAMPLE_FINISHED_RUN_ID]);

    // The whole session: one request, who am I. No write, no shop read, no upload.
    expect(requests).toEqual(["GET /v1/reviewer/me"]);
  }, 30_000);

  it("P37 (D47.2/D47.3): the reviewer's store walks the real lifecycle — running, failed → Chờ duyệt, expired — with only GET /v1/reviewer/me", async () => {
    const requests = spyNetwork();
    storeAuthSession(SESSION);
    storeReviewerRecord({ platform: "shopee", expiresAt: EXPIRES, sample: true });
    render(
      <Shell>
        <DecisionsPageClient />
      </Shell>,
    );
    await screen.findByTestId("reviewer-banner");
    await waitFor(() => expect(productCard(SAMPLE_MAIN_CARD.name)).toBeDefined());
    await approveAndFollow(productCard(SAMPLE_MAIN_CARD.name));
    await screen.findByTestId("consent-block");
    const store = reviewerSampleClients();
    expect(store.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("running");
    const run = store.snapshotRuns().find((entry) => entry.product_name === SAMPLE_MAIN_CARD.name)!;
    expect(run.status).toBe("waiting_approval");
    act(() => {
      store.failRun(run.id);
    });
    await openTab("Đề xuất");
    await waitFor(() => expect(within(productCard(SAMPLE_MAIN_CARD.name)).getByTestId("card-status")).toHaveTextContent("Chờ duyệt"));
    act(() => {
      store.advanceTime(7 * 86_400_000);
    });
    await waitFor(() => expect(within(productCard(SAMPLE_MAIN_CARD.name)).getByTestId("card-status")).toHaveTextContent("Hết hạn"));
    expect(requests).toEqual(["GET /v1/reviewer/me"]);
  }, 30_000);

  it("the labels belong to the reviewer's sample only: signed-out sample and a seller see none", async () => {
    const requests = spyNetwork();
    render(
      <StaticReviewerProvider reviewer={null}>
        <RulesEditor onDelete={vi.fn()} onSave={vi.fn()} rules={await reviewerSampleClients().fetchRules({ token: "", shopId: "" })} />
      </StaticReviewerProvider>,
    );
    expect(screen.queryByTestId("simulated-label")).toBeNull();
    cleanup();

    // The signed-out sample keeps its own notice and its read-only P14-F fields.
    render(
      <Shell>
        <DecisionsPageClient />
      </Shell>,
    );
    await waitFor(() => expect(screen.getAllByTestId("recommendation-card").length).toBeGreaterThanOrEqual(4));
    expect(screen.getByTestId("mock-data-notice")).toBeInTheDocument();
    expect(screen.queryByTestId("simulated-label")).toBeNull();
    expect(screen.queryByTestId("reviewer-banner")).toBeNull();
    expect(screen.queryByRole("button", { name: REVIEWER_RESET_LABEL })).toBeNull();
    expect(requests).toEqual([]);
  });

  it("a reviewer pinned to a real shop stays read-only (P32-A unchanged)", async () => {
    spyNetwork();
    storeAuthSession(SESSION);
    storeActiveShop({ id: "alias", name: "Shop 001" });
    render(
      <StaticReviewerProvider reviewer={{ platform: "shopee", expiresAt: EXPIRES }}>
        <SettingsPageClient />
      </StaticReviewerProvider>,
    );
    // Not the sample: the signed-in rules screen reads the API (refused here), no simulated label.
    await waitFor(() => expect(screen.queryByText("Đang tải…")).toBeNull());
    expect(screen.queryByTestId("simulated-label")).toBeNull();
  });
});
