import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoLanding } from "../components/demo-landing";
import { ENTRY_MODE_STORAGE_KEY } from "../lib/entry-mode";
import { buildGoogleAuthorizeUrl } from "../lib/supabase-auth";

/**
 * DemoLanding's own responsibility is branching on whatever
 * buildGoogleAuthorizeUrl returns, not on whether a given
 * NEXT_PUBLIC_SUPABASE_* combination maps to a URL or to null -- that
 * mapping is supabase-auth.ts's own concern and is already covered
 * exhaustively by supabase-auth.test.ts. This file used to mutate
 * process.env directly (set real-looking values in beforeEach, `delete`
 * them in the two "unconfigured" cases) to drive that branching, which
 * quietly depended on the demo's real build-time env being ABSENT
 * wherever this test ran -- true only until #1905 got CI's Supabase
 * secrets configured, at which point deleting the runtime process.env key
 * stopped being able to force the unconfigured branch (whatever mechanism
 * produced that in a given CI run, mutating process.env after the fact is
 * not a reliable way to control it -- controlling the seam directly is).
 * Mocking the module instead makes both branches deterministic regardless
 * of what CI's actual env looks like when this file runs.
 */
const SUPABASE_ORIGIN_AUTHORIZE_URL =
  "https://rmxzbvgiwrvjuzlzqdcz.supabase.co/auth/v1/authorize?provider=google&redirect_to=http%3A%2F%2Flocalhost%2Fauth%2Fcallback&apikey=anon-key-for-tests";

vi.mock("../lib/supabase-auth", () => ({
  buildGoogleAuthorizeUrl: vi.fn(),
  GOOGLE_SIGN_IN_UNAVAILABLE_COPY:
    "Đăng nhập với Google chưa sẵn sàng trong môi trường này.",
}));

const mockedBuildGoogleAuthorizeUrl = vi.mocked(buildGoogleAuthorizeUrl);

beforeEach(() => {
  window.sessionStorage.clear();
  // DemoLanding reads `?entry=door` from window.location.search (not
  // useSearchParams — see the component's own comment on the
  // missing-suspense-with-csr-bailout build error), so tests drive the
  // real URL. Reset it to a bare `/` between tests.
  window.history.replaceState(null, "", "/");
  mockedBuildGoogleAuthorizeUrl.mockReturnValue(SUPABASE_ORIGIN_AUTHORIZE_URL);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("DemoLanding — the two doors", () => {
  it("shows both entries on a first visit, each honestly labelled", () => {
    render(<DemoLanding />);

    expect(
      screen.getByRole("button", { name: /Dùng thử Demo/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Đăng nhập với Google/ }),
    ).toBeInTheDocument();

    // The demo door must say, in its own copy, that it is a demonstration —
    // never implying the visitor is looking at their own shop's data.
    const doors = screen.getByRole("group", { name: "Chọn lối vào" });
    expect(within(doors).getByText(/minh họa|dữ liệu mẫu/)).toBeInTheDocument();
  });

  it("never issues a fetch merely by rendering the landing", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(<DemoLanding />);

    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("the Google door is a real link to the Supabase authorize endpoint, not a disabled stub", async () => {
    render(<DemoLanding />);

    await waitFor(() => {
      const link = screen.getByRole("link", {
        name: /Đăng nhập với Google/,
      });
      expect(link).toHaveAttribute(
        "href",
        expect.stringContaining("rmxzbvgiwrvjuzlzqdcz.supabase.co/auth/v1/authorize"),
      );
    });

    const link = screen.getByRole("link", { name: /Đăng nhập với Google/ });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("provider=google"),
    );
    expect(link.getAttribute("aria-disabled")).toBeNull();
  });

  it("clicking Dùng thử Demo reveals the replay content with no navigation and no fetch", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(<DemoLanding />);
    await user.click(screen.getByRole("button", { name: /Dùng thử Demo/ }));

    expect(
      screen.getByRole("region", { name: "Điểm đến chính" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("mock-data-notice")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(ENTRY_MODE_STORAGE_KEY)).toBe(
      "replay",
    );
    fetchSpy.mockRestore();
  });

  it("skips straight to the replay content on a later render within the same session", async () => {
    window.sessionStorage.setItem(ENTRY_MODE_STORAGE_KEY, "replay");

    render(<DemoLanding />);

    expect(
      await screen.findByRole("region", { name: "Điểm đến chính" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Dùng thử Demo/ }),
    ).not.toBeInTheDocument();
  });

  // Issue #1907: the sign-in door was unreachable once a visitor entered the
  // replay demo, by any navigation, because `/` always short-circuited back
  // to HomeLauncher. `/?entry=door` is the explicit escape.
  it("renders both doors at /?entry=door even with replay stored — the explicit escape from the short-circuit", async () => {
    window.sessionStorage.setItem(ENTRY_MODE_STORAGE_KEY, "replay");
    window.history.replaceState(null, "", "/?entry=door");

    render(<DemoLanding />);

    // Both the `hasEnteredReplay` read and the Google-href resolution are
    // deferred one macrotask (setTimeout(0)); wait for the latter so the
    // assertions below run AFTER the deferred replay-mode read has settled,
    // not merely during the synchronous pre-effect first paint (which would
    // pass trivially regardless of whether the escape actually works).
    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: /Đăng nhập với Google/ }),
      ).toHaveAttribute("href");
    });

    expect(
      screen.getByRole("button", { name: /Dùng thử Demo/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Đăng nhập với Google/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Điểm đến chính" }),
    ).not.toBeInTheDocument();
  });

  it("still renders HomeLauncher on a bare / with replay stored — existing behaviour preserved, not replaced", async () => {
    window.sessionStorage.setItem(ENTRY_MODE_STORAGE_KEY, "replay");

    render(<DemoLanding />);

    expect(
      await screen.findByRole("region", { name: "Điểm đến chính" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Dùng thử Demo/ }),
    ).not.toBeInTheDocument();
  });

  it("keyboard focus can reach both doors in order", async () => {
    const user = userEvent.setup();

    render(<DemoLanding />);

    // Wait for the Google door's href to resolve — the disabled placeholder
    // state (a non-focusable span) would otherwise break tab order.
    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: /Đăng nhập với Google/ }),
      ).toHaveAttribute("href");
    });

    await user.tab();
    expect(screen.getByRole("button", { name: /Dùng thử Demo/ })).toHaveFocus();

    await user.tab();
    expect(
      screen.getByRole("link", { name: /Đăng nhập với Google/ }),
    ).toHaveFocus();
  });

  it("renders an honest, non-broken Google door when buildGoogleAuthorizeUrl reports unconfigured (null)", () => {
    mockedBuildGoogleAuthorizeUrl.mockReturnValue(null);

    render(<DemoLanding />);

    const link = screen.getByRole("link", { name: /Đăng nhập với Google/ });
    expect(link).toHaveAttribute("aria-disabled", "true");
  });

  // Issue #1905: the disabled state's explanation must be VISIBLE copy, not
  // only the aria-label above -- that is exactly what shipped a defect no
  // sighted, non-screen-reader visitor could see any explanation for.
  it("shows visible Vietnamese copy explaining the disabled Google door when buildGoogleAuthorizeUrl reports unconfigured (null), resolved from dictionary.md `auth.google.unavailable`", async () => {
    mockedBuildGoogleAuthorizeUrl.mockReturnValue(null);

    render(<DemoLanding />);

    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: /Đăng nhập với Google/ }),
      ).toHaveAttribute("aria-disabled", "true");
    });

    expect(
      screen.getByText("Đăng nhập với Google chưa sẵn sàng trong môi trường này."),
    ).toBeVisible();
  });

  it("never shows the unavailable copy once the Google door is actually configured", async () => {
    render(<DemoLanding />);

    await waitFor(() => {
      const link = screen.getByRole("link", { name: /Đăng nhập với Google/ });
      expect(link).toHaveAttribute("href");
    });

    expect(
      screen.queryByText("Đăng nhập với Google chưa sẵn sàng trong môi trường này."),
    ).not.toBeInTheDocument();
  });
});
