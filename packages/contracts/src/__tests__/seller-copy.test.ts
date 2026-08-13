import { describe, expect, it } from "vitest";

import { SELLER_COPY_BANNED_PATTERNS } from "../seller-copy";
// Import (not re-derive from seller-copy.ts) the shared JSON source directly so
// this test cross-checks the guard's built RegExp objects against the source of
// truth, rather than against its own construction of it.
import sharedSource from "../../seller-copy-banned-patterns.json";

describe("SELLER_COPY_BANNED_PATTERNS", () => {
  it("builds every RegExp from the shared JSON source, in order", () => {
    expect(SELLER_COPY_BANNED_PATTERNS).toHaveLength(
      sharedSource.patterns.length,
    );
    sharedSource.patterns.forEach((entry, index) => {
      const pattern = SELLER_COPY_BANNED_PATTERNS[index];
      expect(pattern).toBeInstanceOf(RegExp);
      expect(pattern.source).toBe(entry.source);
      expect(pattern.flags).toBe(entry.flags);
    });
  });

  it("has no duplicate pattern ids in the shared source", () => {
    const ids = sharedSource.patterns.map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  // Characterization tests: these strings matched/did-not-match under the
  // original hand-written `seller-copy.ts` array before #990 extracted it to
  // JSON. Behavior must be byte-for-byte identical after the rewire.
  const shouldMatch: Array<[label: string, text: string]> = [
    ["tool_name", "internal tool_name leaked"],
    ["workflow_key case-insensitive", "WORKFLOW_KEY should not leak"],
    ["webhook word boundary", "configure the webhook now"],
    ["FBS exact case", "moved to FBS warehouse"],
    ["FBT exact case", "shipped via FBT"],
    ["Vietnamese Độ tin cậy", "Độ tin cậy: cao"],
    ["Vietnamese Công cụ", "Công cụ: Tối ưu sản phẩm"],
    ["Vietnamese Khả năng", "Khả năng: 90%"],
    ["Get Product case-insensitive", "call get product api"],
    ["Unresolved/Unfilled escaped slash", "status is Unresolved/Unfilled"],
    ["listing. internal path", "listing.update failed"],
    ["executor word boundary", "the executor ran"],
    ["ship word boundary", "please ship this order"],
    ["confirm word boundary", "confirm the action"],
    ["virus false-safety claim", "no virus detected"],
    ["antivirus false-safety claim", "antivirus scan complete"],
    ["Vietnamese an toàn word boundary", "tệp này an toàn"],
    ["Vietnamese kiểm tra an toàn", "đã kiểm tra an toàn"],
    ["Vietnamese tệp an toàn", "tệp an toàn để tải lên"],
  ];

  it.each(shouldMatch)("flags banned text: %s", (_label, text) => {
    expect(SELLER_COPY_BANNED_PATTERNS.some((pattern) => pattern.test(text))).toBe(
      true,
    );
  });

  const shouldNotMatch: Array<[label: string, text: string]> = [
    [
      "FBS is case-sensitive (no flag) — lowercase must not match",
      "moved to fbs warehouse",
    ],
    [
      "FBT is case-sensitive (no flag) — lowercase must not match",
      "shipped via fbt",
    ],
    ["clean seller-facing copy", "Sản phẩm của bạn đã được cập nhật thành công."],
    [
      "word-boundary guard: shipment does not match \\bship\\b",
      "your shipment is on the way",
    ],
  ];

  it.each(shouldNotMatch)("does not flag clean text: %s", (_label, text) => {
    expect(SELLER_COPY_BANNED_PATTERNS.some((pattern) => pattern.test(text))).toBe(
      false,
    );
  });
});
