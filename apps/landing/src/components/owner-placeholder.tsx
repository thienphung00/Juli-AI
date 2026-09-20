import type { ReactNode } from "react";

export interface OwnerPlaceholderProps {
  children: ReactNode;
}

/**
 * Marks a legal-page field the owner (not the code) must supply — a retention
 * period, a legal entity name, a jurisdiction, a liability clause. Rendered
 * distinctly (dashed border, muted italic) so it reads as unfinished rather
 * than as a quiet, plausible-sounding invention (issue 1971: "a placeholder
 * the owner must fill is correct; a confident fabrication in a legal
 * document is not").
 */
export function OwnerPlaceholder({ children }: OwnerPlaceholderProps) {
  return (
    <p className="lp-legal__placeholder" data-testid="owner-placeholder">
      [OWNER: {children}]
    </p>
  );
}
