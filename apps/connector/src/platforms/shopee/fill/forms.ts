// The Shopee pack's form maps (P97 D85.6): per fill-job action, the Seller Centre page its form is
// on and the filler that types the approved values into it. The core job runner picks the form by
// the job's action; none of them presses Shopee's own save / confirm buttons.

import { FILL_JOB_PAGES } from "../config";
import type { Env, FillOutcome, FormMap } from "../../../core/fill/form";
import { type JobLabels, jobLabels } from "../../../core/fill/job-panel";
import { findControl } from "../../../core/fill/locate";
import { highlight, readValue, targetValue, writeValue } from "../../../core/fill/write";
import { fillAds, fillAffiliate, fillCombo, fillVoucher } from "./fillers";
import type { FillJob, JobKind } from "./job-types";

/** The job panel's Shopee texts. */
export const JOB_LABELS: JobLabels = jobLabels("Shopee");

const NOTHING = (): FillOutcome => ({ steps: [], todo: [], notes: [] });

async function fillText(env: Env, job: FillJob): Promise<FillOutcome> {
  if (job.payload.kind !== "title" && job.payload.kind !== "description_first_line") return { steps: [], todo: [], notes: [] };
  const field = job.payload.fields[0]!;
  const until = env.now() + 25_000;
  let control: HTMLElement | null = null;
  for (;;) {
    control = findControl(env.doc, field.label);
    if (control || env.now() >= until) break;
    await env.sleep(400);
  }
  let ok = false;
  if (control) {
    const current = readValue(control).replace(/\r/g, "");
    const next = targetValue(current, field.value, field.mode);
    ok = current === next || writeValue(control, next);
    if (ok) highlight(control);
  }
  return {
    steps: [{ label: `${field.label}: ${field.value}`, ok, ...(ok ? {} : { note: "Không thấy ô nhập; dán nội dung bằng tay." }) }],
    todo: ["Kiểm tra rồi bấm Cập nhật / Lưu của Shopee."],
    notes: [],
  };
}

export const SHOPEE_FORMS: Readonly<Record<JobKind, FormMap<FillJob>>> = {
  title: { page: FILL_JOB_PAGES.product_edit, fill: fillText },
  description_first_line: { page: FILL_JOB_PAGES.product_edit, fill: fillText },
  voucher: { page: FILL_JOB_PAGES.voucher_new, fill: async (env, job) => (job.payload.kind === "voucher" ? fillVoucher(env, job.payload.voucher) : NOTHING()) },
  ads_edit: { page: FILL_JOB_PAGES.ads_edit, fill: async (env, job) => (job.payload.kind === "ads_edit" ? fillAds(env, job.payload.ads) : NOTHING()) },
  affiliate_commission: {
    page: FILL_JOB_PAGES.affiliate_open,
    fill: async (env, job) => (job.payload.kind === "affiliate_commission" ? fillAffiliate(env, job.payload.affiliate) : NOTHING()),
  },
  combo: { page: FILL_JOB_PAGES.bundle_new, fill: async (env, job) => (job.payload.kind === "combo" ? fillCombo(env, job.payload.combo) : NOTHING()) },
};
