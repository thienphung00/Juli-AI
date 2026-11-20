import type { JuliDelta, JuliDeltaDir } from "@juli/contracts";

import { dirClass, dirGlyph } from "../../lib/juli/format";

const HAS_MARK = /^[▲▼+−-]/;

/** A change chip: colour plus a glyph or sign, never colour alone. */
export function Delta({ delta, chip = false }: { readonly delta: JuliDelta; readonly chip?: boolean }) {
  const text = HAS_MARK.test(delta.text_vi) || delta.dir === "flat" ? delta.text_vi : `${dirGlyph(delta.dir)} ${delta.text_vi}`;
  return (
    <span className={`juli-delta ${dirClass(delta.dir)}${chip ? " juli-delta--chip" : ""}`} data-dir={delta.dir}>
      {text}
    </span>
  );
}

/** A code-rendered value that carries a direction (ΔGMV, Δ lợi nhuận, margin after). */
export function Directed({ dir, children }: { readonly dir: JuliDeltaDir; readonly children: React.ReactNode }) {
  return (
    <span className={`juli-num ${dirClass(dir)}`} data-dir={dir}>
      {children}
    </span>
  );
}
