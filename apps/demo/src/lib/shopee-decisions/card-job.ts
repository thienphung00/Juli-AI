import { fillJobHref } from "../../components/planned-changes/listing-extras";

/**
 * The ONE adapter between the card API's `job` block (Track S, batch-1123-a2 K3/K4) and the Demo.
 * Every "open Seller Centre" button, every Thực hiện step word and the Đã làm request read the job
 * through this file, so a renamed API field is changed here only.
 */

export type JobRole = "forward" | "revert" | "readback";

export interface JobDiff {
  readonly field: string;
  readonly label_vi: string;
  readonly card_value: unknown;
  readonly seen_value: unknown;
}

/** The card's current job: when a finished forward job has a queued revert job, this is the revert job. */
export interface CardJob {
  readonly job_id: string;
  readonly role: JobRole;
  /** Fill-job kind: voucher, combo, voucher_end ... */
  readonly kind: string;
  /** Raw status: queued, opened, filled, saved, captured, failed, cancelled. */
  readonly status: string;
  /** The Vietnamese status word from the backend; rendered as is. */
  readonly status_label?: string | null;
  readonly open_path: string | null;
  readonly filled: number;
  readonly total: number;
  readonly readback?: { readonly result: "match" | "mismatch" | null; readonly diffs: readonly JobDiff[] } | null;
}

/** K4 fallback words, used only when the backend sent no `status_label`. */
const STATUS_WORD: Readonly<Record<string, string>> = {
  queued: "Chờ điền",
  opened: "Chờ điền",
  filled: "Đã điền · chờ bạn lưu",
  saved: "Đã lưu · chờ xác minh",
  captured: "Đã lưu · chờ xác minh",
  failed: "Lỗi",
  cancelled: "Đã hủy",
};

/** `https://banhang.shopee.vn{open_path}#juli-fill={job_id}`; null while the job has no page. */
export function jobHref(job: Pick<CardJob, "job_id" | "open_path"> | null | undefined): string | null {
  return job ? fillJobHref({ id: job.job_id, open_path: job.open_path }) : null;
}

/** "Khớp" / "Lệch" once a read-back answered, else the job's status word. */
export function jobWord(job: CardJob): string {
  const r = job.readback?.result;
  if (r === "match") return "Khớp";
  if (r === "mismatch") return "Lệch";
  return job.status_label || STATUS_WORD[job.status] || job.status;
}

const show = (v: unknown): string => (v === null || v === undefined || v === "" ? "—" : typeof v === "string" ? v : String(v));

/** One line per differing field: "Ngày bắt đầu: Seller Centre 03/01 · thẻ 01/03". */
export function jobDiffLines(job: CardJob): readonly string[] {
  return job.readback?.result === "mismatch" ? job.readback.diffs.map((d) => `${d.label_vi}: Seller Centre ${show(d.seen_value)} · thẻ ${show(d.card_value)}`) : [];
}

/** Đã làm request body: digits travel as `id`, anything else the person typed as `code`; nothing typed sends nothing. */
export function markDoneBody(typed: string): { readonly id?: string; readonly code?: string } {
  const t = typed.trim();
  if (t === "") return {};
  return /^\d+$/.test(t) ? { id: t } : { code: t };
}
