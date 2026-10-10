/**
 * Signed-in client of the P15 content analysis (`p15-content-analysis.md`):
 * bearer + `X-Shop-Id`, same-origin relative paths (#397). The upload is
 * chunked (≤ the slot's `chunk_bytes`, 32 MB — under Cloudflare's request
 * limit) and resumes at `expected_offset` after a 409. Never imported by the
 * anonymous path (the sample door uses `sample.ts`).
 */

import { QdApiError, type AuthedOptions } from "../quyet-dinh/client-types";
import { contentTypeOf, type AnalysisTarget, type ContentAnalysis, type ContentAnalysisClients } from "./types";

const BASE = "/v1/demo/content-analysis";
const MAX_RETRIES_PER_CHUNK = 3;

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let code: string | null = null;
    let message: string | null = null;
    let raw: unknown = null;
    try {
      raw = await response.json();
      const detail = (raw as { detail?: unknown }).detail;
      if (detail && typeof detail === "object") {
        const d = detail as { code?: unknown; message?: unknown };
        code = typeof d.code === "string" ? d.code : null;
        message = typeof d.message === "string" ? d.message : null;
      }
    } catch {
      // status only
    }
    throw new QdApiError(response.status, code, message, raw);
  }
  return (await response.json()) as T;
}

function headers(auth: AuthedOptions, extra: Record<string, string> = {}): Record<string, string> {
  return { Accept: "application/json", Authorization: `Bearer ${auth.token}`, "X-Shop-Id": auth.shopId, ...extra };
}

export async function listAnalyses(auth: AuthedOptions, target: AnalysisTarget): Promise<readonly ContentAnalysis[]> {
  const params = new URLSearchParams();
  if (target.productId) params.set("tiktok_product_id", target.productId);
  if (target.contentRef) params.set("content_ref", target.contentRef);
  if (target.runId) params.set("run_id", target.runId);
  const fetchImpl = auth.fetchImpl ?? fetch;
  const body = await parse<{ data: ContentAnalysis[] }>(
    await fetchImpl(`${BASE}?${params.toString()}`, { headers: headers(auth), cache: "no-store" }),
  );
  return body.data.filter((a) => a.kind === target.kind);
}

export async function getAnalysis(auth: AuthedOptions, id: string): Promise<ContentAnalysis> {
  const fetchImpl = auth.fetchImpl ?? fetch;
  const body = await parse<{ data: ContentAnalysis }>(
    await fetchImpl(`${BASE}/${encodeURIComponent(id)}`, { headers: headers(auth), cache: "no-store" }),
  );
  return body.data;
}

interface Slot {
  readonly analysis: ContentAnalysis;
  readonly upload: { readonly url: string; readonly token: string; readonly chunk_bytes: number; readonly expires_at: string };
}

export async function uploadVideo(
  auth: AuthedOptions,
  target: AnalysisTarget,
  file: File,
  onProgress?: (fraction: number) => void,
): Promise<ContentAnalysis> {
  const fetchImpl = auth.fetchImpl ?? fetch;
  const slot = (
    await parse<{ data: Slot }>(
      await fetchImpl(BASE, {
        method: "POST",
        headers: headers(auth, { "Content-Type": "application/json" }),
        body: JSON.stringify({
          kind: target.kind,
          content_ref: target.contentRef ?? null,
          tiktok_product_id: target.productId ?? null,
          run_id: target.runId ?? null,
          file_name: file.name,
          content_type: contentTypeOf(file),
          size_bytes: file.size,
        }),
      }),
    )
  ).data;
  const { url, token, chunk_bytes: chunk } = slot.upload;
  let offset = 0;
  let latest = slot.analysis;
  let retries = 0;
  onProgress?.(0);
  while (offset < file.size) {
    const piece = file.slice(offset, Math.min(file.size, offset + chunk));
    try {
      const body = await parse<{ data: ContentAnalysis }>(
        await fetchImpl(`${url}?offset=${offset}&token=${encodeURIComponent(token)}`, {
          method: "PUT",
          headers: headers(auth, { "Content-Type": "application/octet-stream" }),
          body: piece,
        }),
      );
      latest = body.data;
      offset = latest.upload.received_bytes;
      retries = 0;
      onProgress?.(offset / file.size);
    } catch (error) {
      const expected = (error as QdApiError).body as { detail?: { expected_offset?: unknown } } | null;
      const resumeAt = expected?.detail?.expected_offset;
      if (error instanceof QdApiError && error.code === "offset_mismatch" && typeof resumeAt === "number" && retries < MAX_RETRIES_PER_CHUNK) {
        retries += 1;
        offset = resumeAt;
        continue;
      }
      const transient = !(error instanceof QdApiError) || error.status >= 500;
      if (transient && retries < MAX_RETRIES_PER_CHUNK) {
        retries += 1;
        continue;
      }
      throw error;
    }
  }
  return latest;
}

export function createAnalysisClients(auth: AuthedOptions): ContentAnalysisClients {
  return {
    sample: false,
    list: (target) => listAnalyses(auth, target),
    get: (id) => getAnalysis(auth, id),
    upload: (target, file, onProgress) => uploadVideo(auth, target, file, onProgress),
  };
}
