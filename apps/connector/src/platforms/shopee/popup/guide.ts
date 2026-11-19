// What the popup tells the seller (Connector 0.3.17, owner 2026-11-13: "Đồng bộ hôm qua" gave
// no clear instruction): which Seller Centre page to open, what Juli reads from each page, and
// where each page stands today. Pure and unit-tested; the seller's on-screen vocabulary only
// (D31.8): Seller Centre menu names, no endpoint or backend terms.

import { type Dataset, type ReaderId, SELLER_CENTRE_ORIGIN } from "../config";
import type { ReaderSchedule } from "../background/state";

export interface PageGuide {
  /** The Seller Centre menu path the seller recognises. */
  title: string;
  /** The page's path on banhang.shopee.vn (null: a page the Connector picks itself). */
  path: string | null;
  /** What Juli reads there, in plain words. Never buyer names, addresses or phone numbers. */
  pulls: string;
}

/** The page "Đồng bộ hôm qua" works from (it reuses the page's own login and its own call). */
export const SYNC_PAGE: PageGuide = {
  title: "Phân Tích Bán Hàng › Truy cập",
  path: "/datacenter/traffic/overview",
  pulls:
    "Số liệu hôm qua: doanh số và đơn theo nguồn (Thẻ sản phẩm, Video, Live, Tiếp thị liên kết, Quảng cáo), lượt xem, lượt nhấp, lượt truy cập shop.",
};

/** The pages the daily run opens itself, one background tab at a time. */
export const READER_GUIDE: Record<ReaderId, PageGuide> = {
  products: {
    title: "Sản phẩm › Tất cả sản phẩm",
    path: "/portal/product/list/all",
    pulls: "Danh sách sản phẩm, phân loại, giá bán, giá khuyến mãi, tồn kho.",
  },
  vouchers: {
    title: "Kênh Marketing › Mã Giảm Giá",
    path: "/portal/marketing/vouchers/list",
    pulls: "Voucher của shop: mức giảm, đơn tối thiểu, thời gian, lượt đã dùng.",
  },
  ads: {
    title: "Kênh Marketing › Quảng Cáo Shopee",
    path: "/portal/marketing/pas/index",
    pulls: "Từng chiến dịch theo ngày: chi phí, doanh thu, đơn, lượt xem, lượt nhấp; ngân sách và ROAS mục tiêu.",
  },
  ads_detail: {
    title: "Quảng Cáo Shopee › trang chỉnh sửa của từng chiến dịch đang chạy",
    path: null,
    pulls: "Cài đặt chiến dịch: ngân sách, ROAS gợi ý, chi phí theo ngày. Chỉ đọc, không sửa gì.",
  },
  ads_products: {
    title: "Quảng Cáo Shopee › từng chiến dịch nhóm",
    path: null,
    pulls: "Chi phí, doanh thu và đơn quảng cáo của từng sản phẩm trong chiến dịch nhóm.",
  },
  health: {
    title: "Tài khoản › Sức khỏe tài khoản",
    path: "/portal/accounthealth",
    pulls: "Điểm phạt, tỉ lệ giao trễ, hủy đơn, phản hồi chat.",
  },
  shop_totals: {
    title: "Phân Tích Bán Hàng › Tổng quan",
    path: "/datacenter/overview",
    pulls: "Doanh số, đơn, người mua, lượt truy cập của shop theo ngày (đơn đặt, xác nhận, đã thanh toán).",
  },
  product_period: {
    title: "Phân Tích Bán Hàng › Sản phẩm › Hiệu quả",
    path: "/datacenter/product/performance",
    pulls: "30 ngày theo sản phẩm và phân loại: lượt xem, lượt nhấp, thêm vào giỏ, đơn, doanh số.",
  },
  orders: {
    title: "Đơn hàng › Tất cả",
    path: "/portal/sale/order",
    pulls: "Dòng đơn: sản phẩm, số lượng, giá, khuyến mãi, trạng thái. Không lấy tên, địa chỉ, số điện thoại người mua.",
  },
  order_income: {
    title: "Đơn hàng › chi tiết từng đơn đã hoàn thành",
    path: null,
    pulls: "Doanh thu thực nhận, phí sàn, phí vận chuyển, voucher của từng đơn đã hoàn thành.",
  },
  affiliate: {
    title: "Tiếp Thị Liên Kết › Báo cáo chuyển đổi",
    path: "/portal/web-seller-affiliate/conversion_report",
    pulls:
      "Đơn từ KOL: KOL, kênh (Shopee Video, Facebook…), loại chiến dịch, sản phẩm, giá trị đơn, hoa hồng, chi phí. Lần đầu lấy thêm 6 tháng trước.",
  },
  affiliate_kols: {
    title: "Tiếp Thị Liên Kết › Phân tích KOL",
    path: "/portal/web-seller-affiliate/affiliate_analytics",
    pulls: "Theo KOL: doanh số, đơn, lượt nhấp, người mua, hoa hồng, ROI.",
  },
  affiliate_dashboard: {
    title: "Tiếp Thị Liên Kết › Trang chủ",
    path: "/portal/web-seller-affiliate/dashboard",
    pulls: "Tổng doanh số, đơn và chi phí tiếp thị liên kết của shop theo ngày.",
  },
  affiliate_products: {
    title: "Tiếp Thị Liên Kết › Phân tích sản phẩm",
    path: "/portal/web-seller-affiliate/product_analytics",
    pulls: "Theo sản phẩm: doanh số, đơn, lượt nhấp, hoa hồng, ROI từ KOL.",
  },
  affiliate_campaigns: {
    title: "Tiếp Thị Liên Kết › Chiến dịch mở",
    path: "/portal/web-seller-affiliate/open_campaign",
    pulls: "Mức hoa hồng, thời gian chạy và ngân sách của từng chiến dịch.",
  },
  affiliate_commissions: {
    title: "Tiếp Thị Liên Kết › Phân tích chiến dịch",
    path: "/portal/web-seller-affiliate/commission_analytics",
    pulls: "Theo chiến dịch × sản phẩm: số KOL, số lượng bán, doanh số, hoa hồng.",
  },
  affiliate_content: {
    title: "Tiếp Thị Liên Kết › Phân tích nội dung",
    path: "/portal/web-seller-affiliate/content_analytics",
    pulls: "Nội dung KOL: số nội dung, lượt xem, lượt thích, đơn, doanh số.",
  },
  affiliate_bills: {
    title: "Tiếp Thị Liên Kết › Đối soát",
    path: "/portal/web-seller-affiliate/validation_bill",
    pulls: "Đối soát hàng tháng: hoa hồng, thuế, chi phí, khấu trừ.",
  },
  traffic: {
    title: "Phân Tích Bán Hàng › Truy cập",
    path: "/datacenter/traffic/overview",
    pulls: "Doanh số và đơn theo nguồn, lượt xem, lượt nhấp, lượt truy cập shop theo ngày.",
  },
  item_traffic: {
    title: "Phân Tích Bán Hàng › Sản phẩm › Truy cập",
    path: "/datacenter/product/traffic",
    pulls: "Nguồn lượt xem và lượt nhấp của từng sản phẩm theo ngày.",
  },
};

/** Every dataset under the name of what it is (the server's per-dataset status list). */
export const DATASET_LABELS: Record<Dataset, string> = {
  traffic_overview: "Doanh số theo nguồn",
  item_by_source: "Sản phẩm theo nguồn",
  item_performance: "Hiệu quả sản phẩm",
  shop_traffic: "Truy cập shop",
  product_overview: "Tổng quan sản phẩm",
  item_catalog: "Danh sách sản phẩm",
  item_snapshot: "Giá và tồn kho sản phẩm",
  item_traffic_sources: "Nguồn truy cập sản phẩm",
  ads_campaign_daily: "Quảng cáo theo ngày",
  ads_campaign_settings: "Cài đặt chiến dịch quảng cáo",
  ads_campaign_detail: "Chi tiết chiến dịch quảng cáo",
  ads_campaign_period: "Quảng cáo theo sản phẩm",
  voucher_settings: "Voucher của shop",
  shop_health_daily: "Sức khỏe tài khoản",
  market_search: "Giá thị trường",
  shop_overview: "Tổng quan shop theo ngày",
  product_period: "Hiệu quả sản phẩm 30 ngày",
  order_lines: "Dòng đơn hàng",
  order_income: "Doanh thu từng đơn",
  affiliate_order_lines: "Đơn KOL",
  affiliate_partner_period: "KOL theo kỳ",
  affiliate_shop_period: "Tiếp thị liên kết theo ngày",
  affiliate_product_period: "Sản phẩm KOL theo kỳ",
  affiliate_shop_campaigns: "Chiến dịch KOL",
  affiliate_commission_period: "Hoa hồng KOL",
  affiliate_content_period: "Nội dung KOL",
  affiliate_bill_period: "Đối soát KOL",
};

export function pageUrl(path: string): string {
  return `${SELLER_CENTRE_ORIGIN}${path}`;
}

export type Tone = "ok" | "busy" | "wait" | "warn" | "muted";

/** One thing the seller can do next: a sentence and, when it helps, the page to open. */
export interface Guidance {
  text: string;
  tone: Tone;
  open?: { label: string; url: string };
}

const OPEN_SYNC_PAGE = { label: `Mở ${SYNC_PAGE.title}`, url: pageUrl(SYNC_PAGE.path as string) };

/**
 * What "Đồng bộ hôm qua" did, and what to do next. `result` is the service worker's answer
 * (dailySync) or the page's report (syncResult); `day` the GMT+7 day it is about.
 */
export function syncGuidance(result: string, day?: string): Guidance {
  const of = day ? ` ngày ${day}` : "";
  switch (result) {
    case "requested":
      return { text: `Đang lấy số liệu${of} từ tab Seller Centre đang mở…`, tone: "busy" };
    case "done":
      return { text: `Đã lấy số liệu${of}: ${SYNC_PAGE.pulls}`, tone: "ok" };
    case "already_synced":
      return { text: `Số liệu${of} đã đồng bộ xong. Bấm lại vào ngày mai cho ngày hôm nay.`, tone: "ok" };
    case "no_tab":
      // 0.3.19: the traffic reader reads Truy cập in its own background tab during today's run.
      return {
        text: `Chưa có tab Seller Centre nào đang mở: tiện ích sẽ tự đọc trang ${SYNC_PAGE.title} trong tab nền ở lượt đọc hôm nay. Muốn lấy ngay: mở trang đó, chờ trang hiện số liệu, rồi bấm “Đồng bộ hôm qua” lần nữa.`,
        tone: "wait",
        open: OPEN_SYNC_PAGE,
      };
    case "needs_data_page":
      return {
        text: `Tab Seller Centre đang mở chưa tải trang số liệu nào. Mở trang ${SYNC_PAGE.title} trong tab đó và chờ biểu đồ hiện ra: tiện ích sẽ tự đồng bộ.`,
        tone: "warn",
        open: OPEN_SYNC_PAGE,
      };
    case "busy":
      return {
        text: "Tiện ích đang đọc các trang báo cáo trong tab nền (xem danh sách bên dưới). Đồng bộ hôm qua sẽ tự chạy khi đọc xong.",
        tone: "busy",
      };
    case "budget_spent":
      return {
        text: "Hôm nay tiện ích đã dùng hết lượt đọc Seller Centre (để tránh bị chặn). Ngày mai sẽ tự đồng bộ tiếp.",
        tone: "wait",
      };
    case "blocked":
      return {
        text: "Seller Centre đang yêu cầu đăng nhập hoặc xác minh. Mở Seller Centre, đăng nhập / xác minh, rồi bấm “Đồng bộ hôm qua”.",
        tone: "warn",
        open: { label: "Mở Seller Centre", url: pageUrl("/") },
      };
    case "consent_required":
      return {
        text: "Shop này chưa được cấp quyền đồng bộ với Juli. Liên hệ Juli để bật quyền, rồi bấm “Đồng bộ hôm qua”.",
        tone: "warn",
      };
    case "unpaired":
      return { text: "Tiện ích chưa kết nối với Juli: nhập mã kết nối mới.", tone: "warn" };
    default:
      return { text: `Đồng bộ${of}: ${result}`, tone: "muted" };
  }
}

export interface PageRow {
  id: ReaderId;
  title: string;
  pulls: string;
  status: string;
  tone: Tone;
  url?: string;
}

/** A finished job's outcome (scheduler finishJob) in the seller's words. */
/** 0.3.25: the Phân tích bán hàng password dialog; the seller confirms it once (the Connector never types it). */
export const PASSWORD_RECHECK_LINE = "Xác nhận mật khẩu Shopee một lần trong Phân tích bán hàng";

/** 0.3.26: the sub-account may not open Tài chính (income); the shop owner grants the right. */
export const NO_PERMISSION_LINE = "Cần quyền Tài chính Seller Centre";

/** HH:mm in GMT+7 (the seller's clock), from ms. */
export function gmt7Time(ms: number): string {
  const d = new Date(ms + 7 * 3_600_000);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** 0.3.28 (F5.3, contract R): Shopee's traffic-check page paused every automation until `until`. */
export const TRAFFIC_CHECK_STATUS = "Shopee tạm chặn truy cập tự động";
export const trafficCheckLine = (until: number) => `${TRAFFIC_CHECK_STATUS} — Juli dừng đến ${gmt7Time(until)}`;

/** The same line inside a sentence. */
export const PASSWORD_RECHECK_LOWER = PASSWORD_RECHECK_LINE.charAt(0).toLowerCase() + PASSWORD_RECHECK_LINE.slice(1);

export function outcomeStatus(outcome: string): { status: string; tone: Tone } {
  const head = outcome.split(/[:|]/, 1)[0] ?? outcome;
  if (head === "done") {
    const failed = /=(rejected|drift|stopped|refused)/.test(outcome);
    if (failed) return { status: "Đã đọc, một phần chưa gửi được (Seller Centre có thể đã đổi giao diện)", tone: "warn" };
    // 0.3.20: "read and sent" only when something was sent (or held / queued to send).
    if (/=(posted|queued|held)\b/.test(outcome)) return { status: "Đã đọc và gửi", tone: "ok" };
    if (/=empty\b/.test(outcome) && !/=ignored\b/.test(outcome)) return { status: "Đã đọc: không có số liệu mới", tone: "muted" };
    return { status: "Đã đọc nhưng không có số liệu để gửi: sẽ thử lại lần sau", tone: "warn" };
  }
  switch (head) {
    case "no_items":
    case "no_campaigns":
    case "no_group_campaigns":
    case "no_orders":
      return { status: "Không có gì cần đọc", tone: "muted" };
    case "waiting_budget":
      return { status: "Hết lượt đọc hôm nay, đọc tiếp ngày mai", tone: "wait" };
    case "blocked_captcha":
      return { status: "Dừng: Seller Centre yêu cầu xác minh (CAPTCHA)", tone: "warn" };
    case "blocked_login":
      return { status: "Dừng: cần đăng nhập lại Seller Centre", tone: "warn" };
    case "blocked":
      // 0.3.22: "blocked:login" / "blocked:captcha": this page only; the other pages went on.
      if (outcome.startsWith("blocked:password_recheck")) return { status: PASSWORD_RECHECK_LINE, tone: "warn" };
      if (outcome.startsWith("blocked:no_permission")) return { status: NO_PERMISSION_LINE, tone: "warn" };
      if (outcome.startsWith("blocked:traffic_check")) return { status: TRAFFIC_CHECK_STATUS, tone: "warn" };
      return outcome.startsWith("blocked:captcha")
        ? { status: "Trang này yêu cầu xác minh (CAPTCHA)", tone: "warn" }
        : { status: "Đăng nhập lại để đọc trang này", tone: "warn" };
    case "blocked_rate_limit":
      return { status: "Dừng: Seller Centre báo truy cập quá nhiều, thử lại sau", tone: "warn" };
    case "needs_data_page":
    case "needs_template":
      return { status: "Trang mở nhưng chưa tải số liệu: sẽ thử lại lần sau", tone: "wait" };
    case "timeout":
      return { status: "Trang tải quá lâu: sẽ thử lại lần sau", tone: "wait" };
    case "error": {
      // 0.3.26: "error:orders:0_rows:<step>": the page was read but no order came out; the step says where.
      const zero = /^error:(orders|order_income):0_rows:([^|]+)/.exec(outcome);
      if (zero) return { status: `Chưa đọc được đơn nào (${zero[2]}): sẽ thử lại lần sau`, tone: "warn" };
      return { status: "Lỗi khi đọc: sẽ thử lại lần sau", tone: "warn" };
    }
    case "redirected":
      return { status: "Seller Centre chuyển sang trang khác (có thể cần đăng nhập)", tone: "warn" };
    case "closed":
      return { status: "Tab bị đóng giữa chừng: sẽ thử lại lần sau", tone: "wait" };
    case "open_failed":
      return { status: "Không mở được tab: sẽ thử lại lần sau", tone: "wait" };
    default:
      return { status: "Lỗi khi đọc: sẽ thử lại lần sau", tone: "warn" };
  }
}

/**
 * One row per report page, in reading order: what it reads and where it stands. Today's run
 * wins (reading now / waiting its turn / its outcome); else the last run's outcome with its day.
 */
export function pageRows(readers: ReaderSchedule | null | undefined, ids: readonly ReaderId[]): PageRow[] {
  const run = readers?.run;
  const last = readers?.lastRun;
  return ids.map((id) => {
    const guide = READER_GUIDE[id];
    const base = { id, title: guide.title, pulls: guide.pulls, ...(guide.path ? { url: pageUrl(guide.path) } : {}) };
    if (run) {
      const at = run.jobs.findIndex((job) => job.id === id);
      if (at >= 0 && at === run.index && run.current) return { ...base, status: "Đang đọc…", tone: "busy" as Tone };
      const done = run.outcomes[id];
      if (done) return { ...base, ...outcomeStatus(done) };
      if (at >= run.index) return { ...base, status: "Chờ lượt hôm nay", tone: "wait" as Tone };
    }
    const previous = last?.outcomes[id];
    if (previous) {
      const { status, tone } = outcomeStatus(previous);
      return { ...base, status: `${status} (${last?.day})`, tone };
    }
    if (run && !run.jobs.some((job) => job.id === id)) {
      return { ...base, status: "Hôm nay không cần đọc lại (đã đủ số liệu)", tone: "muted" as Tone };
    }
    return { ...base, status: "Chưa có kết quả", tone: "muted" as Tone };
  });
}

/** The line above the list while a run is going: which page, how far. */
export function runLine(readers: ReaderSchedule | null | undefined, nowMs: number = Date.now()): string | null {
  if (readers?.blocked && readers.blocked.until > nowMs) {
    const page = READER_GUIDE[readers.blocked.page]?.title ?? "Seller Centre";
    if (readers.blocked.reason === "password_recheck") return `Tạm dừng: ${PASSWORD_RECHECK_LOWER} (trang ${page}).`;
    if (readers.blocked.reason === "traffic_check") return trafficCheckLine(readers.blocked.until);
    return readers.blocked.reason === "captcha"
      ? `Tạm dừng: Seller Centre yêu cầu xác minh (CAPTCHA) ở trang ${page}. Mở Seller Centre, xác minh, rồi bấm “Đồng bộ hôm qua”.`
      : readers.blocked.reason === "login"
        ? `Tạm dừng: cần đăng nhập lại Seller Centre (trang ${page}).`
        : `Tạm dừng: Seller Centre báo truy cập quá nhiều ở trang ${page}. Tiện ích tự thử lại sau.`;
  }
  const run = readers?.run;
  if (!run || run.jobs.length === 0) return null;
  const job = run.jobs[Math.min(run.index, run.jobs.length - 1)];
  const title = job ? READER_GUIDE[job.id].title : "";
  const step = Math.min(run.index + 1, run.jobs.length);
  return `Đang đọc trang ${step}/${run.jobs.length} trong một tab nền: ${title}. Không cần làm gì, có thể tiếp tục dùng Chrome.`;
}

/** dd/mm hh:mm in GMT+7 (the seller's clock), from an ISO time or ms. */
export function gmt7Stamp(at: string | number): string {
  const ms = typeof at === "number" ? at : Date.parse(at);
  if (!Number.isFinite(ms)) return "";
  const d = new Date(ms + 7 * 3_600_000);
  const two = (n: number) => String(n).padStart(2, "0");
  return `${two(d.getUTCDate())}/${two(d.getUTCMonth() + 1)} ${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`;
}

const TRIGGER_LABELS: Record<string, string> = {
  pair: "sau khi kết nối",
  worker_start: "khi tiện ích khởi động",
  chrome_start: "khi mở Chrome",
  install: "sau khi cài",
  update: "sau khi cập nhật",
  daily_alarm: "theo lịch hằng ngày",
  alarm: "theo lịch hằng ngày",
  stock_alarm: "đọc tồn kho 06:30",
  after_stock: "sau khi đọc tồn kho",
  retry: "thử lại",
  reread: "đọc lại các trang bị chặn",
  kick: "thử lại",
  manual: "bấm “Đồng bộ hôm qua”",
};

/** A scheduler tick's result (ReaderScheduler.tick) in the seller's words. */
export function tickResultLabel(result: string): string {
  const head = result.replace(/^stock[:_]/, "");
  if (head.startsWith("blocked:traffic_check")) return TRAFFIC_CHECK_STATUS.toLowerCase();
  switch (head) {
    case "opened":
      return result.startsWith("stock") ? "bắt đầu đọc tồn kho" : "bắt đầu đọc các trang";
    case "finished":
      return "đã đọc xong";
    case "done_today":
      return "hôm nay đã đọc xong";
    case "nothing_to_do":
      return "không có trang nào cần đọc";
    case "backfill_busy":
      return "đang lấy số liệu 30 ngày trước, thử lại sau vài phút";
    case "fill_busy":
      return "đang mở một trang điền của Juli, đọc sau khi bạn đóng trang đó";
    case "blocked":
      return "đang tạm dừng (Seller Centre yêu cầu đăng nhập hoặc xác minh)";
    case "consent_required":
      return "shop chưa được cấp quyền đồng bộ";
    case "off":
      return "tiện ích không đọc cho shop này";
    case "unpaired":
      return "chưa kết nối với Juli";
    case "budget_spent":
      return "hết lượt đọc hôm nay";
    default:
      return head.startsWith("blocked:password_recheck")
        ? PASSWORD_RECHECK_LOWER
        : head.startsWith("blocked:")
          ? "dừng: Seller Centre yêu cầu đăng nhập hoặc xác minh"
          : head;
  }
}

/** The last tick from rest (0.3.19): when, what woke it, how it ended. Null before the first. */
export function tickLine(readers: ReaderSchedule | null | undefined): string | null {
  const tick = readers?.lastTick;
  if (!tick) return null;
  const why = TRIGGER_LABELS[tick.trigger] ?? tick.trigger;
  return `Lượt gần nhất ${gmt7Stamp(tick.at)} (${why}): ${tickResultLabel(tick.result)}`;
}

/** The daily stock read (0.3.19): when the product list with stock was last read, or how today's try went. */
export function stockLine(readers: ReaderSchedule | null | undefined): string | null {
  if (readers?.productsAt) return `Tồn kho đọc lúc ${gmt7Stamp(readers.productsAt)} · mỗi ngày 06:30`;
  const stock = readers?.stock;
  if (stock?.outcome) return `Đọc tồn kho ${gmt7Stamp(stock.at ?? "")}: ${outcomeStatus(stock.outcome).status}`;
  return "Tồn kho: đọc mỗi ngày lúc 06:30";
}

/** The once-per-shop 90-day ads history (0.3.19): how far it got, or where Shopee's history ends. */
export function adsHistoryLine(readers: ReaderSchedule | null | undefined): string | null {
  const history = readers?.adsHistory;
  if (!history) return null;
  const total = history.days.length;
  const dm = (day: string | undefined) => (day ? `${day.slice(8, 10)}/${day.slice(5, 7)}/${day.slice(0, 4)}` : "");
  if (history.status === "done") {
    return history.limit
      ? `Quảng cáo các ngày trước: đã lấy đến ${dm(history.earliest)} (Seller Centre không giữ xa hơn)`
      : `Quảng cáo ${total} ngày trước: đã lấy đủ`;
  }
  return `Quảng cáo ${total} ngày trước: ${history.done.length}/${total} ngày`;
}
