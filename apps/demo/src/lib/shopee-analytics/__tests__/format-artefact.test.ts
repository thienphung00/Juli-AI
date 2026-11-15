import { describe, expect, it } from "vitest";
import { DASH, sv, vnd } from "../format";

describe("numerical artefacts print a dash", () => {
  it("never shows a figure beyond any shop amount", () => {
    expect(sv(-2.6778855896141057e21)).toBe(DASH);
    expect(vnd(1e15)).toBe(DASH);
    expect(sv(-43000)).toBe("−43.000đ");
  });
});
