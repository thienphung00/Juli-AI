import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ACCEPT_ERROR_TEXT,
  LIABILITY_CHECKBOX_LABEL,
  TERMS_UPDATED_TEXT,
  TermsAcceptanceStrip,
} from "../app-shell/terms-acceptance-strip";

function body(needs: boolean) {
  return {
    marketing_opt_out: false,
    ad_measurement_opt_out: false,
    case_study_opt_in: false,
    terms_date_accepted: needs ? null : "2026-10-18",
    terms_accepted_at: null,
    liability_clause_accepted_at: null,
    current_terms_date: "2026-10-18",
    needs_terms_acceptance: needs,
    deletion_scheduled_for: null,
  };
}

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

describe("TermsAcceptanceStrip (P50, D60.8)", () => {
  it("states the update date in plain copy, with no em dash", () => {
    expect(TERMS_UPDATED_TEXT).toBe("Điều khoản dịch vụ và Chính sách bảo mật đã cập nhật ngày 18/10/2026.");
    expect(TERMS_UPDATED_TEXT + LIABILITY_CHECKBOX_LABEL + ACCEPT_ERROR_TEXT).not.toContain("—");
  });

  it("shows nothing when the seller already accepted", async () => {
    const fetchImpl = vi.fn(async () => json(body(false)));
    render(<TermsAcceptanceStrip fetchImpl={fetchImpl} token="tok" />);
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("terms-acceptance-strip")).toBeNull();
  });

  it("shows nothing when the read fails: the app is never blocked", async () => {
    const fetchImpl = vi.fn(async () => json({}, 500));
    render(<TermsAcceptanceStrip fetchImpl={fetchImpl} token="tok" />);
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("terms-acceptance-strip")).toBeNull();
  });

  it("asks, links both pages, and gates Đồng ý on the separate Điều 11 checkbox", async () => {
    const user = userEvent.setup();
    const fetchImpl = vi.fn(async (_path: RequestInfo | URL, init?: RequestInit) =>
      init?.method === "POST" ? json(body(false)) : json(body(true)),
    );
    render(<TermsAcceptanceStrip fetchImpl={fetchImpl} token="tok" />);

    const strip = await screen.findByTestId("terms-acceptance-strip");
    expect(strip).toHaveTextContent(TERMS_UPDATED_TEXT);
    expect(screen.getByRole("link", { name: "Xem Điều khoản dịch vụ" })).toHaveAttribute(
      "href",
      "https://app-juli.com/terms",
    );
    expect(screen.getByRole("link", { name: "Xem Chính sách bảo mật" })).toHaveAttribute(
      "href",
      "https://app-juli.com/privacy",
    );
    const accept = screen.getByRole("button", { name: "Đồng ý" });
    expect(accept).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: LIABILITY_CHECKBOX_LABEL }));
    expect(accept).toBeEnabled();
    await user.click(accept);

    await waitFor(() => expect(screen.queryByTestId("terms-acceptance-strip")).toBeNull());
    const post = fetchImpl.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[0]).toBe("/v1/me/consents");
    expect(JSON.parse(post?.[1]?.body as string)).toEqual({ terms_date: "2026-10-18", liability_clause: true });
  });

  it("keeps the strip and says so when saving fails", async () => {
    const user = userEvent.setup();
    const fetchImpl = vi.fn(async (_path: RequestInfo | URL, init?: RequestInit) =>
      init?.method === "POST" ? json({ detail: "x" }, 409) : json(body(true)),
    );
    render(<TermsAcceptanceStrip fetchImpl={fetchImpl} token="tok" />);
    await user.click(await screen.findByRole("checkbox"));
    await user.click(screen.getByRole("button", { name: "Đồng ý" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(ACCEPT_ERROR_TEXT);
    expect(screen.getByTestId("terms-acceptance-strip")).toBeInTheDocument();
  });
});
