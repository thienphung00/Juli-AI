import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "../app/page";
import { AnalysisPageClient } from "../components/analysis-page-client";
import { DecisionsPageClient } from "../components/decisions-page-client";
import { DemoStateProvider } from "../components/demo-state";
import { OnboardingStrip, etaText } from "../components/onboarding/onboarding-strip";
import {
  ONBOARDING_API_PATH,
  OnboardingFetchError,
  fetchOnboardingStatus,
  onboardingReportReady,
  type OnboardingStatus,
} from "../lib/onboarding/api-client";
import { sampleEnvelope } from "../lib/phan-tich/sample-data";
import { ACTIVE_SHOP_STORAGE_KEY } from "../lib/shop-session";
import { ShopReportProvider } from "../lib/shop-report/shop-report-context";
import { AUTH_SESSION_STORAGE_KEY } from "../lib/supabase-auth";

/**
 * P17 (D26, contract `fasttrack/contracts/p17-onboarding-speed.md` §2): the
 * onboarding strip on Trang chủ / Quyết định / Phân tích, its client and its
 * polling; the sample doors make no onboarding request.
 */

let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => searchParams,
}));

function status(overrides: Partial<OnboardingStatus> = {}): OnboardingStatus {
  return {
    shop_id: "shop-1",
    active: true,
    current_step: 2,
    total_steps: 3,
    label: "Juli đang đọc dữ liệu shop · bước 2/3",
    poll_interval_seconds: 15,
    steps: [
      { key: "quick_scan", label: "Quét nhanh 14 ngày", status: "done", percent: 100, eta_seconds: null, detail: "2 đề xuất nhanh" },
      {
        key: "backfill_diagnosis",
        label: "Đọc 60 ngày và chẩn đoán đầy đủ",
        status: "running",
        percent: 40,
        eta_seconds: 540,
        detail: "24/60 ngày",
      },
      { key: "history", label: "Tải lịch sử nền", status: "pending", percent: 13, eta_seconds: null, detail: null },
    ],
    history_days_available: 24,
    history_target_days: 180,
    history_days_remaining: 156,
    history_complete: false,
    window_90d_available: false,
    ...overrides,
  };
}

const HISTORY_ONLY = status({
  active: false,
  current_step: 3,
  label: "Đang tải lịch sử · còn 120 ngày",
  poll_interval_seconds: 300,
});
const DONE = status({ active: false, current_step: null, label: null, poll_interval_seconds: null });

function json(body: unknown, init: ResponseInit = { status: 200 }): Response {
  return new Response(JSON.stringify(body), { ...init, headers: { "Content-Type": "application/json" } });
}

function signInWithShop() {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }));
  window.localStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify({ id: "shop-1", name: "Shop Thật" }));
}

function renderInShell(page: React.ReactNode, loadAnalysis = vi.fn().mockResolvedValue(sampleEnvelope())) {
  render(
    <DemoStateProvider>
      <ShopReportProvider loadAnalysis={loadAnalysis}>{page}</ShopReportProvider>
    </DemoStateProvider>,
  );
  return loadAnalysis;
}

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  searchParams = new URLSearchParams();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("fetchOnboardingStatus", () => {
  it("GETs /v1/shops/me/onboarding with bearer + X-Shop-Id and returns the body", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(json(status()));
    const body = await fetchOnboardingStatus({ token: "t", shopId: "s", fetchImpl });
    expect(ONBOARDING_API_PATH).toBe("/v1/shops/me/onboarding");
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe("/v1/shops/me/onboarding");
    expect(init.headers).toMatchObject({ Authorization: "Bearer t", "X-Shop-Id": "s" });
    expect(body.label).toBe("Juli đang đọc dữ liệu shop · bước 2/3");
  });

  it("rejects a non-OK response and a malformed body", async () => {
    await expect(
      fetchOnboardingStatus({ token: "t", shopId: "s", fetchImpl: vi.fn().mockResolvedValue(json({}, { status: 500 })) }),
    ).rejects.toBeInstanceOf(OnboardingFetchError);
    await expect(
      fetchOnboardingStatus({ token: "t", shopId: "s", fetchImpl: vi.fn().mockResolvedValue(json({ nope: 1 })) }),
    ).rejects.toBeInstanceOf(OnboardingFetchError);
  });

  it("onboardingReportReady is true once step 2 is done", () => {
    expect(onboardingReportReady(status())).toBe(false);
    expect(onboardingReportReady(HISTORY_ONLY)).toBe(false);
    const steps = status().steps.map((s) => (s.key === "backfill_diagnosis" ? { ...s, status: "done" as const } : s));
    expect(onboardingReportReady(status({ steps }))).toBe(true);
  });
});

describe("OnboardingStrip", () => {
  it("active: the label, three steps with status, percent and ETA", () => {
    render(<OnboardingStrip status={status()} />);
    const strip = screen.getByTestId("onboarding-strip");
    expect(strip).toHaveTextContent("Juli đang đọc dữ liệu shop · bước 2/3");
    const steps = screen.getAllByTestId("onboarding-step");
    expect(steps).toHaveLength(3);
    expect(steps[0]).toHaveTextContent("1. Quét nhanh 14 ngày");
    expect(steps[0]).toHaveTextContent("Xong");
    expect(steps[1]).toHaveTextContent("Đang chạy · 40 % · khoảng 9 phút");
    expect(steps[2]).toHaveTextContent("Chờ");
  });

  it("history only: a quiet note with the label, no steps", () => {
    render(<OnboardingStrip status={HISTORY_ONLY} />);
    expect(screen.getByTestId("onboarding-note")).toHaveTextContent("Đang tải lịch sử · còn 120 ngày");
    expect(screen.queryByTestId("onboarding-strip")).toBeNull();
  });

  it("done or unreadable: nothing", () => {
    const { container, rerender } = render(<OnboardingStrip status={DONE} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<OnboardingStrip status={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("etaText rounds to minutes and hides unknown", () => {
    expect(etaText(540)).toBe("khoảng 9 phút");
    expect(etaText(20)).toBe("khoảng 1 phút");
    expect(etaText(null)).toBeNull();
    expect(etaText(0)).toBeNull();
  });
});

function routeFetch(onboarding: () => Response | Promise<Response>, decisions: () => unknown[] = () => []) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url === ONBOARDING_API_PATH) return onboarding();
    if (url === "/v1/demo/decisions") return json({ success: true, data: decisions(), error: null });
    return json({ detail: "not found" }, { status: 404 });
  });
}

function onboardingCalls(spy: ReturnType<typeof routeFetch>): number {
  return spy.mock.calls.filter(([url]) => String(url) === ONBOARDING_API_PATH).length;
}

describe("the strip on the three pages (signed in with a shop)", () => {
  it("Trang chủ shows it above the report", async () => {
    signInWithShop();
    routeFetch(() => json(status()));
    renderInShell(<HomePage />);
    expect(await screen.findByTestId("onboarding-strip")).toHaveTextContent("bước 2/3");
    expect(await screen.findByRole("region", { name: "Ma trận 5 luồng truy cập" })).toBeInTheDocument();
  });

  it("Phân tích shows it", async () => {
    signInWithShop();
    routeFetch(() => json(status()));
    renderInShell(<AnalysisPageClient />);
    expect(await screen.findByTestId("onboarding-strip")).toHaveTextContent("bước 2/3");
  });

  it("Phân tích with no report yet re-reads the report once step 2 is done", async () => {
    signInWithShop();
    const steps = status().steps.map((s) => (s.key === "backfill_diagnosis" ? { ...s, status: "done" as const } : s));
    routeFetch(() => json(status({ steps, current_step: 3, active: false, label: "Đang tải lịch sử · còn 120 ngày", poll_interval_seconds: 300 })));
    const loadAnalysis = vi.fn().mockResolvedValueOnce(null).mockResolvedValue(sampleEnvelope());
    renderInShell(<AnalysisPageClient />, loadAnalysis);
    await waitFor(() => expect(loadAnalysis).toHaveBeenCalledTimes(2));
  });

  it("Quyết định shows it and re-reads the cards on each poll while active", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    signInWithShop();
    let polls = 0;
    const spy = routeFetch(
      () => {
        polls += 1;
        return json(status());
      },
      () => [],
    );
    renderInShell(<DecisionsPageClient />);
    expect(await screen.findByTestId("onboarding-strip")).toBeInTheDocument();
    const decisionReads = () => spy.mock.calls.filter(([url]) => String(url) === "/v1/demo/decisions").length;
    await waitFor(() => expect(decisionReads()).toBe(1));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    await waitFor(() => expect(polls).toBe(2));
    await waitFor(() => expect(decisionReads()).toBe(2));
  });
});

describe("polling", () => {
  it("polls every poll_interval_seconds, slows to 300 s for history and stops when null", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    signInWithShop();
    const sequence = [status(), HISTORY_ONLY, DONE];
    let index = 0;
    const spy = routeFetch(() => json(sequence[Math.min(index++, sequence.length - 1)]));
    renderInShell(<AnalysisPageClient />);
    expect(await screen.findByTestId("onboarding-strip")).toBeInTheDocument();
    expect(onboardingCalls(spy)).toBe(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(await screen.findByTestId("onboarding-note")).toHaveTextContent("còn 120 ngày");
    expect(onboardingCalls(spy)).toBe(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(299_000);
    });
    expect(onboardingCalls(spy)).toBe(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    await waitFor(() => expect(onboardingCalls(spy)).toBe(3));
    await waitFor(() => expect(screen.queryByTestId("onboarding-note")).toBeNull());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600_000);
    });
    expect(onboardingCalls(spy)).toBe(3);
  });

  it("a failed read hides the strip and retries after a minute", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    signInWithShop();
    let fail = true;
    const spy = routeFetch(() => (fail ? json({}, { status: 500 }) : json(status())));
    renderInShell(<AnalysisPageClient />);
    await waitFor(() => expect(onboardingCalls(spy)).toBe(1));
    expect(screen.queryByTestId("onboarding-strip")).toBeNull();
    fail = false;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(await screen.findByTestId("onboarding-strip")).toBeInTheDocument();
  });
});

describe("the sample doors make no onboarding request", () => {
  it("anonymous: no strip, no request (Trang chủ, Phân tích, Quyết định)", async () => {
    const spy = vi.spyOn(globalThis, "fetch");
    for (const page of [<HomePage key="h" />, <AnalysisPageClient key="a" />, <DecisionsPageClient key="d" />]) {
      const { unmount } = render(
        <DemoStateProvider>
          <ShopReportProvider loadAnalysis={vi.fn()}>{page}</ShopReportProvider>
        </DemoStateProvider>,
      );
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
      expect(screen.queryByTestId("onboarding-strip")).toBeNull();
      unmount();
    }
    expect(screen.queryByTestId("onboarding-strip")).toBeNull();
    expect(onboardingCalls(spy as ReturnType<typeof routeFetch>)).toBe(0);
  });

  it("signed in without a shop: the P13 strip only, no onboarding request", async () => {
    window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }));
    const spy = vi.spyOn(globalThis, "fetch");
    renderInShell(<DecisionsPageClient />, vi.fn());
    expect(await screen.findByTestId("no-shop-sample-strip")).toBeInTheDocument();
    expect(screen.queryByTestId("onboarding-strip")).toBeNull();
    expect(spy).not.toHaveBeenCalled();
  });
});
