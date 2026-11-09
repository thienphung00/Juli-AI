// STUB (W3-J): W3-I owns option-card/. This file exists only so W3-J compiles on its own branch; on merge take W3-I's.
import type { OptionResult } from "../../../lib/shopee-decisions/option-result";

export function OptionCard({ result }: { readonly result: OptionResult }) {
  return <div data-testid="option-card">{result.label}</div>;
}

export function CompareTable({ results }: { readonly results: readonly OptionResult[] }) {
  return <div data-testid="compare-table">{results.map((r) => r.label).join(" | ")}</div>;
}
