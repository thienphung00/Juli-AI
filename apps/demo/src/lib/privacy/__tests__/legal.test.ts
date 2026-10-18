import { describe, expect, it, vi } from "vitest";

import {
  LEGAL_TERMS_DATE,
  PrivacyApiError,
  acceptTerms,
  cancelDeletion,
  exportFilename,
  fetchExport,
  fetchPrivacy,
  requestDeletion,
  updatePrivacy,
  viDate,
  type PrivacyState,
} from "../legal";

const STATE: PrivacyState = {
  marketing_opt_out: false,
  ad_measurement_opt_out: false,
  case_study_opt_in: false,
  terms_date_accepted: null,
  terms_accepted_at: null,
  liability_clause_accepted_at: null,
  current_terms_date: "2026-10-18",
  needs_terms_acceptance: true,
  deletion_scheduled_for: null,
};

function ok(body: unknown = STATE, headers: Record<string, string> = {}) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers }));
}

function call(fetchImpl: ReturnType<typeof vi.fn>) {
  const [path, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
  return { path, init, headers: init.headers as Record<string, string> };
}

describe("LEGAL_TERMS_DATE", () => {
  it("is the date of the D60 legal text, the same value the backend pins", () => {
    expect(LEGAL_TERMS_DATE).toBe("2026-10-18");
  });
});

describe("privacy API client (contract p50-privacy.md)", () => {
  it("GET /v1/me/privacy with the seller's bearer token", async () => {
    const fetchImpl = ok();
    await expect(fetchPrivacy("tok", fetchImpl)).resolves.toEqual(STATE);
    const { path, init, headers } = call(fetchImpl);
    expect(path).toBe("/v1/me/privacy");
    expect(init.method).toBe("GET");
    expect(headers.Authorization).toBe("Bearer tok");
    expect(headers["X-Shop-Id"]).toBeUndefined();
  });

  it("accepts a { data } envelope too", async () => {
    await expect(fetchPrivacy("tok", ok({ data: STATE }))).resolves.toEqual(STATE);
  });

  it("PATCH sends only the changed preference", async () => {
    const fetchImpl = ok();
    await updatePrivacy("tok", { marketing_opt_out: true }, fetchImpl);
    const { path, init, headers } = call(fetchImpl);
    expect(path).toBe("/v1/me/privacy");
    expect(init.method).toBe("PATCH");
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ marketing_opt_out: true });
  });

  it("POST /v1/me/consents with the current terms date and the separate liability clause", async () => {
    const fetchImpl = ok();
    await acceptTerms("tok", fetchImpl);
    const { path, init } = call(fetchImpl);
    expect(path).toBe("/v1/me/consents");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ terms_date: "2026-10-18", liability_clause: true });
  });

  it("POST and DELETE /v1/me/deletion", async () => {
    const post = ok();
    await requestDeletion("tok", post);
    expect(call(post)).toMatchObject({ path: "/v1/me/deletion", init: { method: "POST" } });
    const del = ok();
    await cancelDeletion("tok", del);
    expect(call(del)).toMatchObject({ path: "/v1/me/deletion", init: { method: "DELETE" } });
  });

  it("throws a typed error with the status and detail", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ detail: "stale terms" }), { status: 409 }));
    const error = await acceptTerms("tok", fetchImpl).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(PrivacyApiError);
    expect(error).toMatchObject({ status: 409, message: "stale terms" });
  });

  it("GET /v1/me/export returns the file and the server's filename", async () => {
    const fetchImpl = ok(
      { user: {} },
      { "Content-Disposition": 'attachment; filename="juli-du-lieu-2026-10-18.json"' },
    );
    const file = await fetchExport("tok", fetchImpl);
    expect(call(fetchImpl).path).toBe("/v1/me/export");
    expect(file.filename).toBe("juli-du-lieu-2026-10-18.json");
    expect(file.blob.size).toBe(11);
  });
});

describe("exportFilename", () => {
  it("falls back to a dated name", () => {
    expect(exportFilename(null, new Date("2026-10-18T05:00:00Z"))).toBe("juli-du-lieu-2026-10-18.json");
  });
});

describe("viDate", () => {
  it("writes a date as dd/mm/yyyy", () => {
    expect(viDate("2026-10-18")).toBe("18/10/2026");
  });

  it("reads a datetime on the Vietnam calendar", () => {
    expect(viDate("2026-11-17T20:00:00Z")).toBe("18/11/2026");
  });
});
