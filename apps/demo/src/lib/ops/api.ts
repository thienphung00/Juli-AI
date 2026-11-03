import { readAuthSession } from "../supabase-auth";
import type {
  AuditEntry,
  AuditKind,
  CardGroupCreate,
  CardGroupsPage,
  ContractShop,
  CostsPage,
  Deltas,
  DisconnectResult,
  IngestTokenRow,
  Invite,
  OpsMe,
  Overview,
  PairingCode,
  Scenario,
  ShopConsent,
  ShopSettings,
  ShopSettingsPage,
  ShopTermsPage,
  ShopeeAds,
  ShopeeFlows,
  ShopeeProducts,
  ShopeePromotions,
  ShopeeQuery,
  SimulationPage,
  SystemCost,
  TermsPage,
  TrialSignup,
  TrialSignupStatus,
  TrialSignupsPage,
  ViewSession,
  ApprovalCreate,
  ExecutionCreate,
  ProposalCreate,
  ShopProposalRow,
  KeywordMetricsUploaded,
  KeywordSeedsGenerated,
  OrderLinesUploaded,
  OrderRefKeyResponse,
  ShopeeKeywordBoard,
} from "./types";

/**
 * The Juli Ops client (`/v1/ops/*`, P16). Same-origin: on `ops.app-juli.com`
 * nginx proxies `/v1/` to the API, and Cloudflare Access adds the
 * `Cf-Access-Jwt-Assertion` header on the way in — the page never sees it.
 * The Supabase session is the ops host's own (localStorage is per origin).
 */
export const OPS_API = "/v1/ops" as const;

/** FastAPI `detail` is a string or `{code, message}`; never "[object Object]". */
export function detailText(detail: unknown): string {
  if (typeof detail === "object" && detail !== null) {
    const { code, message } = detail as { code?: unknown; message?: unknown };
    if (typeof message === "string") return message;
    if (typeof code === "string") return code;
    return JSON.stringify(detail);
  }
  return String(detail);
}

export class OpsApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(`Ops API ${status}: ${detail}`);
    this.name = "OpsApiError";
  }
}

export interface OpsRequestOptions {
  readonly token?: string;
  readonly fetchImpl?: typeof fetch;
}

function tokenOf(options?: OpsRequestOptions): string {
  const token = options?.token ?? readAuthSession()?.accessToken;
  if (!token) throw new OpsApiError(401, "not signed in");
  return token;
}

export async function opsRequest<T>(
  path: string,
  init: { method?: string; body?: unknown } = {},
  options?: OpsRequestOptions,
): Promise<T> {
  const fetchImpl = options?.fetchImpl ?? fetch;
  const response = await fetchImpl(`${OPS_API}${path}`, {
    method: init.method ?? "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${tokenOf(options)}`,
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
  });
  if (response.status === 204) return undefined as T;
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? detailText((payload as { detail: unknown }).detail)
        : response.statusText;
    throw new OpsApiError(response.status, detail);
  }
  return payload as T;
}

const shopPath = (shopId: string) => `/shops/${encodeURIComponent(shopId)}`;

export const opsApi = {
  me: (o?: OpsRequestOptions) => opsRequest<OpsMe>("/me", {}, o),
  overview: (o?: OpsRequestOptions) => opsRequest<Overview>("/overview", {}, o),
  /** D27.1: recompute every row now (Vận hành / Admin; Xem gets 403). */
  refreshOverview: (o?: OpsRequestOptions) => opsRequest<Overview>("/overview/refresh", { method: "POST" }, o),
  audit: (shopId: string | null, kind?: AuditKind | null, o?: OpsRequestOptions) => {
    const q = new URLSearchParams();
    if (shopId) q.set("shop_id", shopId);
    if (kind) q.set("kind", kind);
    const qs = q.toString();
    return opsRequest<{ data: AuditEntry[] }>(qs ? `/audit?${qs}` : "/audit", {}, o);
  },
  staff: (o?: OpsRequestOptions) =>
    opsRequest<{ data: { id: string; email: string; role: string; role_label: string; active: boolean; signed_in: boolean }[] }>(
      "/staff",
      {},
      o,
    ),
  putStaff: (body: { email: string; role: string; active: boolean }, o?: OpsRequestOptions) =>
    opsRequest("/staff", { method: "PUT", body }, o),
  settings: (shopId: string, o?: OpsRequestOptions) => opsRequest<ShopSettingsPage>(`${shopPath(shopId)}/settings`, {}, o),
  putSettings: (shopId: string, changes: Record<string, unknown>, o?: OpsRequestOptions) =>
    opsRequest<{ settings: ShopSettings }>(`${shopPath(shopId)}/settings`, { method: "PUT", body: { changes } }, o),
  resetSettings: (shopId: string, o?: OpsRequestOptions) =>
    opsRequest<{ settings: ShopSettings }>(`${shopPath(shopId)}/settings/reset`, { method: "POST" }, o),
  invite: (shopId: string, email: string, keepOpsAccess: boolean, o?: OpsRequestOptions) =>
    opsRequest<{ data: Invite; email_sent: boolean; accept_url: string | null }>(
      `${shopPath(shopId)}/invites`,
      { method: "POST", body: { email, keep_ops_access: keepOpsAccess } },
      o,
    ),
  viewSession: (shopId: string, mode: "view" | "exit", o?: OpsRequestOptions) =>
    opsRequest<ViewSession>(`${shopPath(shopId)}/view-session`, { method: "POST", body: { mode } }, o),
  disconnect: (shopId: string, reason: string, confirmName: string, o?: OpsRequestOptions) =>
    opsRequest<{ data: DisconnectResult }>(
      `${shopPath(shopId)}/disconnect`,
      { method: "POST", body: { reason, confirm_name: confirmName } },
      o,
    ),
  simulation: (shopId: string, window: number, o?: OpsRequestOptions) =>
    opsRequest<SimulationPage>(`${shopPath(shopId)}/simulation?window=${window}`, {}, o),
  /** D27.1: recompute this shop's simulation numbers now (Xem gets 403). */
  refreshSimulation: (shopId: string, window: number, o?: OpsRequestOptions) =>
    opsRequest<SimulationPage>(`${shopPath(shopId)}/simulation/refresh?window=${window}`, { method: "POST" }, o),
  createScenario: (shopId: string, name: string, deltas: Deltas, isTarget: boolean, o?: OpsRequestOptions) =>
    opsRequest<{ data: Scenario }>(
      `${shopPath(shopId)}/scenarios`,
      { method: "POST", body: { name, deltas, is_target: isTarget } },
      o,
    ),
  setTarget: (shopId: string, scenarioId: string, o?: OpsRequestOptions) =>
    opsRequest<{ data: Scenario }>(
      `${shopPath(shopId)}/scenarios/${encodeURIComponent(scenarioId)}`,
      { method: "PATCH", body: { is_target: true } },
      o,
    ),
  /** D28.3 tab Chi phí: the month's system spend and every shop's own cap. */
  costs: (o?: OpsRequestOptions) => opsRequest<CostsPage>("/costs", {}, o),
  /** D28.3: the system figure alone (the banner on every Ops page). */
  costSystem: (o?: OpsRequestOptions) => opsRequest<{ system: SystemCost }>("/costs/system", {}, o),
  /** D28.3 "Sửa giới hạn" (Admin). */
  putSystemCap: (usd: number, o?: OpsRequestOptions) =>
    opsRequest<{ system: SystemCost }>("/costs/system-cap", { method: "PUT", body: { usd } }, o),
  /** D28.3 per-shop "Sửa" (Admin); `null` = back to the default. */
  putShopCap: (shopId: string, usd: number | null, o?: OpsRequestOptions) =>
    opsRequest<{ shop_id: string; cap_usd: number; is_custom: boolean }>(`${shopPath(shopId)}/openai-cap`, { method: "PUT", body: { usd } }, o),
  /** P30 (D34 / D39.3): the shop's card groups with their arms and day-14 verdicts. */
  groups: (shopId: string, o?: OpsRequestOptions) => opsRequest<CardGroupsPage>(`${shopPath(shopId)}/groups`, {}, o),
  /** P36 (D45.1): a group made in Ops (e.g. "Quy cách mới"); Vận hành / Admin; audited `card_group_create`. */
  createGroup: (shopId: string, body: CardGroupCreate, o?: OpsRequestOptions) =>
    opsRequest<CardGroupsPage & { created: string }>(`${shopPath(shopId)}/groups`, { method: "POST", body }, o),
  /** P36 (D45.3): the group's one-line "lý do chọn thử nghiệm" (`null` clears); audited `card_group_reason`. */
  setGroupReason: (shopId: string, groupId: string, reason: string | null, o?: OpsRequestOptions) =>
    opsRequest<CardGroupsPage>(`${shopPath(shopId)}/groups/${encodeURIComponent(groupId)}`, { method: "PATCH", body: { reason } }, o),
  /** D28.4 tab Thời hạn. */
  terms: (o?: OpsRequestOptions) => opsRequest<TermsPage>("/terms", {}, o),
  shopTerms: (shopId: string, o?: OpsRequestOptions) => opsRequest<ShopTermsPage>(`${shopPath(shopId)}/terms`, {}, o),
  /** D28.4 "Gói 30 / 365 ngày" (Admin): source = contract, reference = số hợp đồng. */
  addTerm: (shopId: string, days: 30 | 365, reference: string, o?: OpsRequestOptions) =>
    opsRequest<ShopTermsPage>(`${shopPath(shopId)}/terms`, { method: "POST", body: { days, reference } }, o),
  /** P33-F tab "Đăng ký dùng thử" (Vận hành / Admin; Xem gets 403). */
  trialSignups: (status: TrialSignupStatus | null, o?: OpsRequestOptions) =>
    opsRequest<TrialSignupsPage>(status ? `/trial-signups?status=${status}` : "/trial-signups", {}, o),
  /** P33-F: set a sign-up's status (audited `trial_signup_status`). */
  setTrialSignupStatus: (id: string, status: TrialSignupStatus, o?: OpsRequestOptions) =>
    opsRequest<{ data: TrialSignup }>(`/trial-signups/${encodeURIComponent(id)}`, { method: "PATCH", body: { status } }, o),
  /** ADR-118 "Thêm shop hợp đồng" (Vận hành / Admin): a Shopee shop with no seller login. */
  createContractShop: (shopName: string, shopeeShopId: string | null, o?: OpsRequestOptions) =>
    opsRequest<{ shop: ContractShop }>(
      "/contract-shops",
      { method: "POST", body: { shop_name: shopName, shopee_shop_id: shopeeShopId } },
      o,
    ),
  /** ADR-118: the shop's data-use consent; `contract_client` decides whether "Bật" shows. */
  consent: (shopId: string, o?: OpsRequestOptions) => opsRequest<ShopConsent>(`${shopPath(shopId)}/consent`, {}, o),
  /** ADR-118 "Bật" (Vận hành / Admin): no fields; audited `consent_enable`. */
  enableConsent: (shopId: string, o?: OpsRequestOptions) =>
    opsRequest<ShopConsent>(`${shopPath(shopId)}/consent`, { method: "POST" }, o),
  /** ADR-118 "Tạo mã kết nối" (Vận hành / Admin): a 10-minute, single-use code; 409 before "Bật". */
  createPairingCode: (shopId: string, o?: OpsRequestOptions) =>
    opsRequest<PairingCode>(`${shopPath(shopId)}/pairing-codes`, { method: "POST" }, o),
  /** ADR-118: the shop's connected sources (never the token itself). */
  ingestTokens: (shopId: string, o?: OpsRequestOptions) =>
    opsRequest<{ data: IngestTokenRow[] }>(`${shopPath(shopId)}/ingest-tokens`, {}, o),
  /** ADR-118 "Thu hồi" (Vận hành / Admin); audited `ingest_token_revoke`. */
  revokeIngestToken: (shopId: string, tokenId: string, o?: OpsRequestOptions) =>
    opsRequest<void>(`${shopPath(shopId)}/ingest-tokens/${encodeURIComponent(tokenId)}`, { method: "DELETE" }, o),
  /** ADR-118 "Chu kỳ": the shop's proposals with approvals and executions, newest first. */
  proposals: (shopId: string, o?: OpsRequestOptions) =>
    opsRequest<{ proposals: ShopProposalRow[] }>(`${shopPath(shopId)}/proposals`, {}, o),
  /** ADR-118 (Vận hành / Admin): a new draft; audited `proposal_create`. */
  createProposal: (shopId: string, body: ProposalCreate, o?: OpsRequestOptions) =>
    opsRequest<{ proposal: ShopProposalRow }>(`${shopPath(shopId)}/proposals`, { method: "POST", body }, o),
  /** ADR-118: draft → sent (the text is frozen). */
  sendProposal: (shopId: string, proposalId: string, o?: OpsRequestOptions) =>
    opsRequest<{ proposal_id: string; status: string }>(`${shopPath(shopId)}/proposals/${encodeURIComponent(proposalId)}/send`, { method: "POST" }, o),
  /** ADR-118: withdraw a proposal that has not been executed. */
  withdrawProposal: (shopId: string, proposalId: string, o?: OpsRequestOptions) =>
    opsRequest<{ proposal_id: string; status: string }>(`${shopPath(shopId)}/proposals/${encodeURIComponent(proposalId)}/withdraw`, { method: "POST" }, o),
  /** ADR-118: the client's decision from an email / document, with the evidence pointer. */
  recordApproval: (shopId: string, proposalId: string, body: ApprovalCreate, o?: OpsRequestOptions) =>
    opsRequest<{ proposal_id: string; status: string }>(`${shopPath(shopId)}/proposals/${encodeURIComponent(proposalId)}/approvals`, { method: "POST", body }, o),
  /** ADR-118: the change was made on Shopee. */
  recordExecution: (shopId: string, proposalId: string, body: ExecutionCreate, o?: OpsRequestOptions) =>
    opsRequest<{ proposal_id: string; status: string }>(`${shopPath(shopId)}/proposals/${encodeURIComponent(proposalId)}/executions`, { method: "POST", body }, o),
  /** ADR-118 D81 "Tính lại" (Vận hành / Admin): measure one executed proposal now; audited `proposal_measure`. */
  measureProposal: (shopId: string, proposalId: string, o?: OpsRequestOptions) =>
    opsRequest<{ proposal_id: string; written: number; measured: number }>(`${shopPath(shopId)}/proposals/${encodeURIComponent(proposalId)}/measure`, { method: "POST" }, o),
  /** ADR-117 step 4, Sản phẩm + luồng: the funnel per product for one export period (Xem+; 409 for a non-Shopee shop). */
  shopeeProducts: (shopId: string, q: ShopeeQuery = {}, o?: OpsRequestOptions) =>
    opsRequest<ShopeeProducts>(`${shopPath(shopId)}/shopee/products${shopeeQuery(q, true)}`, {}, o),
  /** Sản phẩm + luồng: GMV by flow; "Trang shop" is a child of "Thẻ sản phẩm" (G3). */
  shopeeFlows: (shopId: string, q: ShopeeQuery = {}, o?: OpsRequestOptions) =>
    opsRequest<ShopeeFlows>(`${shopPath(shopId)}/shopee/flows${shopeeQuery(q)}`, {}, o),
  /** Quảng cáo + khuyến mãi: cost / orders / ROAS by ad type, monthly and daily, with the low-ROAS alert. */
  shopeeAds: (shopId: string, q: ShopeeQuery = {}, o?: OpsRequestOptions) =>
    opsRequest<ShopeeAds>(`${shopPath(shopId)}/shopee/ads${shopeeQuery(q)}`, {}, o),
  /** Quảng cáo + khuyến mãi: the promotion programme timeline. */
  shopeePromotions: (shopId: string, q: ShopeeQuery = {}, o?: OpsRequestOptions) =>
    opsRequest<ShopeePromotions>(`${shopPath(shopId)}/shopee/promotions${shopeeQuery(q)}`, {}, o),
  /** ADR-119, Từ khóa: keyword combinations, metrics, coverage and title candidates (Xem+). */
  shopeeKeywords: (shopId: string, minVolume?: number, o?: OpsRequestOptions) =>
    opsRequest<ShopeeKeywordBoard>(`${shopPath(shopId)}/shopee/keywords${minVolume !== undefined ? `?min_volume=${minVolume}` : ""}`, {}, o),
  /** "Tạo từ khóa từ tiêu đề" (Vận hành); audited `keyword_seeds_generate`. */
  generateKeywordSeeds: (shopId: string, brand: string | null, o?: OpsRequestOptions) =>
    opsRequest<KeywordSeedsGenerated>(`${shopPath(shopId)}/shopee/keywords/seeds/generate`, { method: "POST", body: { brand } }, o),
  /** Keep or drop one combination (Vận hành); audited `keyword_seed_toggle`. */
  setKeywordSeed: (shopId: string, seedId: string, enabled: boolean, o?: OpsRequestOptions) =>
    opsRequest<{ seed: { id: string; keyword: string; enabled: boolean } }>(`${shopPath(shopId)}/shopee/keywords/seeds/${encodeURIComponent(seedId)}`, { method: "PUT", body: { enabled } }, o),
  /** The owner's weekly shopeeanalytics.com upload, one record per JSONL line (Vận hành; public data, no shop). */
  uploadKeywordMetrics: (records: unknown[], o?: OpsRequestOptions) =>
    opsRequest<KeywordMetricsUploaded>("/market/keyword-metrics", { method: "POST", body: { records } }, o),
  /** P90 step 2, Đơn hàng: the shop's order_ref key for ONE upload (Vận hành; `no-store`, audited without the key). */
  orderRefKey: (shopId: string, o?: OpsRequestOptions) =>
    opsRequest<OrderRefKeyResponse>(`${shopPath(shopId)}/shopee/orders/ref-key`, {}, o),
  /** PII-free order lines, at most 1 000 per call (Vận hành; audited `orders_upload` with counts only). */
  uploadOrderLines: (shopId: string, lines: readonly unknown[], o?: OpsRequestOptions) =>
    opsRequest<OrderLinesUploaded>(`${shopPath(shopId)}/shopee/orders/upload`, { method: "POST", body: { lines } }, o),
};

export type OpsApi = typeof opsApi;

/** The Shopee dashboards' query string; the `products` route takes a period, the others a day range. */
function shopeeQuery(q: ShopeeQuery, period = false): string {
  const params = new URLSearchParams();
  if (q.orderType) params.set("order_type", q.orderType);
  if (period) {
    if (q.periodFrom && q.periodTo) {
      params.set("period_from", q.periodFrom);
      params.set("period_to", q.periodTo);
    }
  } else {
    if (q.from) params.set("from", q.from);
    if (q.to) params.set("to", q.to);
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}
