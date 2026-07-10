import type { ProductDraft } from "../schemas";

const DEMO_SELLER_ID = "seller_demo_new_001";
const DEMO_SHOP_ID = "shop_mai_linh_001";

export const PRODUCT_DRAFTS: ProductDraft[] = [
  {
    draft_id: "c3000001-0001-4000-8000-000000000001",
    seller_id: DEMO_SELLER_ID,
    shop_id: DEMO_SHOP_ID,
    status: "ready_for_export",
    source_type: "manual_form",
    product_info: {
      product_name: "Serum Vitamin C 20ml",
      brand: "Mai Linh Beauty",
      category: "Mỹ phẩm",
      price: 189_000,
      variants: ["20ml"],
      description: "Serum vitamin C giúp làm sáng da và giảm thâm nám.",
    },
    listing_content: {
      title: "Serum Vitamin C 20ml — Làm sáng da, giảm thâm nám",
      description:
        "Serum vitamin C 20% giúp cải thiện độ sáng da, hỗ trợ giảm thâm nám và bảo vệ da khỏi oxy hóa.",
      bullet_points: [
        "Vitamin C 20% giúp làm sáng da",
        "Kết cấu nhẹ, thấm nhanh",
        "Phù hợp mọi loại da",
      ],
      seo_keywords: ["serum vitamin c", "làm sáng da", "mỹ phẩm"],
      hashtags: ["#vitaminc", "#skincare", "#mypham"],
    },
    compliance: {
      status: "approved",
      warnings: [],
      blocking_issues: [],
    },
    readiness: {
      overall_score: 88,
      suggested_improvements: ["Thêm ảnh sản phẩm thực tế trước khi đăng"],
    },
    created_at: "2026-06-01T08:00:00.000Z",
    updated_at: "2026-06-01T08:05:00.000Z",
  },
  {
    draft_id: "c3000002-0002-4000-8000-000000000002",
    seller_id: DEMO_SELLER_ID,
    shop_id: DEMO_SHOP_ID,
    status: "blocked",
    source_type: "opportunity_card",
    product_info: {
      product_name: "Tai nghe Bluetooth TWS",
      brand: null,
      category: "Điện tử",
      price: 0,
      variants: [],
      description: null,
    },
    listing_content: {
      title: "Tai nghe Bluetooth TWS",
      description: "",
      bullet_points: [],
      seo_keywords: [],
      hashtags: [],
    },
    compliance: {
      status: "blocked",
      warnings: ["Thiếu mô tả sản phẩm"],
      blocking_issues: ["Giá bán chưa được nhập"],
    },
    readiness: {
      overall_score: 22,
      suggested_improvements: [
        "Nhập giá bán",
        "Bổ sung mô tả và bullet points",
        "Thêm thương hiệu nếu có",
      ],
    },
    created_at: "2026-06-02T10:00:00.000Z",
    updated_at: "2026-06-02T10:00:00.000Z",
  },
];
