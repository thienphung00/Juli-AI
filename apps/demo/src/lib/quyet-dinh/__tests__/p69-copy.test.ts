import { describe, expect, it } from "vitest";

import { cardView, isSellerSku } from "../card-model";
import { groupDecisions, groupTitle } from "../grouping";
import { shortProductName } from "../product-name";
import type { P10DecisionItem } from "../p10-types";

const LONG = "Nồi lẩu điện mini 1.5L có nắp kính, tay cầm tiện dụng (dùng nấu lẩu, mì, súp)";

describe("shortProductName", () => {
  it("strips parentheticals, cuts on a clause or a word boundary, adds …", () => {
    expect(shortProductName(LONG)).toBe("Nồi lẩu điện mini 1.5L có nắp kính…");
    expect(shortProductName("Áo thun nam cổ tròn cotton thoáng mát co giãn 4 chiều form rộng")).toBe(
      "Áo thun nam cổ tròn cotton thoáng mát co…",
    );
    expect(shortProductName("Bình Nước Thép Không Gỉ Chính Hãng 750ml")).toBe("Bình Nước Thép Không Gỉ Chính Hãng 750ml");
    expect(shortProductName("  Bình   giữ nhiệt (cao cấp) ")).toBe("Bình giữ nhiệt");
    expect(shortProductName(null)).toBe("");
  });
});

describe("group headings", () => {
  it("are short: 'Khuyến mãi · 1 thẻ', 'Sản phẩm · 1 thẻ', 'CTR Thẻ sản phẩm · 2 thẻ'", () => {
    expect(groupTitle(1, "Khuyến mãi", "mọi kênh")).toBe("Khuyến mãi · 1 thẻ");
    expect(groupTitle(1, "Sản phẩm", null)).toBe("Sản phẩm · 1 thẻ");
    expect(groupTitle(2, "CTR", "Thẻ sản phẩm")).toBe("CTR Thẻ sản phẩm · 2 thẻ");
    expect(groupTitle(3, null, null)).toBe("3 đề xuất khác");
  });

  it("names a create card's group from the KPI key, even when the stored label is the old long one", () => {
    const make = (key: string, label: string, stage: string) =>
      ({
        id: key,
        title: key,
        description: "",
        is_executable: true,
        recommendation: {
          diagnosis: {
            stage: { code: stage, label: stage },
            main_kpi: { key, label, value: "+1" },
            lever: { code: "create_product", label: "x" },
          },
        },
      }) as unknown as P10DecisionItem;
    const groups = groupDecisions([
      make("promotion", "Khuyến mãi trên TikTok", "promotion"),
      make("products", "Sản phẩm trên TikTok", "catalog"),
    ]);
    expect(groups.map((group) => group.title)).toEqual(["Khuyến mãi · 1 thẻ", "Sản phẩm · 1 thẻ"]);
  });
});

describe("card view", () => {
  const base = (lever: string, product_title: string, seller_sku: string | null) =>
    ({
      id: "c1",
      title: "x",
      description: "",
      is_executable: true,
      recommendation: {
        diagnosis: { product_title: LONG, tiktok_product_id: "1" },
        card: {
          seller_sku,
          seller_sku_more: 0,
          product_title,
          workflow_label: "Tối ưu",
          updated_at: "2026-10-26T01:00:00Z",
          status: "pending",
          main_kpi: null,
          reason_short: "r",
          reason_full: "",
          tiktok_codes: [],
          lever: { code: lever, label: lever, executor: "juli" },
          change_fields: [],
          before_after: [],
        },
      },
    }) as unknown as P10DecisionItem;

  it("shortens a plain product heading and keeps the full name for hover", () => {
    const view = cardView(base("title", LONG, "SM-012"));
    expect(view.title).toBe("Nồi lẩu điện mini 1.5L có nắp kính…");
    expect(view.fullTitle).toBe(LONG);
    expect(view.sku).toBe("SM-012");
  });

  it("never shows Juli's own JULI-… SKU", () => {
    expect(isSellerSku("JULI-F7B54199")).toBe(false);
    expect(isSellerSku("SM-012")).toBe(true);
    expect(cardView(base("title", LONG, "JULI-F7B54199")).sku).toBeNull();
  });

  it("leaves a backend-built create heading as it is", () => {
    const view = cardView(base("create_product", "Tạo sản phẩm mới từ Bình Nước Thép Không Gỉ Chính Hãng 750ml", null));
    expect(view.title).toBe("Tạo sản phẩm mới từ Bình Nước Thép Không Gỉ Chính Hãng 750ml");
    expect(view.fullTitle).toBe(LONG);
  });
});
