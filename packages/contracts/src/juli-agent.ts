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

export type JuliStopReason = "within_noise" | "unexplained" | "data_stale" | "data_missing" | "explained";

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

export type JuliDataKind = "metric_total" | "top_products" | "daily_trend" | "channel_breakdown";

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
  readonly item: "metric" | "window" | "product" | "chain";
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
  const record = raw as Record<string, unknown>;
  const type = (typeof record.type === "string" ? record.type : eventName) ?? null;
  if (type === null || !(JULI_EVENT_TYPES as readonly string[]).includes(type)) return null;
  let data: unknown;
  if (typeof record.data === "object" && record.data !== null && !Array.isArray(record.data)) {
    data = record.data;
  } else {
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
  readonly title: string;
  /** ISO timestamp of the last message. */
  readonly updated_at: string;
}

export interface JuliStoredMessage {
  readonly id: string;
  readonly question: string;
  readonly events: readonly JuliAgentEvent[];
  readonly created_at: string;
  /** The "Số liệu đến dd/mm" line of the saved answer. */
  readonly data_until_vi?: string;
  /** The JC code of a card this answer sent. */
  readonly sent_card_code?: string;
}

export interface JuliConversation {
  readonly id: string;
  readonly title: string;
  readonly messages: readonly JuliStoredMessage[];
}

export interface JuliSendCardResponse {
  readonly card_code: string;
}
