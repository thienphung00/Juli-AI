import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoLanding } from "../components/demo-landing";
import { ENTRY_MODE_STORAGE_KEY } from "../lib/entry-mode";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  window.sessionStorage.clear();
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://rmxzbvgiwrvjuzlzqdcz.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key-for-tests";
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
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

  it("renders an honest, non-broken Google door even when Supabase env is missing", () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

    render(<DemoLanding />);

    const link = screen.getByRole("link", { name: /Đăng nhập với Google/ });
    expect(link).toHaveAttribute("aria-disabled", "true");
  });
});
