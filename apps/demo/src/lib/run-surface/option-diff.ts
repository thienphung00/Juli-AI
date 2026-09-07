/**
 * The before -> after diff shown on an option card's listing miniature
 * (issue #1317, PUI-DESIGN.md §3: "the before -> after diff rendered on a
 * miniature of the actual listing element -- price on the product card;
 * titles: old struck / new highlighted").
 *
 * PURE, AND NOTHING IS INVENTED. `proposed_change` is a generic
 * `Record<string, unknown>` (ADR-075 decision 2) because it is schema-driven
 * by whichever tool produced the option -- this module reads its shape, it
 * never computes a value the payload did not already carry:
 *
 *  - a field shaped `{ from, to }` (the convention the golden fixture's
 *    price example uses) renders as a struck `from` / highlighted `to`
 *    pair -- both strings copied verbatim from the payload;
 *  - `title` has no `from` on the wire today (the one captured scenario's
 *    `proposed_change` is `{ title: "..." }` with no prior value) -- its
 *    "before" is `productName`, the run's own current bound-product name,
 *    itself a real field the caller already fetched from `GET
 *    /v1/demo/runs` (`WorkflowRunListItem.product_name`), never a client
 *    guess. This is a named, deliberate exception documented here rather
 *    than silently reading a cross-cutting prop: the day the backend adds
 *    `title: { from, to }`, the `{from,to}` branch below takes over and
 *    this fallback stops firing, no caller change required.
 *  - any other field (unknown shape, no `from`, not `title`) renders as
 *    the proposed value alone -- no fabricated "before".
 */

export interface OptionDiffRow {
  readonly field: string;
  /** `undefined` when the payload gives no prior value to compare against
   *  (never fabricated to fill the gap). */
  readonly before?: string;
  readonly after: string;
}

function stringifyValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value === null || value === undefined) return "";
  return JSON.stringify(value);
}

function isFromToShape(value: unknown): value is { from: unknown; to: unknown } {
  return (
    typeof value === "object" &&
    value !== null &&
    "from" in value &&
    "to" in value &&
    !Array.isArray(value)
  );
}

/** `run.option_field.*` -- seller-facing labels for known `proposed_change`
 *  keys, never the raw JSON key (same discipline as `describeToolAction`
 *  in `stage-copy.ts`). An unrecognized field still renders honestly: the
 *  raw key itself, not a fabricated translation. */
const OPTION_FIELD_LABELS: Readonly<Record<string, string>> = Object.freeze({
  price: "Giá",
  title: "Tiêu đề",
});

export function describeOptionField(field: string): string {
  return OPTION_FIELD_LABELS[field] ?? field;
}

export function buildOptionDiffRows(
  proposedChange: Record<string, unknown>,
  productName: string,
): OptionDiffRow[] {
  return Object.entries(proposedChange).map(([field, value]) => {
    if (isFromToShape(value)) {
      return { field, before: stringifyValue(value.from), after: stringifyValue(value.to) };
    }
    if (field === "title") {
      return { field, before: productName, after: stringifyValue(value) };
    }
    return { field, after: stringifyValue(value) };
  });
}
