import { NOTICES, SIGNUP_PATH, SIGNUP_THANKS_PATH } from "./signup-content";

/**
 * Server side of `POST /dang-ky/gui` (route `src/app/dang-ky/gui/route.ts`):
 * the landing relays the form to the Juli API, `POST /v1/trial-signups`.
 * Same-origin for the browser, so no CORS; the API is called server to server.
 *
 * - JSON callers (the enhanced form) get the API's status and body back.
 * - Plain form posts (no JavaScript) get a 303: the thank-you page, or
 *   `/dang-ky#<notice>` whose `:target` notice explains what went wrong.
 * - The visitor's IP (nginx `X-Real-IP`) is forwarded as `X-Juli-Client-Ip`
 *   with the shared `TRIAL_SIGNUP_RELAY_KEY`, so the API's per-IP limit counts
 *   the visitor and not this server. Never logged here.
 *
 * Env (server only, never `NEXT_PUBLIC_*`): `TRIAL_SIGNUP_API_URL` (default
 * `https://api.app-juli.com`), `TRIAL_SIGNUP_RELAY_KEY`.
 */

const API_PATH = "/v1/trial-signups";
const DEFAULT_API_URL = "https://api.app-juli.com";
const TIMEOUT_MS = 10_000;
const MAX_BODY_BYTES = 16 * 1024;

const TEXT_FIELDS = ["full_name", "phone", "email", "shop", "role", "note", "website"] as const;
const SOURCE_KEYS = [
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_term",
  "utm_content",
  "referrer",
] as const;

interface RelayEnv {
  apiUrl?: string;
  relayKey?: string;
}

interface RelayDeps {
  fetchImpl?: typeof fetch;
  env?: RelayEnv;
  allowedOrigins: readonly string[];
}

type Body = Record<string, unknown>;

function pickText(source: Body | FormData, key: string): string | undefined {
  const value = source instanceof FormData ? source.get(key) : source[key];
  return typeof value === "string" ? value : undefined;
}

/** Only the fields the API knows, from a JSON body or a form post. */
export function toApiBody(source: Body | FormData): Body {
  const body: Body = {};
  for (const key of TEXT_FIELDS) {
    const value = pickText(source, key);
    if (value !== undefined) body[key] = value;
  }
  const consent = source instanceof FormData ? source.get("consent") : source.consent;
  body.consent = consent === true || consent === "true" || consent === "on";
  const nested = source instanceof FormData ? undefined : source.source;
  const src: Record<string, string> = {};
  for (const key of SOURCE_KEYS) {
    const value =
      nested && typeof nested === "object" ? (nested as Body)[key] : pickText(source, key);
    if (typeof value === "string" && value) src[key] = value.slice(0, 300);
  }
  if (Object.keys(src).length > 0) body.source = src;
  return body;
}

export function clientIp(headers: Headers): string | null {
  const real = headers.get("x-real-ip")?.trim();
  if (real) return real;
  const forwarded = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded || null;
}

function wantsJson(request: Request): boolean {
  return (request.headers.get("content-type") ?? "").includes("application/json");
}

function seeOther(location: string): Response {
  return new Response(null, { status: 303, headers: { Location: location, "Cache-Control": "no-store" } });
}

function json(status: number, body: unknown): Response {
  return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

function formAnswer(status: number): Response {
  if (status === 201 || status === 200) return seeOther(SIGNUP_THANKS_PATH);
  if (status === 422) return seeOther(`${SIGNUP_PATH}#${NOTICES.invalid.id}`);
  if (status === 429) return seeOther(`${SIGNUP_PATH}#${NOTICES.rateLimited.id}`);
  return seeOther(`${SIGNUP_PATH}#${NOTICES.failed.id}`);
}

export async function relaySignup(request: Request, deps: RelayDeps): Promise<Response> {
  const asJson = wantsJson(request);
  const fail = (status: number, detail: string) => (asJson ? json(status, { detail }) : formAnswer(status));

  // Same-site only: a page on another origin may not post sign-ups through us.
  const origin = request.headers.get("origin");
  if (origin && !deps.allowedOrigins.includes(origin)) return fail(403, "forbidden_origin");

  const length = Number(request.headers.get("content-length") ?? "0");
  if (length > MAX_BODY_BYTES) return fail(413, "too_large");

  let parsed: Body | FormData;
  try {
    parsed = asJson ? ((await request.json()) as Body) : await request.formData();
  } catch {
    return fail(400, "invalid_body");
  }
  if (!(parsed instanceof FormData) && (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))) {
    return fail(400, "invalid_body");
  }

  const env = deps.env ?? {};
  const base = (env.apiUrl || DEFAULT_API_URL).replace(/\/$/, "");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  const ip = clientIp(request.headers);
  if (env.relayKey && ip) {
    headers["X-Juli-Relay-Key"] = env.relayKey;
    headers["X-Juli-Client-Ip"] = ip;
  }

  let upstream: Response;
  try {
    upstream = await (deps.fetchImpl ?? fetch)(`${base}${API_PATH}`, {
      method: "POST",
      headers,
      body: JSON.stringify(toApiBody(parsed)),
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    console.error("trial_signup_relay_unreachable");
    return fail(502, "unavailable");
  }
  if (upstream.status >= 500) console.error("trial_signup_relay_upstream", upstream.status);
  if (!asJson) return formAnswer(upstream.status);
  const payload: unknown = await upstream.json().catch(() => ({ detail: "unavailable" }));
  const status = upstream.status >= 500 ? 502 : upstream.status;
  return json(status, payload);
}
