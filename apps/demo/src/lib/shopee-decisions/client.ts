import { ShopeeApiError } from "../shopee-analytics/client";
import type { Card, CardByCode, CardDetail, CardList, CompareResult, DecideResult, ExecutedResult, GenerateReport, LearningOverview, ManualInput, ManualResult, VariantInput } from "./types";

/**
 * The one client of the Shopee recommendation cards. The SAME screens run for the seller
 * (`/v1/demo/shopee/recommendations`, bearer + `X-Shop-Id`), for Juli Ops "Xem như shop" (reads
 * and what-if only) and for the Ops "Đề xuất" tab (`/v1/ops/shops/{id}/shopee/recommendations`,
 * bearer only, staff actions audited server-side). A screen takes a {@link RecoApi} and never
 * knows which one it holds.
 */

export const DEMO_RECO_BASE = "/v1/demo/shopee/recommendations" as const;

export function opsRecoBase(shopId: string): string {
  return `/v1/ops/shops/${encodeURIComponent(shopId)}/shopee/recommendations`;
}

export interface ListQuery {
  readonly family?: string;
  readonly section?: string;
  readonly status?: string;
  readonly xepTheo?: string;
  /** P91: every open card of this product (the Sản phẩm › Đề xuất tab). */
  readonly productId?: string;
  /** `top` (default): the product's #1 card only (Quyết định); `all`: every card, with its queue place. */
  readonly queue?: "top" | "all";
}

export interface ApproveInput {
  readonly inputs?: Readonly<Record<string, unknown>> | null;
  readonly note?: string | null;
  /** P91: which version is approved (1-based; omitted = 1). */
  readonly chosenVersion?: number;
  /** P91: a floor / spend-cap breach never blocks; it needs this yes (422 `reco_breach_unacknowledged` otherwise). */
  readonly acknowledgeBreaches?: boolean;
}

export interface ExecutedInput {
  /** The voucher's id in Seller Centre (required to read a voucher back). */
  readonly voucherId?: string | null;
  readonly evidenceRef?: string | null;
  readonly executedAt?: string | null;
}

export interface WithdrawInput {
  readonly reasonCode: string;
  readonly note?: string | null;
}

export interface WithdrawManyResult {
  readonly withdrawn: readonly string[];
  readonly refused: readonly { readonly id: string; readonly error: string; readonly status: number }[];
}

export interface RecoApi {
  list(q?: ListQuery): Promise<CardList>;
  detail(id: string): Promise<CardDetail>;
  /** Recompute with other inputs. Seller: recorded as `whatif_adjusted`. Ops: nothing recorded. P91: `version` (1-based) moves that version only. */
  whatif(id: string, inputs: Readonly<Record<string, unknown>>, version?: number): Promise<Card>;
  approve(id: string, body: ApproveInput): Promise<DecideResult>;
  /** P91 D-3: 2-4 variants side by side; saves nothing. */
  compare(variants: readonly VariantInput[], asOf?: string | null): Promise<CompareResult>;
  /** P91 D-3: save `variants[chosen]` as a card (`origin = "manual"`), the others as its versions. */
  createManual(body: ManualInput): Promise<ManualResult>;
  /** P91 D-5, Juli Ops only: one card by `JC-…` or `JC-…-Vn`. */
  byCode(code: string): Promise<CardByCode>;
  requestChange(id: string, note: string): Promise<DecideResult>;
  dismiss(id: string, body: { readonly reasonCode?: string | null; readonly note?: string | null }): Promise<DecideResult>;
  executed(id: string, body?: ExecutedInput): Promise<ExecutedResult>;
  // Juli Ops only
  generate(body: { readonly topN?: number; readonly mega?: { readonly start: string; readonly end: string; readonly budgetCapPerDay?: number | null } | null }): Promise<GenerateReport>;
  publish(cardIds?: readonly string[] | null): Promise<{ readonly sent: readonly string[] }>;
  /** "Gỡ thẻ": close the card (withdrawn) with a reason; the product's next card moves up. */
  withdraw(id: string, body?: WithdrawInput): Promise<{ readonly id: string; readonly status: string }>;
  /** Bulk "Gỡ thẻ": each card closes on its own; the ones that could not are listed. */
  withdrawMany(ids: readonly string[], body: WithdrawInput): Promise<WithdrawManyResult>;
  rerunStale(): Promise<Readonly<Record<string, number>>>;
  learning(): Promise<LearningOverview>;
  learningRun(): Promise<Readonly<Record<string, unknown>>>;
}

function errorOf(status: number, payload: unknown): ShopeeApiError {
  let code = "";
  let message = `HTTP ${status}`;
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") message = detail;
    else if (typeof detail === "object" && detail !== null) {
      const d = detail as { code?: unknown; message?: unknown };
      if (typeof d.code === "string") code = d.code;
      if (typeof d.message === "string") message = d.message;
      return new ShopeeApiError(status, code, message, detail as Readonly<Record<string, unknown>>);
    }
  }
  return new ShopeeApiError(status, code, message);
}

export interface RecoClientOptions {
  /** `DEMO_RECO_BASE` or `opsRecoBase(shopId)`. */
  readonly base: string;
  readonly token: string;
  /** Seller scope only: the acting shop (`X-Shop-Id`). */
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

export function createRecoApi(options: RecoClientOptions): RecoApi {
  const { base, token, shopId, fetchImpl } = options;
  async function call<T>(method: "GET" | "POST", path: string, body?: unknown, params?: URLSearchParams): Promise<T> {
    const doFetch = fetchImpl ?? fetch;
    const qs = params?.toString();
    const response = await doFetch(`${base}${path}${qs ? `?${qs}` : ""}`, {
      method,
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(shopId ? { "X-Shop-Id": shopId } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      cache: "no-store",
    });
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) throw errorOf(response.status, payload);
    return payload as T;
  }
  const id = (cardId: string) => `/${encodeURIComponent(cardId)}`;
  return {
    list: (q = {}) => {
      const p = new URLSearchParams();
      if (q.family) p.set("family", q.family);
      if (q.section) p.set("section", q.section);
      if (q.status) p.set("status", q.status);
      if (q.xepTheo) p.set("xep_theo", q.xepTheo);
      if (q.productId) p.set("product_id", q.productId);
      if (q.queue) p.set("queue", q.queue);
      return call<CardList>("GET", "", undefined, p);
    },
    detail: (cardId) => call<CardDetail>("GET", id(cardId)),
    whatif: async (cardId, inputs, version) => (await call<{ card: Card }>("POST", `${id(cardId)}/whatif`, { inputs, ...(version ? { version } : {}) })).card,
    approve: (cardId, body) =>
      call<DecideResult>("POST", `${id(cardId)}/approve`, {
        inputs: body.inputs ?? null,
        note: body.note ?? null,
        chosen_version: body.chosenVersion ?? 1,
        acknowledge_breaches: body.acknowledgeBreaches ?? false,
      }),
    compare: (variants, asOf) => call<CompareResult>("POST", "/compare", { variants, ...(asOf ? { as_of: asOf } : {}) }),
    createManual: (body) =>
      call<ManualResult>("POST", "/manual", {
        variants: body.variants,
        chosen: body.chosen,
        primary: body.primary,
        acknowledge_breaches: body.acknowledgeBreaches,
      }),
    byCode: (code) => call<CardByCode>("GET", `/code/${encodeURIComponent(code)}`),
    requestChange: (cardId, note) => call<DecideResult>("POST", `${id(cardId)}/request-change`, { note }),
    dismiss: (cardId, body) => call<DecideResult>("POST", `${id(cardId)}/dismiss`, { reason_code: body.reasonCode ?? null, note: body.note ?? null }),
    executed: (cardId, body = {}) =>
      call<ExecutedResult>("POST", `${id(cardId)}/executed`, {
        executed_at: body.executedAt ?? null,
        voucher_id: body.voucherId ?? null,
        evidence_ref: body.evidenceRef ?? null,
      }),
    generate: (body) =>
      call<GenerateReport>("POST", "/generate", {
        top_n: body.topN ?? 10,
        ...(body.mega ? { mega: { start: body.mega.start, end: body.mega.end, budget_cap_per_day: body.mega.budgetCapPerDay ?? null } } : {}),
      }),
    publish: (cardIds) => call<{ sent: string[] }>("POST", "/publish", { card_ids: cardIds ?? null }),
    withdraw: (cardId, body) => call<{ id: string; status: string }>("POST", `${id(cardId)}/withdraw`, body ? { reason_code: body.reasonCode, note: body.note ?? null } : {}),
    withdrawMany: (cardIds, body) => call<WithdrawManyResult>("POST", "/withdraw", { card_ids: cardIds, reason_code: body.reasonCode, note: body.note ?? null }),
    rerunStale: () => call<Record<string, number>>("POST", "/rerun-stale", {}),
    learning: () => call<LearningOverview>("GET", "/learning"),
    learningRun: () => call<Record<string, unknown>>("POST", "/learning/run", {}),
  };
}
