"use client";

import Link from "next/link";

import type { Decision } from "@/lib/decisions";

import { DecisionPreviewCard } from "./DecisionPreviewCard";

export function RecommendedDecisionsPreview({ decisions }: { decisions: Decision[] }) {
  return (
    <section className="space-y-3" data-testid="recommended-decisions-preview">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-bold" style={{ color: "var(--foreground)" }}>
          Quyết định được đề xuất
        </h2>
        <Link
          href="/decisions"
          className="text-sm font-medium underline-offset-2 hover:underline"
          style={{ color: "var(--brand-primary)" }}
          data-testid="decisions-preview-view-all"
        >
          Xem tất cả quyết định
        </Link>
      </div>

      <div className="space-y-3" data-testid="decision-preview-list">
        {decisions.map((decision) => (
          <DecisionPreviewCard key={decision.id} decision={decision} />
        ))}
      </div>
    </section>
  );
}
