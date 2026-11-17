// The Shopee pack's form maps (P97 D85.6): per fill-job action, the Seller Centre page its form is
// on and the filler that types the approved values into it. The core job runner picks the form by
// the job's action; none of them presses Shopee's own save / confirm buttons.

import { FILL_JOB_PAGES, FILL_POLL_MS, FILL_WAIT_MS } from "../config";
import type { Env, FillOutcome, FormMap } from "../../../core/fill/form";
import { type JobLabels, jobLabels } from "../../../core/fill/job-panel";
import { findControl } from "../../../core/fill/locate";
import { fillOne } from "../../../core/fill/settle";
import { findRow } from "./controls";
import { COMBO_LABELS, fillAds, fillAffiliate, fillCombo, fillVoucher, VOUCHER_LABELS } from "./fillers";
import type { FillJob, JobKind } from "./job-types";

/** The job panel's Shopee texts. */
export const JOB_LABELS: JobLabels = jobLabels("Shopee");

const NOTHING = (): FillOutcome => ({ steps: [], todo: [], notes: [] });

/**
 * Title / description through the job path. 0.3.24: the same settle → write → re-read as the
 * listing fill (live 2026-11-17 the job path wrote at once, Shopee then loaded the product over it
 * and the panel still said ✓): wait for the control, wait for Shopee's own value to hold still,
 * keep it (the before value), write, read again; the runner's re-read decides ✓.
 */
async function fillText(env: Env, job: FillJob): Promise<FillOutcome> {
  if (job.payload.kind !== "title" && job.payload.kind !== "description_first_line") return NOTHING();
  const field = job.payload.fields[0]!;
  const until = env.now() + FILL_WAIT_MS;
  let control: HTMLElement | null = null;
  for (;;) {
    control = findControl(env.doc, field.label);
    if (control || env.now() >= until) break;
    await env.sleep(FILL_POLL_MS);
  }
  // the sheet's step keys (the revert reads before_values by them): title, first_line
  const key = field.key === "description_first_line" ? "first_line" : field.key;
  const ok = !!control && (await fillOne(env, control, field, until, env.log, key));
  return {
    steps: [
      {
        label: `${field.label}: ${field.value}`,
        ok,
        keys: [key],
        ...(ok ? {} : { note: control ? "Shopee chưa nhận nội dung; dán bằng nút Sao chép." : "Không thấy ô nhập; dán nội dung bằng tay." }),
      },
    ],
    todo: ["Kiểm tra rồi bấm Cập nhật / Lưu của Shopee."],
    notes: [],
  };
}

const textReady = (doc: Document, job: FillJob) =>
  (job.payload.kind === "title" || job.payload.kind === "description_first_line") && !!findControl(doc, job.payload.fields[0]!.label);
const rowReady = (label: string) => (doc: Document) => !!findRow(doc, label);

export const SHOPEE_FORMS: Readonly<Record<JobKind, FormMap<FillJob>>> = {
  title: { page: FILL_JOB_PAGES.product_edit, ready: textReady, fill: fillText },
  description_first_line: { page: FILL_JOB_PAGES.product_edit, ready: textReady, fill: fillText },
  voucher: { page: FILL_JOB_PAGES.voucher_new, ready: rowReady(VOUCHER_LABELS.name), fill: async (env, job) => (job.payload.kind === "voucher" ? fillVoucher(env, job.payload.voucher) : NOTHING()) },
  ads_edit: { page: FILL_JOB_PAGES.ads_edit, fill: async (env, job) => (job.payload.kind === "ads_edit" ? fillAds(env, job.payload.ads) : NOTHING()) },
  affiliate_commission: {
    page: FILL_JOB_PAGES.affiliate_open,
    fill: async (env, job) => (job.payload.kind === "affiliate_commission" ? fillAffiliate(env, job.payload.affiliate) : NOTHING()),
  },
  combo: { page: FILL_JOB_PAGES.bundle_new, ready: rowReady(COMBO_LABELS.name), fill: async (env, job) => (job.payload.kind === "combo" ? fillCombo(env, job.payload.combo) : NOTHING()) },
};
