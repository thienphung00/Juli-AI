/**
 * Copy of the partner reviewer guide (fast track P77). Mirrors dictionary.md
 * `reviewer.guide.*`. The body is English (the reviewer's language); the
 * Vietnamese names in quotes are the app's own strings, verbatim.
 */

export type GuideStepId = "home" | "analysis" | "propose" | "switch" | "sync" | "write" | "measure" | "undo";
export type GuidePart = "read" | "write" | "check";

export interface GuideStep {
  readonly id: GuideStepId;
  readonly part: GuidePart;
  readonly title: string;
  readonly body: string;
  /** Mobile (bottom sheet) variants. */
  readonly shortTitle: string;
  readonly shortBody: string;
  /** Where in the app: shown as the step's link text. */
  readonly where: string;
  /** Route to open; `null` = the step is the shop switch (a handler, not a route). */
  readonly href: string | null;
}

export const GUIDE_STEPS: readonly GuideStep[] = [
  {
    id: "home",
    part: "read",
    title: "Trang chủ: live GMV, orders and traffic",
    body: "Pulled from the TikTok Shop Open API for the last 30 days. Shop name and ids are hidden.",
    shortTitle: "Trang chủ: live GMV and orders",
    shortBody: "From the TikTok Shop Open API, last 30 days. Names and ids hidden.",
    where: "Trang chủ",
    href: "/",
  },
  {
    id: "analysis",
    part: "read",
    title: "Phân tích: where GMV is lost",
    body: "Product card, shop tab, video, LIVE and promotions, each broken down by product.",
    shortTitle: "Phân tích: where GMV is lost",
    shortBody: "Product card, shop tab, video, LIVE and promotions.",
    where: "Phân tích",
    href: "/analytics",
  },
  {
    id: "propose",
    part: "read",
    title: "Quyết định: approve a recommendation",
    body: "Press “Duyệt” on a card. On this shop the approval is simulated: the seller’s shop is never changed.",
    shortTitle: "Quyết định: approve a card",
    shortBody: "Simulated here: the seller’s shop is never changed.",
    where: "Quyết định › Đề xuất",
    href: "/decisions?tab=de-xuat",
  },
  {
    id: "switch",
    part: "write",
    title: "Switch to the sandbox shop",
    body: "Open the shop menu at the top left and choose “Chuyển sang Shop sandbox TikTok”.",
    shortTitle: "Switch to the sandbox shop",
    shortBody: "Shop menu › “Chuyển sang Shop sandbox TikTok”.",
    where: "Shop menu",
    href: null,
  },
  {
    id: "sync",
    part: "write",
    title: "Sync from TikTok",
    body: "Press “Đồng bộ ngay”. Orders and products refresh from the sandbox within a minute.",
    shortTitle: "Sync from TikTok",
    shortBody: "Press “Đồng bộ ngay” on the connection card.",
    where: "Trang chủ › Kết nối TikTok Shop",
    href: "/",
  },
  {
    id: "write",
    part: "write",
    title: "Approve a change and confirm it",
    body: "Create a product, a promotion or a better listing. Juli shows the exact change, then writes it to TikTok after you confirm.",
    shortTitle: "Approve and confirm a change",
    shortBody: "Product, promotion or listing: written to TikTok after you confirm.",
    where: "Quyết định › Duyệt › Xác nhận",
    href: "/decisions?tab=de-xuat",
  },
  {
    id: "measure",
    part: "check",
    title: "Đo lường: what TikTok confirmed",
    body: "See the write with TikTok’s id and time, and TikTok’s own quality check after the edit.",
    shortTitle: "Đo lường: what TikTok confirmed",
    shortBody: "TikTok’s id, time and its own quality check.",
    where: "Quyết định › Đo lường",
    href: "/decisions?tab=do-luong",
  },
  {
    id: "undo",
    part: "check",
    title: "Hoàn tác: undo it on TikTok",
    body: "Juli reads TikTok first, checks for outside edits, then restores the old value after you confirm.",
    shortTitle: "Hoàn tác: undo it on TikTok",
    shortBody: "Juli checks for outside edits, then restores the old value.",
    where: "Đo lường › Hoàn tác",
    href: "/decisions?tab=do-luong",
  },
];

export const GUIDE_PARTS: readonly { readonly id: GuidePart; readonly chip: string; readonly title: string; readonly tab: string }[] = [
  { id: "read", chip: "READ", title: "Part 1 · A real seller’s shop (read-only)", tab: "Read" },
  { id: "write", chip: "WRITE", title: "Part 2 · A TikTok sandbox shop (real writes)", tab: "Write" },
  { id: "check", chip: "CHECK", title: "Part 3 · Measure and undo", tab: "Check" },
];

export const GUIDE_EYEBROW = "PARTNER REVIEWER GUIDE";
export const GUIDE_TITLE = "See Juli's live TikTok Shop integration in 8 steps";
export const GUIDE_SHEET_TITLE = "Read a real shop, then write to a sandbox";
export const GUIDE_INTRO =
  "Part 1 reads a real seller's shop (names and ids hidden, nothing is changed). Part 2 writes real changes to a TikTok Shop sandbox shop through the Open API.";
export const GUIDE_DURATION = "~10 min";
export const GUIDE_COLLAPSE_LABEL = "Collapse the guide";
export const GUIDE_CLOSE_LABEL = "Close the guide";
export const GUIDE_START_OVER = "Start over";
export const GUIDE_DONE_LABEL = "Done: you have seen read and write";
export const GUIDE_STEPS_LABEL = "Guide steps";

export function guideProgress(done: number, total: number): string {
  return `${done} of ${total} done`;
}
export function guideProgressShort(done: number, total: number): string {
  return `${done}/${total}`;
}
export function guidePillLabel(done: number, total: number): string {
  return `Reviewer guide · ${guideProgressShort(done, total)}`;
}
export function guideContinueLabel(step: number): string {
  return `Continue with step ${step}`;
}

/**
 * P100 S2-F: the guide on the synthetic Shopee sample shop ("Dữ liệu mẫu", pin mode `sample`).
 * Vietnamese, fewer words. Part 1 reads the sample shop (synthetic names, never a seller's shop),
 * Part 2 and 3 are the TikTok sandbox as before (the switch step names the sample menu's "Đổi shop"). Same step ids, so the ticks carry over.
 * Mirrors dictionary.md `reviewer.guide_sample`.
 */
type SampleStepId = "home" | "analysis" | "propose" | "switch";
const SAMPLE_OVERRIDES: Readonly<Record<SampleStepId, Pick<GuideStep, "title" | "body" | "shortTitle" | "shortBody" | "where" | "href">>> = {
  home: {
    title: "Tổng quan: GMV, đơn, lượt xem",
    body: "Shop Shopee dữ liệu mẫu, 30 ngày. Tên và số liệu đều là mẫu.",
    shortTitle: "Tổng quan",
    shortBody: "Dữ liệu mẫu, 30 ngày.",
    where: "Tổng quan",
    href: "/tong-quan",
  },
  analysis: {
    title: "Phân tích: GMV mất ở đâu",
    body: "Theo nguồn và theo sản phẩm.",
    shortTitle: "Phân tích",
    shortBody: "Theo nguồn và sản phẩm.",
    where: "Phân tích",
    href: "/phan-tich",
  },
  propose: {
    title: "Quyết định: bấm “Duyệt”",
    body: "Tiêu đề, Ảnh bìa, Voucher. Duyệt chỉ mô phỏng, không gửi tới Shopee.",
    shortTitle: "Quyết định: Duyệt",
    shortBody: "Chỉ mô phỏng.",
    where: "Quyết định › Đề xuất",
    href: "/decisions?tab=de-xuat",
  },
  // the sample shop's menu reads "Đổi shop" (P100 S2-C)
  switch: {
    title: "Đổi sang shop sandbox",
    body: "Menu shop góc trên trái › “Đổi shop”.",
    shortTitle: "Đổi sang shop sandbox",
    shortBody: "Menu shop › “Đổi shop”.",
    where: "Menu shop",
    href: null,
  },
};

const isSampleStep = (id: GuideStepId): id is SampleStepId => id in SAMPLE_OVERRIDES;

export const GUIDE_SAMPLE_STEPS: readonly GuideStep[] = GUIDE_STEPS.map((step) =>
  isSampleStep(step.id) ? { ...step, ...SAMPLE_OVERRIDES[step.id] } : step,
);

export const GUIDE_SAMPLE_PARTS: typeof GUIDE_PARTS = [
  { id: "read", chip: "READ", title: "Phần 1 · Shop Shopee dữ liệu mẫu (chỉ xem)", tab: "Xem" },
  { id: "write", chip: "WRITE", title: "Phần 2 · Shop sandbox TikTok (ghi thật)", tab: "Ghi" },
  { id: "check", chip: "CHECK", title: "Phần 3 · Đo và hoàn tác", tab: "Kiểm tra" },
];

export const GUIDE_SAMPLE_TITLE = "Xem Juli trong 8 bước";
export const GUIDE_SAMPLE_SHEET_TITLE = "Xem dữ liệu mẫu, rồi ghi lên sandbox";
export const GUIDE_SAMPLE_INTRO = "Phần 1: shop Shopee dữ liệu mẫu, chỉ xem. Phần 2: ghi thật lên shop sandbox TikTok.";

export interface GuideCopy {
  readonly steps: readonly GuideStep[];
  readonly parts: typeof GUIDE_PARTS;
  readonly title: string;
  readonly sheetTitle: string;
  readonly intro: string;
}

/** The guide's copy for the active pin: the sample shop's, else the P77 copy. */
export function guideCopy(sampleShop: boolean): GuideCopy {
  return sampleShop
    ? { steps: GUIDE_SAMPLE_STEPS, parts: GUIDE_SAMPLE_PARTS, title: GUIDE_SAMPLE_TITLE, sheetTitle: GUIDE_SAMPLE_SHEET_TITLE, intro: GUIDE_SAMPLE_INTRO }
    : { steps: GUIDE_STEPS, parts: GUIDE_PARTS, title: GUIDE_TITLE, sheetTitle: GUIDE_SHEET_TITLE, intro: GUIDE_INTRO };
}
