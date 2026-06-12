"use client";

import { Sparkles } from "lucide-react";
import {
  AFFILIATE_OUT_OF_SCOPE_HEADING,
  AFFILIATE_OUT_OF_SCOPE_MESSAGE,
  AFFILIATE_OUT_OF_SCOPE_TEST_ID,
} from "@/lib/affiliate-out-of-scope";
import { useWorkspaceMode } from "@/lib/mode-context";

export function AffiliateOutOfScope() {
  const { setMode } = useWorkspaceMode();

  return (
    <section
      data-testid={AFFILIATE_OUT_OF_SCOPE_TEST_ID}
      className="card mx-auto max-w-md p-8 text-center"
      aria-labelledby="affiliate-out-of-scope-heading"
    >
      <div
        className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl"
        style={{ background: "var(--muted)" }}
        aria-hidden
      >
        <Sparkles size={28} style={{ color: "var(--primary)" }} />
      </div>
      <p
        className="text-xs font-semibold uppercase tracking-wide"
        style={{ color: "var(--primary)" }}
      >
        Sắp ra mắt
      </p>
      <h2
        id="affiliate-out-of-scope-heading"
        className="mt-2 text-lg font-bold"
        style={{ color: "var(--foreground)" }}
      >
        {AFFILIATE_OUT_OF_SCOPE_HEADING}
      </h2>
      <p className="mt-3 text-sm leading-relaxed" style={{ color: "var(--muted-foreground)" }}>
        {AFFILIATE_OUT_OF_SCOPE_MESSAGE}
      </p>
      <button
        type="button"
        className="btn-primary mt-6 w-full"
        onClick={() => setMode("seller")}
        data-testid="affiliate-switch-to-seller"
      >
        Chuyển sang Người bán
      </button>
      <p className="mt-3 text-xs" style={{ color: "var(--muted-foreground)" }}>
        Hoặc dùng nút chế độ ở góc trên để đổi workspace bất cứ lúc nào.
      </p>
    </section>
  );
}
