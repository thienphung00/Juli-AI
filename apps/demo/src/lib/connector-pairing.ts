/**
 * The seller's side of the Juli Connector pairing (P96, owner 2026-11-06): `/v1/ingest/*` with the
 * seller's session and `X-Shop-Id`, the same endpoints the extension's pairing code is exchanged
 * against. A code is single-use and short-lived; a token's secret never comes back to the page.
 */

export interface SellerPairingCode {
  readonly code: string;
  readonly expires_at: string;
  readonly ttl_seconds: number;
}

export interface SellerIngestToken {
  readonly id: string;
  readonly client_label: string | null;
  readonly last_used_at: string | null;
  readonly active: boolean;
}

export class PairingRequestError extends Error {
  constructor(public readonly status: number) {
    super(`pairing request failed (${status})`);
  }
}

interface Auth {
  readonly token: string;
  readonly shopId: string;
  readonly fetchImpl?: typeof fetch;
}

async function call(auth: Auth, path: string, method: "GET" | "POST" | "DELETE"): Promise<Response> {
  const response = await (auth.fetchImpl ?? fetch)(path, {
    method,
    headers: { Accept: "application/json", Authorization: `Bearer ${auth.token}`, "X-Shop-Id": auth.shopId },
    cache: "no-store",
  });
  if (!response.ok) throw new PairingRequestError(response.status);
  return response;
}

export async function createSellerPairingCode(auth: Auth): Promise<SellerPairingCode> {
  return (await (await call(auth, "/v1/ingest/pairing-codes", "POST")).json()) as SellerPairingCode;
}

export async function listSellerIngestTokens(auth: Auth): Promise<readonly SellerIngestToken[]> {
  const body = (await (await call(auth, "/v1/ingest/tokens", "GET")).json()) as { data?: SellerIngestToken[] };
  return body.data ?? [];
}

export async function revokeSellerIngestToken(auth: Auth, tokenId: string): Promise<void> {
  await call(auth, `/v1/ingest/tokens/${encodeURIComponent(tokenId)}`, "DELETE");
}

/** One dataset of `/v1/ingest/shop-status`: what Juli last received from the Connector. */
export interface ConnectorDatasetStatus {
  readonly dataset: string;
  readonly last_ingest_at: string | null;
  readonly last_period_end: string | null;
  readonly drift: string;
}

export async function sellerConnectorStatus(auth: Auth): Promise<readonly ConnectorDatasetStatus[]> {
  const body = (await (await call(auth, "/v1/ingest/shop-status", "GET")).json()) as { datasets?: ConnectorDatasetStatus[] };
  return body.datasets ?? [];
}

/**
 * What the Connector sends, under the seller's names (the extension popup uses the same words,
 * Connector 0.3.17), grouped by the Seller Centre page it comes from. Datasets outside this list
 * (file uploads by Juli) are not the Connector's and are not listed on this page.
 */
export const CONNECTOR_DATASETS: readonly { readonly page: string; readonly items: readonly (readonly [string, string])[] }[] = [
  {
    page: "Phân Tích Bán Hàng",
    items: [
      ["traffic_overview", "Doanh số theo nguồn"],
      ["shop_traffic", "Truy cập shop"],
      ["shop_overview", "Tổng quan shop theo ngày"],
      ["product_period", "Hiệu quả sản phẩm 30 ngày"],
      ["item_traffic_sources", "Nguồn truy cập sản phẩm"],
    ],
  },
  {
    page: "Sản phẩm · Đơn hàng",
    items: [
      ["item_catalog", "Danh sách sản phẩm"],
      ["item_snapshot", "Giá và tồn kho sản phẩm"],
      ["order_lines", "Dòng đơn hàng"],
      ["order_income", "Doanh thu từng đơn"],
    ],
  },
  {
    page: "Kênh Marketing",
    items: [
      ["ads_campaign_daily", "Quảng cáo theo ngày"],
      ["ads_campaign_settings", "Cài đặt chiến dịch quảng cáo"],
      ["ads_campaign_detail", "Chi tiết chiến dịch quảng cáo"],
      ["ads_campaign_period", "Quảng cáo theo sản phẩm"],
      ["voucher_settings", "Voucher của shop"],
    ],
  },
  {
    page: "Tiếp Thị Liên Kết",
    items: [
      ["affiliate_order_lines", "Đơn KOL"],
      ["affiliate_partner_period", "KOL theo kỳ"],
      ["affiliate_shop_period", "Tiếp thị liên kết theo ngày"],
      ["affiliate_product_period", "Sản phẩm KOL theo kỳ"],
      ["affiliate_shop_campaigns", "Chiến dịch KOL"],
      ["affiliate_commission_period", "Hoa hồng KOL"],
      ["affiliate_content_period", "Nội dung KOL"],
      ["affiliate_bill_period", "Đối soát KOL"],
    ],
  },
  { page: "Tài khoản", items: [["shop_health_daily", "Sức khỏe tài khoản"]] },
];
