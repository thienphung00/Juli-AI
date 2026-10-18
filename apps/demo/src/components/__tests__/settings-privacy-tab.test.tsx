import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StaticReviewerProvider } from "../../lib/reviewer/mode";
import { storeActiveShop } from "../../lib/shop-session";
import { storeAuthSession } from "../../lib/supabase-auth";
import { DemoStateProvider } from "../demo-state";
import { SettingsPageClient, readSettingsTab } from "../quyet-dinh/settings-rules";

/** P50 (D60.6): Cài đặt → Quyền riêng tư, signed-in sellers only. */

const PRIVACY = {
  marketing_opt_out: false,
  ad_measurement_opt_out: false,
  case_study_opt_in: false,
  terms_date_accepted: "2026-10-18",
  terms_accepted_at: null,
  liability_clause_accepted_at: null,
  current_terms_date: "2026-10-18",
  needs_terms_acceptance: false,
  deletion_scheduled_for: null,
};

let requests: string[];

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/settings");
  requests = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      requests.push(input);
      if (input === "/v1/me/privacy") return new Response(JSON.stringify(PRIVACY), { status: 200 });
      return new Response(JSON.stringify({ detail: "not here" }), { status: 404 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function signIn(withShop = true) {
  storeAuthSession({ accessToken: "tok", refreshToken: null, expiresIn: 3600, tokenType: "bearer" });
  if (withShop) storeActiveShop({ id: "shop-1", name: "Shop Một" });
}

describe("the settings tabs", () => {
  it("opens on Quy tắc and switches to Quyền riêng tư, keeping it in the URL", async () => {
    const user = userEvent.setup();
    signIn();
    render(<SettingsPageClient />);

    const rulesTab = await screen.findByRole("tab", { name: "Quy tắc" });
    expect(rulesTab).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByRole("tab", { name: "Quyền riêng tư" }));

    expect(await screen.findByRole("switch", { name: "Không nhận email tiếp thị" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Quyền riêng tư" })).toHaveAttribute("aria-selected", "true");
    expect(window.location.search).toBe("?tab=quyen-rieng-tu");
  });

  it("opens Quyền riêng tư straight from ?tab=quyen-rieng-tu", async () => {
    window.history.replaceState(null, "", "/settings?tab=quyen-rieng-tu");
    signIn();
    render(<SettingsPageClient />);

    expect(await screen.findByRole("switch", { name: "Không đo lường quảng cáo" })).toBeInTheDocument();
    expect(readSettingsTab("?tab=other")).toBe("rules");
  });

  it("gives a signed-in seller with no shop yet the privacy page", async () => {
    signIn(false);
    render(<SettingsPageClient />);

    expect(await screen.findByRole("button", { name: "Xoá tài khoản" })).toBeInTheDocument();
  });

  it("shows no privacy tab and calls no privacy route for a partner trial account", async () => {
    signIn();
    render(
      <StaticReviewerProvider reviewer={{ platform: "shopee", expiresAt: null }}>
        <SettingsPageClient />
      </StaticReviewerProvider>,
    );

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(screen.queryByRole("tab", { name: "Quyền riêng tư" })).toBeNull();
    expect(requests).not.toContain("/v1/me/privacy");
  });

  it("asks nothing of a signed-out visitor", async () => {
    render(
      <DemoStateProvider>
        <SettingsPageClient />
      </DemoStateProvider>,
    );

    await waitFor(() => expect(screen.queryByText("Đang tải…")).toBeNull());
    expect(screen.queryByRole("tab", { name: "Quyền riêng tư" })).toBeNull();
    expect(requests).toEqual([]);
  });
});
