import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fakeBuilder } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import { fakeReco } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { BuilderP98Api } from "../../../lib/shopee-decisions/builder-p98-api";
import { kolCandidatesOf, kolKind } from "../../../lib/shopee-decisions/kol-candidates";
import type { KolApi, KolReport } from "../../../lib/shopee-kol/types";
import { DecisionsView } from "../decisions-view";
import { params, renderReco } from "./harness";

const p98 = { combo: vi.fn(), kol: vi.fn(), ads: vi.fn() } as unknown as BuilderP98Api;

describe("P98 W4-C · builders are reachable from Quyết định", () => {
  it("shows the three builder tabs with the P98 client", async () => {
    const builder = fakeBuilder();
    renderReco(<DecisionsView params={params("tu-tao=1")} />, fakeReco(), { builder, p98 });
    await waitFor(() => expect(screen.getByTestId("p98-modes")).toBeInTheDocument());
    for (const k of ["combo", "kol", "ads"]) expect(screen.getByTestId(`p98-mode-${k}`)).toBeInTheDocument();
  });

  it("shows no extra tabs without the client", async () => {
    const builder = fakeBuilder();
    renderReco(<DecisionsView params={params("tu-tao=1")} />, fakeReco(), { builder });
    await waitFor(() => expect(screen.queryByText("Đang tải sản phẩm…")).toBeNull());
    expect(screen.queryByTestId("p98-modes")).toBeNull();
  });

  it("passes the shop's KOL rows to the KOL builder", async () => {
    const builder = fakeBuilder();
    const kols = vi.fn().mockResolvedValue([{ kol_key: "k1", handle: "@mai", kind: "kol" }, { kol_key: "c1", handle: "shopbackvn_", kind: "cashback" }]);
    renderReco(<DecisionsView params={params("tu-tao=1")} />, fakeReco(), { builder, p98, kols });
    await waitFor(() => expect(kols).toHaveBeenCalled());
    (await screen.findByTestId("p98-mode-kol")).click();
    expect(await screen.findByText(/@mai/)).toBeInTheDocument();
  });

  it("maps the KOL report to candidates, cashback and coupon sites marked", async () => {
    const report = { filters: { kols: [{ kol_key: "a", handle: "@mai" }, { kol_key: "b", handle: "accesstradevn" }, { kol_key: "c", handle: "magiamgia_vn" }] } } as unknown as KolReport;
    const api = { report: vi.fn().mockResolvedValue(report) } as unknown as KolApi;
    expect(await kolCandidatesOf(api)()).toEqual([
      { kol_key: "a", handle: "@mai", kind: "kol" },
      { kol_key: "b", handle: "accesstradevn", kind: "cashback" },
      { kol_key: "c", handle: "magiamgia_vn", kind: "coupon" },
    ]);
    expect(kolKind(null)).toBe("kol");
  });
});
