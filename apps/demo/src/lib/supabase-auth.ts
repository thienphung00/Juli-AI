/**
 * Supabase Auth (Google provider) for the "Đăng nhập với Google" door —
 * ADR-094 decision 3. Deliberately hand-rolled against the plain GoTrue REST
 * surface rather than the `@supabase/supabase-js` SDK: the only operation
 * this app needs is a browser redirect plus reading the implicit-grant hash
 * GoTrue appends on return, and `apps/demo`'s existing contract (#397,
 * `lib/analytics/api-client.ts`) is already "no client SDK, plain fetch".
 *
 * This is a real, distinct Supabase Auth identity (ADR-075 unweakened) — not
 * the withdrawn anonymous session from ADR-084 decision 1.
 */

export interface AuthSession {
  accessToken: string;
  refreshToken: string | null;
  expiresIn: number | null;
  tokenType: string;
}

type AuthCallbackResult =
  | { status: "success"; session: AuthSession }
  | { status: "error"; message: string; errorCode: string | null }
  | { status: "empty" };

export const AUTH_SESSION_STORAGE_KEY = "juli_demo_auth_session";

function readSupabaseConfig(): { url: string; anonKey: string } | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    return null;
  }

  return { url, anonKey };
}

/**
 * `dictionary.md` `auth.google.unavailable` (issue #1905) — the single
 * source for the honest-disabled-state copy. `DemoLanding`'s landing door
 * and `DemoShell`'s header control (issue #1907) both render this exact
 * sentence when `buildGoogleAuthorizeUrl` returns null; neither authors its
 * own second string.
 */
export const GOOGLE_SIGN_IN_UNAVAILABLE_COPY =
  "Đăng nhập với Google chưa sẵn sàng trong môi trường này.";

/**
 * Builds the Supabase GoTrue authorize URL for a full-page browser redirect.
 * Returns null (never a broken link) when the project URL/anon key are not
 * configured in this environment.
 */
export function buildGoogleAuthorizeUrl(redirectTo: string): string | null {
  const config = readSupabaseConfig();

  if (!config) {
    return null;
  }

  const authorizeUrl = new URL("/auth/v1/authorize", config.url);
  authorizeUrl.searchParams.set("provider", "google");
  authorizeUrl.searchParams.set("redirect_to", redirectTo);
  authorizeUrl.searchParams.set("apikey", config.anonKey);

  return authorizeUrl.toString();
}

/**
 * Parses the `#access_token=...` (or `#error=...`) hash fragment GoTrue's
 * implicit grant appends to `redirect_to` on return from Google — and, since
 * AC-9.1, from an email magic link, which lands the same way. Also accepts a
 * `?error=...` query string (GoTrue puts some verify failures there).
 */
export function parseAuthCallbackHash(hash: string): AuthCallbackResult {
  const trimmed = hash.startsWith("#") ? hash.slice(1) : hash;

  if (!trimmed) {
    return { status: "empty" };
  }

  const params = new URLSearchParams(trimmed);
  const error = params.get("error");

  if (error) {
    const description = params.get("error_description");
    return {
      status: "error",
      message: description ? decodeURIComponent(description.replace(/\+/g, " ")) : error,
      errorCode: params.get("error_code"),
    };
  }

  const accessToken = params.get("access_token");

  if (!accessToken) {
    return { status: "empty" };
  }

  const expiresInRaw = params.get("expires_in");

  return {
    status: "success",
    session: {
      accessToken,
      refreshToken: params.get("refresh_token"),
      expiresIn: expiresInRaw ? Number(expiresInRaw) : null,
      tokenType: params.get("token_type") ?? "bearer",
    },
  };
}

export function storeAuthSession(session: AuthSession): void {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.setItem(
    AUTH_SESSION_STORAGE_KEY,
    JSON.stringify(session),
  );
}

export function readAuthSession(): AuthSession | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.sessionStorage.getItem(AUTH_SESSION_STORAGE_KEY);

  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<AuthSession>;

    if (typeof parsed.accessToken !== "string") {
      return null;
    }

    return {
      accessToken: parsed.accessToken,
      refreshToken: parsed.refreshToken ?? null,
      expiresIn: parsed.expiresIn ?? null,
      tokenType: parsed.tokenType ?? "bearer",
    };
  } catch {
    return null;
  }
}

export function clearAuthSession(): void {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
}

/**
 * Decodes a JWT payload for **display only** (e.g. an email to greet the
 * seller with). This performs no signature verification and must never be
 * treated as proof of identity — that check happens server-side
 * (`verify_supabase_jwt`, ADR-075).
 */
export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split(".");

  if (parts.length !== 3) {
    return null;
  }

  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    const json =
      typeof atob === "function"
        ? atob(padded)
        : Buffer.from(padded, "base64").toString("utf8");

    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/* ------------------------------------------------------------------------ *
 * Email sign-in (AC-9.1) — Supabase Auth email OTP, beside the Google door.
 *
 * Same hand-rolled GoTrue REST surface as the Google door, same session
 * shape, same storage key: `POST /auth/v1/otp` emails a 6-digit code (and a
 * magic link to `/auth/callback`, which lands with the same implicit-grant
 * hash Google's redirect does), and `POST /auth/v1/verify` with
 * `type: "email"` exchanges the code for a session. Every signed-in page,
 * `/auth/connect-shop` and every bearer-authenticated `/v1` call then reads
 * it through `readAuthSession()` unchanged.
 *
 * Copy lives here (dictionary.md `auth.email.*`) so the landing door, the
 * `/auth/email` page and the magic-link callback cannot drift apart. No
 * message ever contains the code or a token.
 * ------------------------------------------------------------------------ */

export const EMAIL_SIGN_IN_LABEL = "Đăng nhập bằng email";

export const EMAIL_SIGN_IN_UNAVAILABLE_COPY =
  "Đăng nhập bằng email chưa sẵn sàng trong môi trường này.";

/** Seconds before "Gửi lại mã" re-enables (Supabase's own per-email floor is 60 s). */
export const EMAIL_OTP_RESEND_COOLDOWN_SECONDS = 60;

export type EmailOtpErrorKind =
  | "invalid_email"
  | "invalid_code"
  | "rate_limited"
  | "unavailable"
  | "network"
  | "unknown";

export type EmailOtpFailure = {
  ok: false;
  error: EmailOtpErrorKind;
  /** When GoTrue says how long to wait ("after 42 seconds"), that wait. */
  retryAfterSeconds?: number;
};

export type EmailOtpRequestResult = { ok: true } | EmailOtpFailure;
export type EmailOtpVerifyResult = { ok: true; session: AuthSession } | EmailOtpFailure;

export const EMAIL_OTP_ERROR_COPY: Readonly<Record<EmailOtpErrorKind, string>> = {
  invalid_email: "Email chưa đúng định dạng. Ví dụ: ten@shopcuaban.vn",
  invalid_code: "Mã không đúng hoặc đã hết hạn. Kiểm tra lại, hoặc gửi mã mới.",
  rate_limited: "Bạn đã yêu cầu quá nhiều lần. Vui lòng đợi một lát rồi thử lại.",
  unavailable: EMAIL_SIGN_IN_UNAVAILABLE_COPY,
  network: "Không kết nối được tới máy chủ đăng nhập. Kiểm tra mạng rồi thử lại.",
  unknown: "Đăng nhập bằng email không thành công. Vui lòng thử lại.",
};

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

/** A deliberately loose shape check — GoTrue has the final word. */
export function isValidEmail(email: string): boolean {
  const trimmed = email.trim();
  return trimmed.length <= 320 && EMAIL_PATTERN.test(trimmed);
}

/** Digits only — pasted codes often carry spaces or a dash. */
export function normaliseOtpCode(raw: string): string {
  return raw.replace(/\D/g, "");
}

export function isEmailSignInConfigured(): boolean {
  return readSupabaseConfig() !== null;
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

interface GoTrueErrorBody {
  code?: unknown;
  error_code?: unknown;
  error?: unknown;
  msg?: unknown;
  message?: unknown;
  error_description?: unknown;
}

const RATE_LIMIT_CODES = new Set([
  "over_email_send_rate_limit",
  "over_request_rate_limit",
  "over_sms_send_rate_limit",
]);
const INVALID_CODE_CODES = new Set(["otp_expired", "otp_invalid", "invalid_otp"]);
const INVALID_EMAIL_CODES = new Set(["email_address_invalid", "validation_failed"]);
const UNAVAILABLE_CODES = new Set([
  "otp_disabled",
  "email_provider_disabled",
  "signup_disabled",
  "email_address_not_authorized",
]);

function classifyGoTrueError(
  status: number,
  body: GoTrueErrorBody | null,
  stage: "request" | "verify",
): EmailOtpFailure {
  const code =
    typeof body?.error_code === "string"
      ? body.error_code
      : typeof body?.code === "string"
        ? body.code
        : typeof body?.error === "string"
          ? body.error
          : "";
  const message = [body?.msg, body?.message, body?.error_description]
    .filter((part): part is string => typeof part === "string")
    .join(" ");
  const wait = /(\d+)\s*seconds?/i.exec(message);
  const retryAfterSeconds = wait ? Number(wait[1]) : undefined;

  if (status === 429 || RATE_LIMIT_CODES.has(code)) {
    return { ok: false, error: "rate_limited", ...(retryAfterSeconds ? { retryAfterSeconds } : {}) };
  }
  if (UNAVAILABLE_CODES.has(code)) {
    return { ok: false, error: "unavailable" };
  }
  if (INVALID_CODE_CODES.has(code) || (stage === "verify" && (status === 401 || status === 403))) {
    return { ok: false, error: "invalid_code" };
  }
  if (INVALID_EMAIL_CODES.has(code) || (stage === "request" && (status === 400 || status === 422))) {
    return { ok: false, error: stage === "verify" ? "invalid_code" : "invalid_email" };
  }
  if (stage === "verify" && status === 400) {
    return { ok: false, error: "invalid_code" };
  }
  return { ok: false, error: "unknown" };
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

async function postGoTrue(
  path: string,
  body: Record<string, unknown>,
  fetchImpl: FetchLike,
  query?: Record<string, string>,
): Promise<Response | null> {
  const config = readSupabaseConfig();
  if (!config) return null;

  const url = new URL(path, config.url);
  for (const [key, value] of Object.entries(query ?? {})) {
    url.searchParams.set(key, value);
  }

  return fetchImpl(url.toString(), {
    method: "POST",
    headers: {
      apikey: config.anonKey,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

/**
 * Asks GoTrue to email a one-time code (and magic link) to `email`, creating
 * the Supabase user on first use. `redirectTo` is where the magic link lands
 * (`<origin>/auth/callback`); it must be in the project's Redirect URLs.
 */
export async function requestEmailOtp(
  email: string,
  redirectTo: string,
  fetchImpl: FetchLike = (input, init) => fetch(input, init),
): Promise<EmailOtpRequestResult> {
  const trimmed = email.trim();
  if (!isValidEmail(trimmed)) return { ok: false, error: "invalid_email" };

  let response: Response | null;
  try {
    response = await postGoTrue(
      "/auth/v1/otp",
      { email: trimmed, create_user: true },
      fetchImpl,
      { redirect_to: redirectTo },
    );
  } catch {
    return { ok: false, error: "network" };
  }

  if (!response) return { ok: false, error: "unavailable" };
  if (response.ok) return { ok: true };
  return classifyGoTrueError(response.status, (await readJson(response)) as GoTrueErrorBody | null, "request");
}

/**
 * Exchanges the emailed code for a session (`type: "email"` covers both a
 * first-time sign-up and a returning sign-in). The session has the same
 * shape the Google callback stores; the caller stores it.
 */
export async function verifyEmailOtp(
  email: string,
  code: string,
  fetchImpl: FetchLike = (input, init) => fetch(input, init),
): Promise<EmailOtpVerifyResult> {
  const trimmed = email.trim();
  const token = normaliseOtpCode(code);
  if (!isValidEmail(trimmed)) return { ok: false, error: "invalid_email" };
  if (token.length < 6) return { ok: false, error: "invalid_code" };

  let response: Response | null;
  try {
    response = await postGoTrue("/auth/v1/verify", { type: "email", email: trimmed, token }, fetchImpl);
  } catch {
    return { ok: false, error: "network" };
  }

  if (!response) return { ok: false, error: "unavailable" };

  const body = (await readJson(response)) as Record<string, unknown> | null;
  if (!response.ok) return classifyGoTrueError(response.status, body, "verify");

  const accessToken = body?.access_token;
  if (typeof accessToken !== "string" || !accessToken) {
    return { ok: false, error: "unknown" };
  }

  return {
    ok: true,
    session: {
      accessToken,
      refreshToken: typeof body?.refresh_token === "string" ? body.refresh_token : null,
      expiresIn: typeof body?.expires_in === "number" ? body.expires_in : null,
      tokenType: typeof body?.token_type === "string" ? body.token_type : "bearer",
    },
  };
}

/**
 * Vietnamese for a failed redirect into `/auth/callback` (Google or magic
 * link). GoTrue's `error_code=otp_expired` — an expired or already-used
 * magic link — gets its own sentence; anything else keeps the provider's
 * description, which never carries a token.
 */
export function describeAuthCallbackError(message: string, errorCode: string | null): string {
  if (errorCode && INVALID_CODE_CODES.has(errorCode)) {
    return "Liên kết đăng nhập đã hết hạn hoặc đã được dùng. Vui lòng gửi lại mã đăng nhập bằng email.";
  }
  return `Đăng nhập không thành công: ${message}`;
}
