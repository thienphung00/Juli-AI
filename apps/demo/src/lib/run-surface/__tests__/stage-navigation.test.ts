import { describe, expect, it } from "vitest";

import {
  canNavigateToStageIndex,
  clampStageIndex,
  resolveRequestedStageIndex,
  stageIndexOf,
} from "../stage-navigation";

describe("stageIndexOf", () => {
  it("resolves each of the six stage ids to its PUI-DESIGN.md §2 order", () => {
    expect(stageIndexOf("phan-tich")).toBe(0);
    expect(stageIndexOf("thong-tin-san-pham")).toBe(1);
    expect(stageIndexOf("seo")).toBe(2);
    expect(stageIndexOf("de-xuat")).toBe(3);
    expect(stageIndexOf("cap-nhat")).toBe(4);
    expect(stageIndexOf("hoan-tat")).toBe(5);
  });
});

describe("clampStageIndex", () => {
  it("passes through a request inside [0, liveEdgeIndex]", () => {
    expect(clampStageIndex(1, 3)).toBe(1);
  });

  it("clamps a negative request to 0", () => {
    expect(clampStageIndex(-1, 3)).toBe(0);
  });

  it("clamps a request beyond the live edge down to the live edge -- the locked-future rule", () => {
    expect(clampStageIndex(5, 3)).toBe(3);
  });

  it("allows a request exactly at the live edge", () => {
    expect(clampStageIndex(3, 3)).toBe(3);
  });
});

describe("resolveRequestedStageIndex -- the 'unreachable by direct URL' gate", () => {
  it("resolves a null/absent request to the live edge", () => {
    expect(resolveRequestedStageIndex(null, "de-xuat")).toBe(3);
    expect(resolveRequestedStageIndex(undefined, "de-xuat")).toBe(3);
    expect(resolveRequestedStageIndex("", "de-xuat")).toBe(3);
  });

  it("resolves an unknown stage id to the live edge rather than erroring", () => {
    expect(resolveRequestedStageIndex("not-a-real-stage", "de-xuat")).toBe(3);
  });

  it("resolves a request for a stage behind the live edge to that frozen stage", () => {
    expect(resolveRequestedStageIndex("phan-tich", "de-xuat")).toBe(0);
  });

  it("CLAMPS a request for a stage beyond the live edge -- never opens the locked stage", () => {
    // The live edge is "de-xuat" (index 3); a URL asking for "hoan-tat"
    // (index 5, not yet reached) must resolve to the live edge, not 5.
    expect(resolveRequestedStageIndex("hoan-tat", "de-xuat")).toBe(3);
  });

  it("resolves a request for the live edge itself to the live edge", () => {
    expect(resolveRequestedStageIndex("de-xuat", "de-xuat")).toBe(3);
  });
});

describe("canNavigateToStageIndex", () => {
  it("allows every frozen stage and the live edge", () => {
    expect(canNavigateToStageIndex(0, 3)).toBe(true);
    expect(canNavigateToStageIndex(2, 3)).toBe(true);
    expect(canNavigateToStageIndex(3, 3)).toBe(true);
  });

  it("forbids anything beyond the live edge -- the locked stages", () => {
    expect(canNavigateToStageIndex(4, 3)).toBe(false);
    expect(canNavigateToStageIndex(5, 3)).toBe(false);
  });

  it("forbids a negative index", () => {
    expect(canNavigateToStageIndex(-1, 3)).toBe(false);
  });
});
