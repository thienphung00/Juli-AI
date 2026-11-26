/**
 * Juli tab (analytics agent) event types: the browser mirror of the backend's
 * `AgentEvent` (CONTRACT.md, batch-1120-juli-tab). Every event is `{ type, data }`.
 * Labels (`*_vi`) are written by the backend per platform; the UI never maps source keys itself.
 */

export type JuliDeltaDir = "up" | "down" | "flat";

export interface JuliDelta {
  readonly dir: JuliDeltaDir;
  readonly text_vi: string;
}

export type JuliLinkKind = "metric" | "channel" | "product" | "ads" | "card";

export interface JuliLink {
  readonly kind: JuliLinkKind;
  readonly metric?: string;
  readonly channel?: string;
  readonly item_id?: string;
  readonly card_code?: string;
  /** ISO dates (yyyy-mm-dd) of the window the link carries. */
  readonly from?: string;
  readonly to?: string;
}

export interface JuliPathStep {
  readonly label_vi: string;
  readonly value_vi: string;
  readonly delta: JuliDelta | null;
  readonly link: JuliLink;
}

export type JuliStopReason = "within_noise" | "unexplained" | "data_stale" | "data_missing" | "explained" | "not_applicable";

export interface JuliCardVersion {
  readonly label_vi: string;
  readonly inputs: Readonly<Record<string, unknown>>;
  readonly recommended: boolean;
  readonly estimable: boolean;
  readonly gmv_p50: number | null;
  readonly profit_p50: number | null;
  readonly days: number;
  readonly cost_total: number | null;
  readonly cost_text_vi: string;
  readonly margin_before_pct: number | null;
  readonly margin_after_pct: number | null;
}

export interface JuliDataRow {
  readonly label_vi: string;
  readonly value_vi: string;
  readonly detail_vi?: string;
  readonly missing?: boolean;
  readonly link?: JuliLink;
}

export interface JuliSeriesPoint {
  readonly label_vi: string;
  readonly value: number;
  readonly value_vi: string;
  readonly missing?: boolean;
}

/** `metric_list`: the 4th figure on of one answer, as one table (owner #110 rule 5). */
export type JuliDataKind = "metric_total" | "metric_list" | "top_products" | "daily_trend" | "channel_breakdown";

export interface JuliChoiceOption {
  readonly label_vi: string;
  readonly value: string;
}

export interface JuliStatusData {
  readonly key: "thinking" | "checking_data" | "comparing" | "finding_cause" | "preparing_card";
  readonly text_vi: string;
}
export interface JuliRestatedData {
  readonly text_vi: string;
}
export interface JuliTextData {
  readonly text: string;
}
export interface JuliPathData {
  readonly steps: readonly JuliPathStep[];
}
export interface JuliLabelData {
  readonly stop_reason: JuliStopReason;
  readonly text_vi: string;
  readonly detail_vi?: string;
}
export interface JuliDataAnswerData {
  readonly kind: JuliDataKind;
  readonly title_vi: string;
  readonly value?: string;
  readonly delta?: JuliDelta;
  readonly window_vi: string;
  readonly rows?: readonly JuliDataRow[];
  readonly series?: readonly JuliSeriesPoint[];
  readonly fresh_vi: string;
  readonly sale_vi?: string;
  /** A tile's one comparison line ("▲ 20,0% so với 800đ", "Kỳ trước chưa đủ dữ liệu"). */
  readonly compare_vi?: string;
  /** A list with no row: no box is drawn (the lead says it, #110 rule 7). */
  readonly empty?: boolean;
}
/** The answer's one period line, on top (#110 rule 2): period, data day, sale days. */
export interface JuliMetaData {
  readonly window_vi?: string;
  readonly fresh_vi?: string;
  readonly sale_vi?: string;
}
/** The answer's first sentence, its main number in it (#110 rule 1). */
export interface JuliLeadData {
  readonly text_vi: string;
}
export interface JuliCardData {
  readonly draft_ref: string;
  readonly kind: string;
  readonly kind_vi: string;
  readonly item_id?: string;
  readonly item_name?: string;
  readonly title_vi: string;
  readonly versions: readonly JuliCardVersion[];
  readonly recommendation_vi: string;
}
export interface JuliNoCardData {
  readonly reason_vi: string;
  readonly existing_card_code?: string;
}
export interface JuliNeedsChoiceData {
  /** "template": the Jev outage fallback; options are the template keys. */
  readonly item: "metric" | "window" | "product" | "chain" | "scope" | "template";
  readonly question_vi: string;
  readonly options: readonly JuliChoiceOption[];
  readonly pending: Readonly<Record<string, unknown>>;
}
export interface JuliUnsupportedData {
  readonly text_vi: string;
  readonly templates: readonly string[];
  readonly switch_platform?: "tiktok" | "shopee";
}
export interface JuliIntentBlockData {
  readonly index: number;
  readonly total: number;
  readonly title_vi: string;
}
export interface JuliMoreData {
  readonly items: readonly { readonly label_vi: string; readonly text: string }[];
}
export interface JuliDoneData {
  readonly stop_reasons: readonly string[];
  readonly cost_usd?: number;
  readonly ms?: number;
  readonly data_until_vi?: string;
}
export interface JuliErrorData {
  readonly code: "busy" | "failed";
}

export interface JuliEventMap {
  status: JuliStatusData;
  restated: JuliRestatedData;
  text_delta: JuliTextData;
  text_replace: JuliTextData;
  path: JuliPathData;
  label: JuliLabelData;
  data_answer: JuliDataAnswerData;
  meta: JuliMetaData;
  lead: JuliLeadData;
  card: JuliCardData;
  no_card: JuliNoCardData;
  needs_choice: JuliNeedsChoiceData;
  unsupported: JuliUnsupportedData;
  intent_block: JuliIntentBlockData;
  more: JuliMoreData;
  done: JuliDoneData;
  error: JuliErrorData;
}

export type JuliEventType = keyof JuliEventMap;

export type JuliAgentEvent = {
  [K in JuliEventType]: { readonly type: K; readonly data: JuliEventMap[K] };
}[JuliEventType];

export const JULI_EVENT_TYPES: readonly JuliEventType[] = [
  "status",
  "restated",
  "text_delta",
  "text_replace",
  "path",
  "label",
  "data_answer",
  "meta",
  "lead",
  "card",
  "no_card",
  "needs_choice",
  "unsupported",
  "intent_block",
  "more",
  "done",
  "error",
];

export function isJuliTerminalEvent(event: JuliAgentEvent): boolean {
  return event.type === "done" || event.type === "error";
}

/**
 * Normalises a decoded SSE frame into `{ type, data }`. Accepts `{type, data}`, a flat
 * `{type, ...payload}`, or a bare payload with the type taken from the SSE `event:` line.
 * Returns `null` for an unknown type so the caller can skip it without crashing.
 */
export function parseJuliEvent(raw: unknown, eventName?: string | null): JuliAgentEvent | null {
  if (typeof raw !== "object" || raw === null) return null;
  const known = (name: string | null | undefined): name is JuliEventType =>
    typeof name === "string" && (JULI_EVENT_TYPES as readonly string[]).includes(name);
  // Primary wire format (agent_runs `format_sse`): `event: <type>` + `data: <payload JSON>`.
  if (known(eventName)) return { type: eventName, data: raw } as JuliAgentEvent;
  const record = raw as Record<string, unknown>;
  const type = typeof record.type === "string" ? record.type : null;
  if (!known(type)) return null;
  let data: unknown;
  if (typeof record.payload === "object" && record.payload !== null) data = record.payload;
  else if (typeof record.data === "object" && record.data !== null && !Array.isArray(record.data)) data = record.data;
  else {
    const { type: _type, ...rest } = record;
    void _type;
    data = rest;
  }
  return { type, data } as JuliAgentEvent;
}

// ── HTTP API (`/v1/demo/juli`) ───────────────────────────────────────────

export interface JuliTemplate {
  readonly key: string;
  readonly label_vi: string;
}

/** `GET /templates`. */
export interface JuliTemplatesResponse {
  readonly templates: readonly JuliTemplate[];
  readonly shop_state: { readonly read_only: boolean };
}

export type JuliDraftStatus = "drafted" | "sent" | "dismissed" | string;

export interface JuliStoredCard {
  readonly draft_ref: string;
  readonly status: JuliDraftStatus;
  readonly sent_card_code: string | null;
  readonly version_label: string | null;
}

export interface JuliAskRequest {
  readonly conversation_id?: string;
  readonly text?: string;
  readonly template?: string;
  readonly choice?: { readonly item: string; readonly value: string };
}

export interface JuliAskResponse {
  readonly conversation_id: string;
  readonly message_id: string;
}

export interface JuliConversationSummary {
  readonly id: string;
  readonly platform?: "shopee" | "tiktok";
  readonly title: string;
  readonly created_at?: string;
  /** ISO timestamp of the last message. */
  readonly updated_at: string;
}

export interface JuliStoredMessage {
  readonly id: string;
  readonly question: string;
  /** The template key when the seller tapped a template (the page maps it to its label). */
  readonly template?: string;
  readonly events: readonly JuliAgentEvent[];
  readonly created_at: string;
  readonly cards?: readonly JuliStoredCard[];
  /** The "Số liệu đến dd/mm" line of the saved answer. */
  readonly data_until_vi?: string;
}

export interface JuliConversation {
  readonly id: string;
  readonly title: string;
  readonly messages: readonly JuliStoredMessage[];
}

export interface JuliSendCardResponse {
  readonly card_code: string | null;
  readonly card_id?: string | null;
  readonly status?: string | null;
  readonly already_sent?: boolean;
}

/** A message of `GET /conversations/{id}` as the server sends it (user rows and assistant rows). */
export interface JuliServerMessage {
  readonly id: string;
  readonly role: "user" | "assistant";
  readonly status: string;
  readonly created_at: string;
  readonly text?: string | null;
  readonly template?: string | null;
  readonly choice?: { readonly item: string; readonly value: string } | null;
  readonly events?: readonly { readonly seq: number; readonly type: string; readonly payload: unknown }[];
  readonly stop_reasons?: readonly string[];
  readonly cost_usd?: number | null;
  readonly ms?: number | null;
  readonly data_until_vi?: string | null;
  readonly cards?: readonly JuliStoredCard[];
}
