import {
  AFFILIATE_OUT_OF_SCOPE_HEADING,
  AFFILIATE_OUT_OF_SCOPE_MESSAGE,
  AFFILIATE_OUT_OF_SCOPE_TEST_ID,
} from "@/lib/affiliate-out-of-scope";

export function AffiliateOutOfScope() {
  return (
    <section
      data-testid={AFFILIATE_OUT_OF_SCOPE_TEST_ID}
      className="rounded-2xl border p-6 text-center"
      style={{
        background: "var(--card)",
        borderColor: "var(--border)",
      }}
      aria-labelledby="affiliate-out-of-scope-heading"
    >
      <h2
        id="affiliate-out-of-scope-heading"
        className="text-lg font-bold"
        style={{ color: "var(--foreground)" }}
      >
        {AFFILIATE_OUT_OF_SCOPE_HEADING}
      </h2>
      <p className="mt-3 text-sm leading-relaxed" style={{ color: "var(--muted-foreground)" }}>
        {AFFILIATE_OUT_OF_SCOPE_MESSAGE}
      </p>
    </section>
  );
}
