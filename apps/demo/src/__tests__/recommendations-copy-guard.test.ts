import { SELLER_COPY_BANNED_PATTERNS } from "@juli/contracts";
import { describe, expect, it } from "vitest";

import { recommendationFixtures } from "../lib/recommendations";

/**
 * P53: the rendered Đề xuất panel (`RecommendationsView` / `RecommendationsPanel`)
 * was removed with the legacy `/decisions/recommendations/*` route. The fixture
 * guard stays because `lib/recommendations.ts` is still read by `demo-state.tsx`.
 */

const BANNED_JARGON = [
  /tool_name/,
  /feature_id/,
  /\bwebhook\b/i,
  /\bendpoint\b/i,
  /\bexecutor\b/i,
  /\bCreate Packages\b/i,
  /\bship\b/i,
  /\bsplit\b/i,
  /\bconfirm\b/i,
  /\bDeactivate\b/i,
  /\bparity\b/i,
  /\bActivity\b/,
  /Get Activity/i,
] as const;

describe("Recommendations — copy guard", () => {
  it("fixture sources do not contain residual system vocabulary", () => {
    for (const fixture of recommendationFixtures) {
      const fieldsToCheck = {
        reasoning: fixture.reasoning,
        risks: fixture.risks,
        knownLimits: fixture.knownLimits,
        sellerReason: fixture.sellerReason,
        evidence: fixture.evidence,
        eligibility: fixture.eligibility,
        subject: fixture.subject,
        previewRows: fixture.previewRows
          .map((row) => `${row.label} ${row.change}`)
          .join(" "),
      };

      for (const [fieldName, fieldValue] of Object.entries(fieldsToCheck)) {
        for (const pattern of BANNED_JARGON) {
          expect(
            fieldValue,
            `${fixture.workflowKey}.${fieldName} contains banned pattern`,
          ).not.toMatch(pattern);
        }
      }
    }
  });
});

describe("Seller copy banned patterns — consistency check", () => {
  it("SELLER_COPY_BANNED_PATTERNS includes false security claim terms", () => {
    // Verify that the canonical banned patterns list includes terms that forbid false security claims
    // This ensures client-side file validation never claims to check for viruses/malware
    const patternStrings = SELLER_COPY_BANNED_PATTERNS.map((p) => p.source);

    expect(patternStrings.join("|")).toMatch(/virus|antivirus|malware/i);
    expect(patternStrings.join("|")).toMatch(/an toàn/i);
  });

  it("SELLER_COPY_BANNED_PATTERNS enforces no internal jargon", () => {
    // Verify the core jargon terms are still banned
    const patternStrings = SELLER_COPY_BANNED_PATTERNS.map((p) => p.source);

    expect(patternStrings.join("|")).toMatch(/tool_name|workflow_key|feature_id/i);
    expect(patternStrings.join("|")).toMatch(/webhook|endpoint/i);
  });
});
