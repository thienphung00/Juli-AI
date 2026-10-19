/**
 * P50 (D68): the seller's privacy rights and terms acceptance, against the
 * contract in `fasttrack/contracts/p50-privacy.md`.
 *
 * Same-origin relative paths with the Supabase bearer token, matching
 * `tiktok-connect-client.ts` and `shops-client.ts` (#397: no client-side API
 * base env var; the demo vhost proxies `/v1/`). Scoped by the signed-in user,
 * so no `X-Shop-Id`.
 */

import { PRIVACY_POLICY_URL, TERMS_OF_SERVICE_URL } from "../../components/legal-consent-note";

export { PRIVACY_POLICY_URL, TERMS_OF_SERVICE_URL };

/** The date of the D68 `/terms` + `/privacy` text. Bump together with the backend's `terms.py`. */
export const LEGAL_TERMS_DATE = "2026-10-18" as const;

export const PRIVACY_PATH = "/v1/me/privacy" as const;
export const CONSENTS_PATH = "/v1/me/consents" as const;
export const EXPORT_PATH = "/v1/me/export" as const;
export const DELETION_PATH = "/v1/me/deletion" as const;

export const PRIVACY_CONTACT_EMAIL = "lienhe@app-juli.com";

export interface PrivacyState {
  readonly marketing_opt_out: boolean;
  readonly ad_measurement_opt_out: boolean;
  readonly case_study_opt_in: boolean;
  readonly terms_date_accepted: string | null;
  readonly terms_accepted_at: string | null;
  readonly liability_clause_accepted_at: string | null;
  readonly current_terms_date: string;
  readonly needs_terms_acceptance: boolean;
  readonly deletion_scheduled_for: string | null;
}

export type PrivacyPreferenceKey = "marketing_opt_out" | "ad_measurement_opt_out" | "case_study_opt_in";
export type PrivacyPreferencePatch = Partial<Record<PrivacyPreferenceKey, boolean>>;

export class PrivacyApiError extends Error {
  constructor(
    public readonly status: number,
    detail?: string,
  ) {
    super(detail ?? `Privacy request failed (${status})`);
    this.name = "PrivacyApiError";
  }
}

async function failure(response: Response): Promise<PrivacyApiError> {
  let detail: string | undefined;
  try {
    const body = (await response.json()) as { detail?: unknown };
    detail = typeof body.detail === "string" ? body.detail : undefined;
  } catch {
    detail = undefined;
  }
  return new PrivacyApiError(response.status, detail);
}

/** The contract returns the body bare; accept a `{ data }` envelope too, as other `/v1` routes use one. */
async function readState(response: Response): Promise<PrivacyState> {
  const body = (await response.json()) as PrivacyState | { data: PrivacyState };
  return "data" in body && body.data && typeof body.data === "object" ? body.data : (body as PrivacyState);
}

async function send(
  path: string,
  accessToken: string,
  fetchImpl: typeof fetch,
  method: "GET" | "PATCH" | "POST" | "DELETE",
  body?: unknown,
): Promise<Response> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    Authorization: `Bearer ${accessToken}`,
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetchImpl(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!response.ok) throw await failure(response);
  return response;
}

export async function fetchPrivacy(accessToken: string, fetchImpl: typeof fetch = fetch): Promise<PrivacyState> {
  return readState(await send(PRIVACY_PATH, accessToken, fetchImpl, "GET"));
}

export async function updatePrivacy(
  accessToken: string,
  patch: PrivacyPreferencePatch,
  fetchImpl: typeof fetch = fetch,
): Promise<PrivacyState> {
  return readState(await send(PRIVACY_PATH, accessToken, fetchImpl, "PATCH", patch));
}

/** Accepts the current terms and, separately, Điều 11 (D68.4). */
export async function acceptTerms(accessToken: string, fetchImpl: typeof fetch = fetch): Promise<PrivacyState> {
  return readState(
    await send(CONSENTS_PATH, accessToken, fetchImpl, "POST", { terms_date: LEGAL_TERMS_DATE, liability_clause: true }),
  );
}

export async function requestDeletion(accessToken: string, fetchImpl: typeof fetch = fetch): Promise<PrivacyState> {
  return readState(await send(DELETION_PATH, accessToken, fetchImpl, "POST"));
}

export async function cancelDeletion(accessToken: string, fetchImpl: typeof fetch = fetch): Promise<PrivacyState> {
  return readState(await send(DELETION_PATH, accessToken, fetchImpl, "DELETE"));
}

/** `juli-du-lieu-2026-10-18.json` from the response, or a dated fallback. */
export function exportFilename(contentDisposition: string | null, today: Date = new Date()): string {
  const match = contentDisposition ? /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(contentDisposition) : null;
  if (match?.[1]) return decodeURIComponent(match[1]);
  return `juli-du-lieu-${today.toISOString().slice(0, 10)}.json`;
}

export interface ExportFile {
  readonly blob: Blob;
  readonly filename: string;
}

/** `GET /v1/me/export`: the file and its name; the caller saves it. */
export async function fetchExport(accessToken: string, fetchImpl: typeof fetch = fetch): Promise<ExportFile> {
  const response = await send(EXPORT_PATH, accessToken, fetchImpl, "GET");
  return { blob: await response.blob(), filename: exportFilename(response.headers.get("Content-Disposition")) };
}

/** Saves a fetched file through a temporary object URL (a bearer token cannot ride a plain link). */
export function saveFile({ blob, filename }: ExportFile): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

const VN_DATE = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Ho_Chi_Minh",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

/** "18/10/2026": a date as written, a datetime on the Vietnam calendar. */
export function viDate(iso: string): string {
  if (iso.length > 10) {
    const instant = new Date(iso);
    if (!Number.isNaN(instant.getTime())) return VN_DATE.format(instant);
  }
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}
