import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * D61: public content does not expose Juli's algorithms or models. This test
 * scans the source of every rendered text surface (pages, shared components,
 * route meta / JSON-LD / llms.txt in `lib/seo`, blog bodies, post meta and FAQs,
 * figure alts and captions) for the leak forms the 2026-10-18 audit found, so
 * they cannot come back. `/terms` and `/privacy` own their legal disclosures
 * (D46.4, D61) and are not scanned.
 *
 * Kept on purpose (no pattern catches them): TikTok's public metric
 * definitions and the identity GMV = Lượt hiển thị × CTR × CTOR × AOV; the
 * workflow (day 7 check, day 14 verdict, undo); the 14-day baseline; data and
 * security commitments; naming the AI provider on `/ket-noi`; result labels.
 *
 * Text is matched after collapsing whitespace, so a phrase wrapped across JSX
 * lines still matches. Patterns marked `hypotheticalOk` are skipped when the
 * 200 characters before the match contain "Ví dụ giả định": a labelled
 * do-it-yourself example may use round numbers (D61: reach posts keep DIY
 * advice), but a bare number stated as a rule may not.
 */

interface LeakPattern {
  pattern: RegExp;
  reason: string;
  hypotheticalOk?: boolean;
}

const LEAK_PATTERNS: readonly LeakPattern[] = [
  // Expected / recoverable GMV formulas. The TikTok identity has no "mục tiêu −
  // hiện tại" term, and its derivation "× (Lượt nhấp ÷ Lượt hiển thị)" has no
  // metric right after "× (", so neither matches. The equation form needs
  // " = " with spaces, so a JSX attribute (`GMV dự kiến" caption=`) does not.
  { pattern: /CTO?R mục tiêu\s*[−-]\s*CTO?R hiện tại/u, reason: "recoverable-GMV formula (target − current)" },
  { pattern: /×\s*\(\s*(CTO?R|AOV)/u, reason: "recoverable-GMV formula (× (…) form)" },
  { pattern: /GMV (có thể lấy lại|dự kiến)[^.="\n]{0,40}\s=\s/u, reason: "recoverable / expected GMV written as an equation" },
  { pattern: /nhân chênh lệch (CTR|CTOR)/u, reason: "recoverable-GMV formula spelled out in an alt" },
  // Learning, calibration, demotion and decay.
  { pattern: /hệ số hiệu chỉnh/u, reason: "calibration coefficient" },
  { pattern: /hệ số học/u, reason: "learning coefficient" },
  { pattern: /hệ số so sánh GMV/u, reason: "calibration coefficient (actual vs expected GMV)" },
  { pattern: /nhạt dần/u, reason: "decay of learned priority" },
  { pattern: /ưu tiên thấp hơn/u, reason: "priority demotion from seller reasons or outcomes" },
  { pattern: /cập nhật mức kỳ vọng|mức kỳ vọng[^.]{0,40}thận trọng/u, reason: "per-lever expectation update" },
  { pattern: /[Tt]hứ tự (các )?đề xuất (đã điều chỉnh|sau|tiếp theo)/u, reason: "outcomes feed back into ranking" },
  // Rules-vs-model architecture and model names.
  { pattern: /Quy tắc chọn, AI chỉ viết/u, reason: "rules-vs-AI architecture heading" },
  // "AI chỉ viết lại được từ thông tin bạn cung cấp" is generic advice about any
  // AI writing tool, not Juli's architecture.
  { pattern: /AI chỉ (được )?(gọi|viết)(?! lại được)/u, reason: "when the model is called" },
  { pattern: /ước tính theo quy tắc/u, reason: "rules-vs-model architecture" },
  { pattern: /\bGPT/u, reason: "model name" },
  { pattern: /fine-?tun/iu, reason: "model training method" },
  // Card caps, slots, validity and cooldown windows.
  { pattern: /3\/1\/1/u, reason: "daily card slots" },
  { pattern: /(?<![\d.,])5 thẻ mới/u, reason: "daily card cap" },
  { pattern: /[Tt]ối đa 5 (thẻ|đề xuất)/u, reason: "daily card cap" },
  { pattern: /(?<![\d.,])25 thẻ/u, reason: "weekly card cap" },
  { pattern: /(?<![\d.,])30 thẻ/u, reason: "open-card cap" },
  { pattern: /1 đến 3 (“|")?(đề xuất|thẻ) nhanh/u, reason: "onboarding quick-card count" },
  { pattern: /hiệu lực 7 ngày|ở lại ít nhất 3 ngày/u, reason: "card validity / stay window" },
  { pattern: /quay lại (sau )?(ít nhất )?7 ngày|(từ chối|hoàn tác)[^.]{0,30}trong 7 ngày/u, reason: "cooldown window" },
  { pattern: /(ô|thẻ)[^.]{0,40}(được lấp đầy|được lấp vào)/u, reason: "daily slot filling" },
  // Verdict multiples, statistical tests and data floors.
  { pattern: /≥ ?2 ?×/u, reason: "verdict multiple" },
  { pattern: /1–2 ?×/u, reason: "verdict multiple" },
  { pattern: /(một|1) đến (hai|2) lần (mức )?dao động/u, reason: "verdict multiple", hypotheticalOk: true },
  { pattern: /(hai|2) lần mức dao động/u, reason: "verdict multiple", hypotheticalOk: true },
  { pattern: /dải dao động/u, reason: "internal band wording for the verdict" },
  { pattern: /khoảng tin cậy[^.]{0,40}không chứa 0/u, reason: "statistical test used for verdicts and pooling" },
  { pattern: /(?<![\d.,])50 lượt hiển thị mỗi ngày/u, reason: "CTR data floor", hypotheticalOk: true },
  { pattern: /(?<![\d.,])20 lượt nhấp mỗi ngày/u, reason: "CTOR data floor", hypotheticalOk: true },
  // "từ 30 đơn hủy do lỗi người bán" is TikTok's own penalty rule.
  { pattern: /(?<![\d.,])30 đơn(?! (hủy|huỷ))/u, reason: "order data floor", hypotheticalOk: true },
  { pattern: /(?<![\d.,])30 lượt nhấp/u, reason: "click data floor", hypotheticalOk: true },
  { pattern: /14, 30 rồi 60 ngày/u, reason: "adaptive diagnosis window" },
  { pattern: /ngẫu nhiên[^.]{0,30}một phần ba/u, reason: "delayed-control holdback share" },
  // Comparison groups, peer medians and simulation.
  // "mức ở giữa (trung vị) là 14,0%" describes TikTok's fee table, not a peer
  // reference Juli compares products with.
  { pattern: /trung vị(?!\) là)/u, reason: "peer-median reference" },
  { pattern: /nhóm đối chứng|đối chứng chậm/u, reason: "control-group method (D34 not shipped)" },
  {
    pattern: /(ngày 7|ngày 14)[^.]{0,40}so với (nhóm |các )?sản phẩm không (thay )?đổi/u,
    reason: "comparison-group method attributed to the measurement",
  },
  { pattern: /nhóm sản phẩm không (thay )?đổi/u, reason: "comparison-group method" },
  { pattern: /Juli[^.]{0,60}mô phỏng|mô phỏng[^.]{0,60}Juli/u, reason: "simulation described as Juli's method" },
];

/**
 * Blog files that still hit a pattern while P52-B (guides) and P52-C (reach,
 * pillar and tools posts) clean the blog in parallel. Paths are relative to
 * `src`. Each entry must still hit (the stale check below fails otherwise):
 * remove a file from this list in the commit that cleans it. Target: empty.
 */
const LEAK_PENDING_FILES: readonly string[] = [
];

const SRC_ROOT = join(__dirname, "..");
const SCANNED_EXTENSIONS = [".tsx", ".ts", ".md", ".mdx", ".json", ".txt"];
const SCANNED_ROOTS = ["app", "components", join("lib", "seo"), join("content", "blog")];
const SKIPPED = new Set([
  join(SRC_ROOT, "app", "terms"),
  join(SRC_ROOT, "app", "privacy"),
]);

function collectFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) {
      return entry === "__tests__" || SKIPPED.has(path) ? [] : collectFiles(path);
    }
    if (/\.test\.[jt]sx?$/.test(entry) || entry === "README.md" || entry === "MODULE.md") return [];
    return SCANNED_EXTENSIONS.some((extension) => path.endsWith(extension)) ? [path] : [];
  });
}

function toKey(path: string): string {
  return relative(SRC_ROOT, path).split(sep).join("/");
}

function findLeaks(text: string): string[] {
  const flat = text.normalize("NFC").replace(/\s+/gu, " ");
  const hits: string[] = [];
  for (const { pattern, reason, hypotheticalOk } of LEAK_PATTERNS) {
    const global = new RegExp(pattern.source, pattern.flags.includes("g") ? pattern.flags : `${pattern.flags}g`);
    for (const match of flat.matchAll(global)) {
      const start = match.index ?? 0;
      if (hypotheticalOk && /ví dụ giả định/iu.test(flat.slice(Math.max(0, start - 200), start))) continue;
      hits.push(`${reason}: “${flat.slice(Math.max(0, start - 30), start + match[0].length + 30)}”`);
    }
  }
  return hits;
}

const FILES = SCANNED_ROOTS.flatMap((root) => collectFiles(join(SRC_ROOT, root)));
const LEAKS = new Map(FILES.map((file) => [toKey(file), findLeaks(readFileSync(file, "utf8"))]));

describe("no algorithm or model leak in public content (D61)", () => {
  it("scans pages, components, SEO and every blog body, posts.ts and figures.ts", () => {
    const keys = [...LEAKS.keys()];
    for (const required of [
      "app/san-pham/de-xuat-va-thuc-thi/page.tsx",
      "app/san-pham/do-luong-gmv/page.tsx",
      "app/cong-cu/tinh-gmv/page.tsx",
      "components/ui/blocks.tsx",
      "lib/seo/llms.ts",
      "content/blog/posts.ts",
      "content/blog/figures.ts",
    ]) {
      expect(keys, required).toContain(required);
    }
    expect(keys.filter((key) => key.startsWith("content/blog/bodies/")).length).toBeGreaterThan(20);
    expect(keys.some((key) => key.startsWith("app/terms") || key.startsWith("app/privacy"))).toBe(false);
  });

  it("product pages, home, components, calculator and SEO have no leak", () => {
    const offenders = [...LEAKS]
      .filter(([key, hits]) => !key.startsWith("content/blog/") && hits.length > 0)
      .map(([key, hits]) => `${key}\n  ${hits.join("\n  ")}`);
    expect(offenders, offenders.join("\n")).toHaveLength(0);
  });

  it("blog content has no leak outside LEAK_PENDING_FILES", () => {
    const pending = new Set(LEAK_PENDING_FILES);
    const offenders = [...LEAKS]
      .filter(([key, hits]) => key.startsWith("content/blog/") && !pending.has(key) && hits.length > 0)
      .map(([key, hits]) => `${key}\n  ${hits.join("\n  ")}`);
    expect(offenders, offenders.join("\n")).toHaveLength(0);
  });

  it("LEAK_PENDING_FILES lists only blog files that still leak (remove an entry once clean)", () => {
    for (const key of LEAK_PENDING_FILES) {
      expect(key.startsWith("content/blog/"), key).toBe(true);
      expect(existsSync(join(SRC_ROOT, key)), key).toBe(true);
      expect(LEAKS.get(key)?.length ?? 0, `${key} is clean: remove it from LEAK_PENDING_FILES`).toBeGreaterThan(0);
    }
  });

  it.each([
    ["TikTok GMV identity", "GMV = Lượt hiển thị × CTR × CTOR × AOV"],
    ["TikTok CTR definition", "CTR = Lượt nhấp ÷ Lượt hiển thị"],
    ["labelled hypothetical floor", "Ví dụ giả định: chỉ đọc CTOR khi có từ 30 lượt nhấp trở lên."],
    ["workflow and baseline", "So với mốc 14 ngày trước khi áp dụng, kiểm tra ngày 7, chốt ngày 14."],
    ["AI provider disclosure", "Dữ liệu gửi đến OpenAI để soạn nội dung không được dùng để huấn luyện mô hình."],
    ["TikTok CTR derivation", "Lượt hiển thị × CTR = Lượt hiển thị × (Lượt nhấp ÷ Lượt hiển thị) = Lượt nhấp"],
    ["TikTok penalty rule", "từ 10% kèm từ 30 đơn hủy do lỗi người bán bị trừ 1 điểm"],
    ["TikTok fee statistic", "từ 1,5% đến 16,0%, mức ở giữa (trung vị) là 14,0%"],
    ["generic AI-tool advice", "AI chỉ viết lại được từ thông tin bạn cung cấp."],
    ["JSX attributes after a label", 'alt="… và GMV dự kiến" caption="Một thẻ đề xuất"'],
  ])("does not flag legitimate copy: %s", (_name, text) => {
    expect(findLeaks(text)).toEqual([]);
  });

  it.each([
    ["formula", "Lượt nhấp × (CTOR mục tiêu − CTOR hiện tại) × AOV"],
    ["cap", "Tối đa 5 thẻ mới mỗi ngày"],
    ["unlabelled floor", "khoảng 30 lượt nhấp hoặc 30 đơn"],
    ["decay", "ưu tiên thấp hơn, nhạt dần trong 60 ngày"],
    ["architecture", "Mô hình AI chỉ được gọi sau khi bạn duyệt"],
  ])("flags a known leak: %s", (_name, text) => {
    expect(findLeaks(text).length).toBeGreaterThan(0);
  });
});
