/**
 * Folds one answer's event stream into the view the answer renders. Pure: the same events give
 * the same view, so a replayed prefix after a reconnect, a saved answer and a live one all agree.
 */
import type {
  JuliAgentEvent,
  JuliCardData,
  JuliDataAnswerData,
  JuliLabelData,
  JuliNeedsChoiceData,
  JuliNoCardData,
  JuliPathStep,
  JuliUnsupportedData,
  JuliEventMap,
} from "@juli/contracts";

export interface AnswerBlockView {
  readonly title: string | null;
  readonly text: string;
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
}

export const RESTATED_PREFIX = "Đang tìm hiểu: ";

const EMPTY_BLOCK: AnswerBlockView = {
  title: null,
  text: "",
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
    b.text === "" &&
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
      case "text_delta":
        patchLast({ text: last().text + event.data.text });
        break;
      case "text_replace":
        patchLast({ text: event.data.text });
        break;
      case "path":
        patchLast({ path: event.data.steps });
        break;
      case "label":
        patchLast({ label: event.data });
        break;
      case "data_answer":
        patchLast({ dataAnswers: [...last().dataAnswers, event.data] });
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

  const freshVi = blocks.flatMap((b) => b.dataAnswers.map((d) => d.fresh_vi)).at(-1) ?? null;
  return { restated, status, doneSteps, blocks, more, finished, errorCode, freshVi };
}
