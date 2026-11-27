/**
 * Folds one answer's event stream into the view the answer renders. Pure: the same events give
 * the same view, so a replayed prefix after a reconnect, a saved answer and a live one all agree.
 */
import type {
  JuliAgentEvent,
  JuliCardData,
  JuliDataAnswerData,
  JuliLabelData,
  JuliMetaData,
  JuliNeedsChoiceData,
  JuliNoCardData,
  JuliPathStep,
  JuliUnsupportedData,
  JuliEventMap,
} from "@juli/contracts";

export interface AnswerBlockView {
  readonly title: string | null;
  /** The block's own period line, only when it differs from the answer's (#110 rule 2). */
  readonly meta: JuliMetaData | null;
  /** The block's first sentence, its main number in it (#110 rule 1). */
  readonly lead: string | null;
  readonly text: string;
  /** The text as streamed (the shown `text` drops its restated first line). */
  readonly rawText: string;
  readonly path: readonly JuliPathStep[] | null;
  readonly label: JuliLabelData | null;
  readonly dataAnswers: readonly JuliDataAnswerData[];
  readonly card: JuliCardData | null;
  readonly noCard: JuliNoCardData | null;
  readonly needsChoice: JuliNeedsChoiceData | null;
  readonly unsupported: JuliUnsupportedData | null;
}

export interface AnswerView {
  /** "Đang tìm hiểu: …", the first line of every answer. */
  readonly restated: string | null;
  /** The one status line (the current non-text step). */
  readonly status: JuliEventMap["status"] | null;
  /** Steps that finished, in order (the "thinking" step is the restated line itself). */
  readonly doneSteps: readonly JuliEventMap["status"][];
  readonly blocks: readonly AnswerBlockView[];
  readonly more: JuliEventMap["more"]["items"];
  readonly finished: boolean;
  readonly errorCode: "busy" | "failed" | null;
  /** The answer's own freshness line when it carries one ("Số liệu đến hết dd/mm"). */
  readonly freshVi: string | null;
  /** The one period line on top: the backend's `meta`, else (an answer saved before #110) the
   * first data answer's period, data day and sale days. */
  readonly meta: JuliMetaData | null;
}

export const RESTATED_PREFIX = "Đang tìm hiểu: ";

const EMPTY_BLOCK: AnswerBlockView = {
  title: null,
  meta: null,
  lead: null,
  text: "",
  rawText: "",
  path: null,
  label: null,
  dataAnswers: [],
  card: null,
  noCard: null,
  needsChoice: null,
  unsupported: null,
};

function isEmptyBlock(b: AnswerBlockView): boolean {
  return (
    b.title === null &&
    b.meta === null &&
    b.lead === null &&
    b.rawText === "" &&
    b.path === null &&
    b.label === null &&
    b.dataAnswers.length === 0 &&
    b.card === null &&
    b.noCard === null &&
    b.needsChoice === null &&
    b.unsupported === null
  );
}

export function reduceAnswer(events: readonly JuliAgentEvent[]): AnswerView {
  let restated: string | null = null;
  let status: AnswerView["status"] = null;
  let doneSteps: JuliEventMap["status"][] = [];
  let blocks: AnswerBlockView[] = [{ ...EMPTY_BLOCK }];
  let more: JuliEventMap["more"]["items"] = [];
  let finished = false;
  let errorCode: AnswerView["errorCode"] = null;
  let meta: JuliMetaData | null = null;

  const patchLast = (patch: Partial<AnswerBlockView>) => {
    blocks = [...blocks.slice(0, -1), { ...blocks[blocks.length - 1]!, ...patch }];
  };
  const last = () => blocks[blocks.length - 1]!;

  for (const event of events) {
    switch (event.type) {
      case "status": {
        if (status && status.key !== "thinking" && status.key !== event.data.key) doneSteps = [...doneSteps, status];
        status = event.data;
        break;
      }
      case "restated":
        restated = event.data.text_vi.startsWith(RESTATED_PREFIX) ? event.data.text_vi : `${RESTATED_PREFIX}${event.data.text_vi}`;
        break;
      case "text_delta": {
        const raw = last().rawText + event.data.text;
        patchLast({ rawText: raw, text: stripHeader(stripMarkdown(raw)) });
        break;
      }
      case "text_replace":
        patchLast({ rawText: event.data.text, text: stripHeader(stripMarkdown(event.data.text)) });
        break;
      case "meta":
        if (meta === null) meta = event.data;
        else if (!sameMeta(meta, event.data)) patchLast({ meta: event.data });
        break;
      case "lead":
        patchLast({ lead: event.data.text_vi });
        break;
      case "path":
        patchLast({ path: event.data.steps });
        break;
      case "label":
        patchLast({ label: event.data });
        break;
      case "data_answer":
        patchLast({ dataAnswers: [...last().dataAnswers, normalizeDataAnswer(event.data)] });
        break;
      case "card":
        patchLast({ card: event.data });
        break;
      case "no_card":
        patchLast({ noCard: event.data });
        break;
      case "needs_choice":
        patchLast({ needsChoice: event.data });
        break;
      case "unsupported":
        patchLast({ unsupported: event.data });
        break;
      case "intent_block":
        if (isEmptyBlock(last())) patchLast({ title: event.data.title_vi });
        else blocks = [...blocks, { ...EMPTY_BLOCK, title: event.data.title_vi }];
        break;
      case "more":
        more = event.data.items;
        break;
      case "done":
        finished = true;
        if (status) doneSteps = status.key === "thinking" ? doneSteps : [...doneSteps, status];
        status = null;
        break;
      case "error":
        finished = true;
        errorCode = event.data.code;
        status = null;
        break;
    }
  }

  const freshVi = meta?.fresh_vi ?? blocks.flatMap((b) => b.dataAnswers.map((d) => d.fresh_vi)).at(-1) ?? null;
  if (meta === null) {
    const first = blocks.flatMap((b) => b.dataAnswers)[0];
    if (first) meta = { window_vi: first.window_vi, fresh_vi: first.fresh_vi, ...(first.sale_vi ? { sale_vi: first.sale_vi } : {}) };
  }
  return { restated, status, doneSteps, blocks, more, finished, errorCode, freshVi, meta };
}

function sameMeta(a: JuliMetaData, b: JuliMetaData): boolean {
  return a.window_vi === b.window_vi && a.fresh_vi === b.fresh_vi && a.sale_vi === b.sale_vi;
}

/** #110 rule 1: the answer starts with its answer; a first line restating the question goes. */
export function stripHeader(text: string): string {
  if (!text.startsWith(RESTATED_PREFIX.trim()) && !RESTATED_PREFIX.startsWith(text)) return text;
  const nl = text.indexOf("\n");
  return nl < 0 ? "" : text.slice(nl + 1).replace(/^\n+/, "");
}

/** The answer is plain text: drop markdown emphasis markers the writer sometimes emits ("**x**"). */
export function stripMarkdown(text: string): string {
  return text.replace(/\*\*/g, "").replace(/(^|\s)__(\S)/g, "$1$2").replace(/(\S)__(\s|$)/g, "$1$2");
}

type Loose = Record<string, unknown>;
const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);

/**
 * Coerce a data answer to the UI contract. Answers saved before 22/11 carry the engine's older
 * shapes (`value` as an object, product rows keyed `name` / `gmv_vi`, series keyed `day`); an object
 * rendered as a React child crashed the whole page, and a reopened conversation crashed it again.
 */
export function normalizeDataAnswer(data: JuliDataAnswerData): JuliDataAnswerData {
  const raw = data as unknown as Loose;
  const value = raw.value;
  const valueText =
    typeof value === "string" ? value : value && typeof value === "object" ? str((value as Loose).value_vi) : undefined;
  const rows = Array.isArray(raw.rows)
    ? (raw.rows as Loose[]).map((r) => ({
        ...r,
        label_vi: str(r.label_vi) ?? str(r.name) ?? str(r.item_id) ?? "",
        value_vi: str(r.value_vi) ?? str(r.gmv_vi) ?? "",
        detail_vi: str(r.detail_vi) ?? (str(r.orders_vi) ? `${String(r.orders_vi)} đơn` : undefined),
        missing: typeof r.missing === "boolean" ? r.missing : Boolean(r.note_vi),
        link: r.link ?? (str(r.item_id) ? { kind: "product", item_id: str(r.item_id) } : undefined),
      }))
    : undefined;
  const series = Array.isArray(raw.series)
    ? (raw.series as Loose[]).map((p) => ({ ...p, label_vi: str(p.label_vi) ?? str(p.day) ?? "" }))
    : undefined;
  return {
    ...data,
    ...(value !== undefined ? { value: valueText ?? "" } : {}),
    ...(rows ? { rows } : {}),
    ...(series ? { series } : {}),
  } as JuliDataAnswerData;
}
