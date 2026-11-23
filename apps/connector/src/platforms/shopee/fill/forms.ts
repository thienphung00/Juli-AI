// The Shopee pack's form maps (P97 D85.6): per fill-job action, the Seller Centre page its form is
// on and the filler that types the approved values into it. The core job runner picks the form by
// the job's action; none of them presses Shopee's own save / confirm buttons.

import { FILL_JOB_PAGES, FILL_POLL_MS, FILL_WAIT_MS } from "../config";
import type { Env, FillOutcome, FormMap } from "../../../core/fill/form";
import { type JobLabels, jobLabels } from "../../../core/fill/job-panel";
import { findControl } from "../../../core/fill/locate";
import { fillOne } from "../../../core/fill/settle";
import { buttonsMatching, findRow } from "./controls";
import { COMBO_LABELS, cssAttr, fillAds, fillAffiliate, fillCombo, fillVariationPrices, fillVoucher, VOUCHER_LABELS } from "./fillers";
import { fillEnd, fillProgrammeEnd, productCurrent, readProduct } from "./revert";
import { ADD_GROUP_TEXT, DISCOUNT_LABELS, fillCover, fillDeal, fillFlashSale, fillProductDiscount, fillVariationSet, FLASH_SLOT_TEXT, imageGrid, lockedOutcome, priceLocked } from "./promos";
import { readAffiliate } from "./fillers";
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
  // contract D: what Shopee holds now (the value kept before Juli typed, the other field as shown)
  const current = productCurrent(env.doc, job.payload.itemId, env.log?.before ?? {});
  return {
    ...(current ? { current: [current] } : {}),
    steps: [
      {
        label: `${field.label}: ${field.value}`,
        ok,
        keys: [key],
        ...(ok ? {} : { note: control ? "Shopee chưa nhận nội dung; dán bằng nút Sao chép." : "Không thấy ô nhập; dán nội dung bằng tay." }),
      },
    ],
    todo: [job.mode === "revert" ? "Đây là hoàn tác: kiểm tra giá trị cũ rồi bấm Cập nhật / Lưu của Shopee." : "Kiểm tra rồi bấm Cập nhật / Lưu của Shopee."],
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
  price: {
    page: FILL_JOB_PAGES.product_edit,
    ready: (doc, job) => job.payload.kind === "price" && job.payload.price.variations.some((v) => !!doc.querySelector(`[data-variation-id="${cssAttr(v.variationId)}"]`)),
    fill: async (env, job) => {
      if (job.payload.kind !== "price") return NOTHING();
      // F7: a price greyed by a running promotion: nothing is written, the job ends "Bị khoá"
      if (priceLocked(env.doc, job.payload.price.variations)) return lockedOutcome(env, "Giá theo phân loại");
      return fillVariationPrices(env, job.payload.price.variations);
    },
  },
  // batch-1123-a F (0.3.32)
  product_discount: {
    page: FILL_JOB_PAGES.discount_new,
    ready: rowReady(DISCOUNT_LABELS.name),
    fill: async (env, job) => (job.payload.kind === "product_discount" ? fillProductDiscount(env, job.payload.discount) : NOTHING()),
  },
  flash_sale: {
    page: FILL_JOB_PAGES.flash_sale_new,
    ready: (doc) => buttonsMatching(doc, FLASH_SLOT_TEXT).length > 0,
    fill: async (env, job) => (job.payload.kind === "flash_sale" ? fillFlashSale(env, job.payload.flash) : NOTHING()),
  },
  add_on: { page: FILL_JOB_PAGES.deal_new, fill: async (env, job) => (job.payload.kind === "add_on" ? fillDeal(env, job.payload.deal) : NOTHING()) },
  gift: { page: FILL_JOB_PAGES.deal_new, fill: async (env, job) => (job.payload.kind === "gift" ? fillDeal(env, job.payload.deal) : NOTHING()) },
  cover_image: {
    page: FILL_JOB_PAGES.product_edit,
    ready: (doc) => !!imageGrid(doc),
    fill: async (env, job) => (job.payload.kind === "cover_image" ? fillCover(env, job.payload.cover, job.mode === "revert") : NOTHING()),
  },
  variation_set: {
    page: FILL_JOB_PAGES.product_edit,
    ready: (doc) => !!doc.querySelector('input[placeholder="Nhập"]') || buttonsMatching(doc, ADD_GROUP_TEXT).length > 0,
    fill: async (env, job) => (job.payload.kind === "variation_set" ? fillVariationSet(env, job.payload.variations, job.mode === "revert") : NOTHING()),
  },
  discount_end: { page: FILL_JOB_PAGES.discount_list, fill: fillProgrammeEnd },
  flash_sale_end: { page: FILL_JOB_PAGES.flash_sale_list, fill: fillProgrammeEnd },
  deal_end: { page: FILL_JOB_PAGES.discount_list, fill: fillProgrammeEnd },
  voucher_end: { page: FILL_JOB_PAGES.voucher_list, fill: fillEnd },
  combo_end: { page: FILL_JOB_PAGES.bundle_list, fill: fillEnd },
  // a read-back of a product opens its edit page, an affiliate one the open campaign (the list
  // read-backs run as the daily readers)
  readback: {
    page: FILL_JOB_PAGES.product_edit,
    fill: (env, job) => (FILL_JOB_PAGES.affiliate_open.test(job.openPath.split("?")[0] ?? "") ? readAffiliate(env, job) : readProduct(env, job)),
  },
};
