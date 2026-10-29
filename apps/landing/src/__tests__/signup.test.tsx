import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SignupThanksPage, { metadata as thanksMetadata } from "../app/dang-ky/cam-on/page";
import SignupPage, { metadata as signupMetadata } from "../app/dang-ky/page";
import sitemap from "../app/sitemap";
import { SignupConversion, SIGNUP_CONVERSION } from "../components/signup/signup-conversion";
import {
  NEXT_STEPS,
  NOTICES,
  SELF_CONNECT_URL,
  SIGNUP_DONE_FLAG,
  SIGNUP_H1,
  SIGNUP_THANKS_PATH,
} from "../components/signup/signup-content";
import { SignupForm } from "../components/signup/signup-form";
import { clientIp, relaySignup, toApiBody } from "../components/signup/signup-relay";
import { MESSAGES, normalizePhone, PHONE_PATTERN, validateSignup } from "../components/signup/validate";
import { CONSENT_STORAGE_KEY } from "../lib/consent";
import { absoluteUrl, getRoute } from "../lib/seo";

/** P33-F (D43, AC-33.11): /dang-ky, its form, the relay route and /dang-ky/cam-on. */

const tracked = vi.hoisted(() => ({ load: vi.fn(), track: vi.fn() }));
vi.mock("@juli/tiktok-events", () => ({
  loadTikTokPixel: tracked.load,
  trackTikTokEvent: tracked.track,
  TikTokEvents: { completeRegistration: "CompleteRegistration" },
}));

beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  tracked.load.mockReset();
  tracked.track.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function fillValid(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/Họ và tên/), "Nguyễn Thị Lan");
  await user.type(screen.getByLabelText(/Số điện thoại \/ Zalo/), "0912 345 678");
  await user.type(screen.getByLabelText(/^Email/), "Lan@Example.vn");
  await user.type(screen.getByLabelText(/Tên hoặc link shop TikTok/), "tiktok.com/@lanshop");
  await user.click(screen.getByLabelText("Nhà bán"));
  await user.click(screen.getByLabelText(/Tôi đồng ý với/));
}

describe("/dang-ky page", () => {
  it("has one H1, the 'Sau khi bạn đăng ký' steps and shot, and every field labelled", () => {
    render(<SignupPage />);
    const main = screen.getByRole("main");
    const h1s = within(main).getAllByRole("heading", { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(SIGNUP_H1);
    expect(main).toHaveTextContent("Miễn phí 3 tháng · không cần thẻ thanh toán");
    // Signup.dc.html (P34-E): the aside replaces P33-F's value list.
    const aside = screen.getByRole("complementary", { name: "Sau khi bạn đăng ký" });
    const steps = within(aside).getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(steps).toEqual(NEXT_STEPS.map((step) => step.title));
    expect(within(aside).getByRole("img")).toHaveAccessibleName(/\(dữ liệu mẫu\)$/);
    expect(aside).toHaveTextContent("Dữ liệu mẫu");
    expect(screen.getByTestId("signup-self-connect-link")).toHaveAttribute("href", SELF_CONNECT_URL);
    expect(screen.getByTestId("signup-submit").tagName).toBe("BUTTON");
    for (const label of [/Họ và tên/, /Số điện thoại \/ Zalo/, /^Email/, /Tên hoặc link shop TikTok/, /Ghi chú/]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    const roles = screen.getByRole("group", { name: /Bạn là/ });
    for (const role of ["Nhà bán", "Affiliate", "Đội vận hành sàn", "Agency"]) {
      expect(within(roles).getByLabelText(role)).toHaveAttribute("type", "radio");
    }
  });

  it("works without JavaScript: a POST form with browser validation", () => {
    render(<SignupForm />);
    const form = screen.getByTestId("signup-form");
    expect(form).toHaveAttribute("action", "/dang-ky/gui");
    expect(form).toHaveAttribute("method", "post");
    expect(screen.getByLabelText(/Họ và tên/)).toBeRequired();
    expect(screen.getByLabelText(/Số điện thoại/)).toHaveAttribute("pattern", PHONE_PATTERN);
    expect(screen.getByLabelText(/^Email/)).toHaveAttribute("type", "email");
    expect(screen.getByLabelText(/Tôi đồng ý với/)).toBeRequired();
    // the no-JS answers exist as :target notices
    for (const notice of Object.values(NOTICES)) {
      expect(document.getElementById(notice.id)).toHaveTextContent(notice.text);
    }
  });

  it("the consent links to /terms and /privacy; the honeypot is hidden", () => {
    render(<SignupForm />);
    const consent = screen.getByText(/Tôi đồng ý với/);
    const hrefs = within(consent).getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/terms", "/privacy#dang-ky-dung-thu"]);
    const honeypot = document.querySelector('input[name="website"]');
    expect(honeypot).toHaveAttribute("tabindex", "-1");
    expect(honeypot?.closest('[aria-hidden="true"]')).not.toBeNull();
  });

  it("is registered, indexable and in the sitemap", () => {
    expect(getRoute("/dang-ky").noindex).toBeFalsy();
    expect(signupMetadata.robots).toBeUndefined();
    expect(signupMetadata.alternates?.canonical).toBe(absoluteUrl("/dang-ky"));
    expect(sitemap().map((e) => e.url)).toContain(absoluteUrl("/dang-ky"));
  });
});

describe("validation (twin of the API's)", () => {
  it.each([
    ["0912345678", "0912345678"],
    ["0912 345 678", "0912345678"],
    ["+84 912 345 678", "0912345678"],
    ["84912345678", "0912345678"],
    ["(+84) 386-123-456", "0386123456"],
    ["0123456789", null],
    ["0212345678", null],
    ["091234567", null],
  ])("normalizePhone(%s) = %s", (raw, expected) => {
    expect(normalizePhone(raw)).toBe(expected);
  });

  it("the no-JS pattern accepts what the server accepts", () => {
    const re = new RegExp(`^(?:${PHONE_PATTERN})$`, "v");
    for (const ok of ["0912345678", "0912 345 678", "+84 912 345 678", "(+84) 386-123-456"]) {
      expect(re.test(ok), ok).toBe(true);
    }
    for (const bad of ["0212345678", "12345", "0912"]) expect(re.test(bad), bad).toBe(false);
  });

  it("returns one Vietnamese message per invalid field", () => {
    const errors = validateSignup({
      full_name: "",
      phone: "1",
      email: "x",
      shop: "",
      role: "",
      note: "",
      consent: false,
      website: "",
    });
    expect(errors).toEqual({
      full_name: MESSAGES.full_name,
      phone: MESSAGES.phone,
      email: MESSAGES.email,
      shop: MESSAGES.shop,
      role: MESSAGES.role,
      consent: MESSAGES.consent,
    });
  });
});

describe("the enhanced form", () => {
  it("shows inline errors, focuses the first invalid field and sends nothing", async () => {
    const fetchImpl = vi.fn();
    const user = userEvent.setup();
    render(<SignupForm fetchImpl={fetchImpl as unknown as typeof fetch} />);
    await user.type(screen.getByLabelText(/Họ và tên/), "Lan");
    await user.type(screen.getByLabelText(/Số điện thoại/), "12345");
    await user.click(screen.getByTestId("signup-submit"));
    const phone = screen.getByLabelText(/Số điện thoại/);
    expect(phone).toHaveAttribute("aria-invalid", "true");
    expect(phone).toHaveFocus();
    expect(phone.getAttribute("aria-describedby")).toContain("phone-error");
    expect(screen.getByText(MESSAGES.phone)).toBeInTheDocument();
    expect(screen.getByText(MESSAGES.consent)).toBeInTheDocument();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("posts JSON to /dang-ky/gui, flags the conversion and goes to the thank-you page", async () => {
    const fetchImpl = vi.fn(async () => Response.json({ ok: true }, { status: 201 }));
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<SignupForm fetchImpl={fetchImpl as unknown as typeof fetch} onDone={onDone} />);
    await fillValid(user);
    await user.click(screen.getByTestId("signup-submit"));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(SIGNUP_THANKS_PATH));
    const [path, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe("/dang-ky/gui");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body).toMatchObject({
      full_name: "Nguyễn Thị Lan",
      phone: "0912 345 678",
      email: "Lan@Example.vn",
      shop: "tiktok.com/@lanshop",
      role: "seller",
      consent: true,
      website: "",
    });
    expect(window.sessionStorage.getItem(SIGNUP_DONE_FLAG)).toBe("1");
  });

  it("shows the server's field errors (422) and the rate-limit notice (429)", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ detail: "invalid", errors: { email: MESSAGES.email } }, { status: 422 }),
      )
      .mockResolvedValueOnce(Response.json({ detail: "x" }, { status: 429 }))
      .mockRejectedValueOnce(new Error("offline"));
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<SignupForm fetchImpl={fetchImpl as unknown as typeof fetch} onDone={onDone} />);
    await fillValid(user);
    await user.click(screen.getByTestId("signup-submit"));
    expect(await screen.findByText(MESSAGES.email)).toBeInTheDocument();
    expect(screen.getByTestId("signup-notice")).toHaveTextContent(NOTICES.invalid.text);
    await user.click(screen.getByTestId("signup-submit"));
    await waitFor(() =>
      expect(screen.getByTestId("signup-notice")).toHaveTextContent(NOTICES.rateLimited.text),
    );
    await user.click(screen.getByTestId("signup-submit"));
    await waitFor(() =>
      expect(screen.getByTestId("signup-notice")).toHaveTextContent(NOTICES.failed.text),
    );
    expect(onDone).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(SIGNUP_DONE_FLAG)).toBeNull();
  });
});

describe("POST /dang-ky/gui relay", () => {
  const ORIGINS = ["https://app-juli.com"];
  const API_OK = () => Response.json({ ok: true }, { status: 201 });

  function formRequest(fields: Record<string, string>, headers: Record<string, string> = {}) {
    const body = new URLSearchParams(fields);
    return new Request("https://app-juli.com/dang-ky/gui", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", ...headers },
      body,
    });
  }

  it("relays a JSON post with the relay key and the visitor's IP", async () => {
    const fetchImpl = vi.fn(async () => API_OK());
    const request = new Request("https://app-juli.com/dang-ky/gui", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "https://app-juli.com",
        "x-real-ip": "203.0.113.7",
      },
      body: JSON.stringify({ full_name: "Lan", consent: true, extra: "dropped", source: { utm_source: "tt" } }),
    });
    const response = await relaySignup(request, {
      allowedOrigins: ORIGINS,
      fetchImpl: fetchImpl as unknown as typeof fetch,
      env: { apiUrl: "https://api.example/", relayKey: "k" },
    });
    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ ok: true });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example/v1/trial-signups");
    expect(init.headers).toMatchObject({ "X-Juli-Relay-Key": "k", "X-Juli-Client-Ip": "203.0.113.7" });
    expect(JSON.parse(String(init.body))).toEqual({
      full_name: "Lan",
      consent: true,
      source: { utm_source: "tt" },
    });
  });

  it("without a relay key it forwards no IP header", async () => {
    const fetchImpl = vi.fn(async () => API_OK());
    await relaySignup(formRequest({ full_name: "Lan" }, { "x-real-ip": "203.0.113.7" }), {
      allowedOrigins: ORIGINS,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.app-juli.com/v1/trial-signups");
    expect(init.headers).not.toHaveProperty("X-Juli-Client-Ip");
  });

  it.each([
    [201, SIGNUP_THANKS_PATH],
    [422, `/dang-ky#${NOTICES.invalid.id}`],
    [429, `/dang-ky#${NOTICES.rateLimited.id}`],
    [500, `/dang-ky#${NOTICES.failed.id}`],
  ])("a no-JS form post answered %s redirects (303) to %s", async (status, location) => {
    const fetchImpl = vi.fn(async () => Response.json({}, { status }));
    const response = await relaySignup(formRequest({ full_name: "Lan", consent: "true" }), {
      allowedOrigins: ORIGINS,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(location);
  });

  it("an unreachable API is 502 (JSON) or the failure notice (form)", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const fetchImpl = vi.fn(async () => {
      throw new Error("down");
    });
    const asJson = await relaySignup(
      new Request("https://app-juli.com/dang-ky/gui", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
      }),
      { allowedOrigins: ORIGINS, fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(asJson.status).toBe(502);
    const asForm = await relaySignup(formRequest({}), {
      allowedOrigins: ORIGINS,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(asForm.headers.get("location")).toBe(`/dang-ky#${NOTICES.failed.id}`);
  });

  it("refuses another site's origin and never calls the API", async () => {
    const fetchImpl = vi.fn();
    const response = await relaySignup(
      formRequest({ full_name: "x" }, { origin: "https://evil.example" }),
      { allowedOrigins: ORIGINS, fetchImpl: fetchImpl as unknown as typeof fetch },
    );
    expect(response.status).toBe(303);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("maps form fields (checkbox 'true', honeypot) and reads the client IP", () => {
    const form = new FormData();
    form.set("full_name", "Lan");
    form.set("consent", "true");
    form.set("website", "");
    form.set("utm_source", "tiktok");
    expect(toApiBody(form)).toEqual({ full_name: "Lan", consent: true, website: "", source: { utm_source: "tiktok" } });
    expect(clientIp(new Headers({ "x-forwarded-for": "198.51.100.2, 10.0.0.1" }))).toBe("198.51.100.2");
    expect(clientIp(new Headers())).toBeNull();
  });
});

describe("/dang-ky/cam-on", () => {
  it("says the team will call and offers 'Tự kết nối shop ngay' to the demo trial door", () => {
    render(<SignupThanksPage />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("main")).toHaveTextContent(/Đội ngũ Juli sẽ liên hệ/);
    expect(screen.getByRole("main")).toHaveTextContent(/kết nối shop/);
    const cta = screen.getByTestId("self-connect-cta");
    expect(cta).toHaveTextContent("Tự kết nối shop ngay");
    expect(cta).toHaveAttribute("href", SELF_CONNECT_URL);
    expect(SELF_CONNECT_URL).toBe("https://app.app-juli.com/?dang-ky=dung-thu");
  });

  it("is a calm confirmation: bird mark and the same 3 next steps", () => {
    render(<SignupThanksPage />);
    const main = screen.getByRole("main");
    expect(main.querySelector("img.ui-bird")).not.toBeNull();
    expect(within(main).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(
      NEXT_STEPS.map((step) => step.title),
    );
  });

  it("is noindex and kept out of the sitemap", () => {
    expect(thanksMetadata.robots).toEqual({ index: false, follow: true });
    expect(sitemap().map((e) => e.url)).not.toContain(absoluteUrl("/dang-ky/cam-on"));
  });
});

describe("CompleteRegistration (consent-gated)", () => {
  async function mountConversion() {
    await act(async () => {
      render(<SignupConversion />);
    });
    // the pixel package is imported lazily
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }

  it("fires once after a real sign-up when analytics consent is granted", async () => {
    window.localStorage.setItem(CONSENT_STORAGE_KEY, "granted");
    window.sessionStorage.setItem(SIGNUP_DONE_FLAG, "1");
    await mountConversion();
    expect(tracked.load).toHaveBeenCalledTimes(1);
    expect(tracked.track).toHaveBeenCalledWith("CompleteRegistration", SIGNUP_CONVERSION);
    expect(window.sessionStorage.getItem(SIGNUP_DONE_FLAG)).toBeNull();
  });

  it.each([
    ["no consent choice", null, "1"],
    ["consent refused", "denied", "1"],
    ["a reload / direct visit (no flag)", "granted", null],
  ])("does nothing with %s", async (_label, consent, flag) => {
    if (consent) window.localStorage.setItem(CONSENT_STORAGE_KEY, consent);
    if (flag) window.sessionStorage.setItem(SIGNUP_DONE_FLAG, flag);
    await mountConversion();
    expect(tracked.load).not.toHaveBeenCalled();
    expect(tracked.track).not.toHaveBeenCalled();
  });
});
