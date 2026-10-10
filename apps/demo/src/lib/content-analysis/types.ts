/**
 * P15 content analysis — network-free CONTRACT (`fasttrack/contracts/p15-content-analysis.md`).
 *
 * Shapes of `GET/POST /v1/demo/content-analysis`, the client interface the
 * "Phân tích video" block talks to, and the pure client-side checks. Two
 * implementations: `api-client.ts` (signed in, real upload) and `sample.ts`
 * (signed out / no shop: a canned analysis, no network).
 */

export type AnalysisKind = "video" | "live";
export type AnalysisStatus = "awaiting_upload" | "queued" | "processing" | "done" | "failed" | "refused" | "expired";

export interface AnalysisIssue {
  readonly code: string;
  readonly text: string;
}

export interface AnalysisResult {
  readonly kind: AnalysisKind;
  readonly analysed_s: number;
  readonly hook: { readonly verdict: "strong" | "ok" | "weak" | null; readonly label: string; readonly from_s: number; readonly to_s: number; readonly reason: string | null };
  readonly product_first_s: number | null;
  readonly product_line: string;
  readonly cta: { readonly present: boolean; readonly at_s: number | null; readonly text: string | null; readonly line: string };
  readonly pacing: { readonly cuts: number; readonly cuts_per_10s: number | null; readonly line: string };
  readonly issues: readonly AnalysisIssue[];
  readonly suggestions: readonly string[];
  readonly windows: readonly { readonly from_s: number; readonly to_s: number; readonly mention_s: number; readonly source: string }[];
}

export interface ContentAnalysis {
  readonly id: string;
  readonly kind: AnalysisKind;
  readonly content_ref: string | null;
  readonly tiktok_product_id: string | null;
  readonly run_id: string | null;
  readonly file_name: string;
  readonly status: AnalysisStatus;
  readonly status_label: string;
  readonly upload: { readonly received_bytes: number; readonly size_bytes: number };
  readonly duration_s: number | null;
  readonly error: { readonly code: string; readonly message: string } | null;
  readonly result: AnalysisResult | null;
  readonly cost_usd: number;
  readonly file_deleted: boolean;
  readonly created_at: string | null;
  readonly completed_at: string | null;
}

/** What the analysis is for: a Phân tích row (`content_ref`) and/or a content run. */
export interface AnalysisTarget {
  readonly kind: AnalysisKind;
  readonly contentRef?: string | null;
  readonly productId?: string | null;
  readonly runId?: string | null;
}

export interface ContentAnalysisClients {
  /** Signed-out / no-shop sample: canned result, the upload control is disabled. */
  readonly sample: boolean;
  readonly list: (target: AnalysisTarget) => Promise<readonly ContentAnalysis[]>;
  readonly get: (id: string) => Promise<ContentAnalysis>;
  /** Uploads the file in chunks; `onProgress(0..1)`. Resolves with the queued analysis. */
  readonly upload: (target: AnalysisTarget, file: File, onProgress?: (fraction: number) => void) => Promise<ContentAnalysis>;
}

export const MB = 1024 * 1024;
export const VIDEO_MAX_BYTES = 500 * MB;
export const LIVE_MAX_BYTES = 4096 * MB;
export const ACCEPT = "video/mp4,video/quicktime,.mp4,.mov";

/** Client-side check before any byte is sent; the backend checks again (and probes). */
export function checkFile(kind: AnalysisKind, file: { readonly name: string; readonly type: string; readonly size: number }): string | null {
  const name = file.name.toLowerCase();
  const typeOk = file.type === "video/mp4" || file.type === "video/quicktime" || file.type === "";
  if (!typeOk || !(name.endsWith(".mp4") || name.endsWith(".mov"))) return "Juli chỉ nhận video MP4 hoặc MOV.";
  const limit = kind === "live" ? LIVE_MAX_BYTES : VIDEO_MAX_BYTES;
  if (file.size <= 0) return "Tệp trống.";
  if (file.size > limit) {
    return kind === "live"
      ? `Bản ghi LIVE lớn hơn ${limit / MB} MB. Bạn xuất lại bản nhẹ hơn rồi tải lên.`
      : `Video lớn hơn ${limit / MB} MB. Bạn xuất lại bản nhẹ hơn rồi tải lên.`;
  }
  return null;
}

/** The content type the backend expects, from the file. */
export function contentTypeOf(file: { readonly name: string; readonly type: string }): "video/mp4" | "video/quicktime" {
  if (file.type === "video/quicktime" || file.name.toLowerCase().endsWith(".mov")) return "video/quicktime";
  return "video/mp4";
}

export function isWorking(status: AnalysisStatus): boolean {
  return status === "awaiting_upload" || status === "queued" || status === "processing";
}
