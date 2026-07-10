export interface SellerProductSummary {
  total_products: number;
  active_products: number;
  gmv_this_month_vnd: number;
  low_stock_count: number;
}

export interface SellerProduct {
  id: string;
  name: string;
  gmv_this_month_vnd: number;
  roi_pct: number;
  profit_per_order_vnd: number;
  stock_units: number;
  velocity_units_per_day: number;
  days_until_stockout: number;
  risk_level: "critical" | "safe" | "warning";
}

export interface SellerCreatorsSummary {
  active_creators: number;
  gmv_this_month_vnd: number;
  avg_refund_rate: number;
}

export interface SellerCreator {
  id: string;
  handle: string;
  status: "active" | "pending_approval" | "inactive";
  commission_pct: number;
  gmv_this_month_vnd: number;
  conversion_rate: number | null;
  refund_rate: number | null;
  fit_score: number;
}

export interface SellerOrdersSummary {
  total_today: number;
  processing: number;
  delivered: number;
  returned: number;
  returned_delta: number;
}

export interface SellerOrder {
  id: string;
  product_name: string;
  quantity: number;
  total_vnd: number;
  status: "shipping" | "delivered" | "returned" | "processing";
  created_at: string;
}

export interface SellerReturn {
  id: string;
  order_id: string;
  product_name: string;
  creator_handle: string;
  reason: string;
  gmv_impact_vnd: number;
  status: "pending_review" | "approved" | "rejected";
  created_at: string;
}

export interface SellerOperationData {
  mode: "seller";
  products_summary: SellerProductSummary;
  products: SellerProduct[];
  creators_summary: SellerCreatorsSummary;
  creators: SellerCreator[];
  orders_summary: SellerOrdersSummary;
  orders: SellerOrder[];
  returns: SellerReturn[];
}

export const MOCK_OPERATION_SELLER: SellerOperationData = {
  mode: "seller",
  products_summary: {
    total_products: 18,
    active_products: 14,
    gmv_this_month_vnd: 284_000_000,
    low_stock_count: 2,
  },
  products: [
    {
      id: "prod-laneige-berry-3",
      name: "Son Laneige #3 Berry",
      gmv_this_month_vnd: 84_000_000,
      roi_pct: 340,
      profit_per_order_vnd: 42_000,
      stock_units: 12,
      velocity_units_per_day: 4.2,
      days_until_stockout: 2.9,
      risk_level: "critical",
    },
    {
      id: "prod-anessa-spf50",
      name: "Kem chống nắng Anessa SPF50",
      gmv_this_month_vnd: 62_000_000,
      roi_pct: 280,
      profit_per_order_vnd: 78_000,
      stock_units: 84,
      velocity_units_per_day: 3.1,
      days_until_stockout: 27.1,
      risk_level: "safe",
    },
    {
      id: "prod-bioderma-micellar",
      name: "Nước tẩy trang Bioderma H2O",
      gmv_this_month_vnd: 41_000_000,
      roi_pct: 195,
      profit_per_order_vnd: 38_000,
      stock_units: 53,
      velocity_units_per_day: 2.4,
      days_until_stockout: 22.1,
      risk_level: "safe",
    },
  ],
  creators_summary: {
    active_creators: 6,
    gmv_this_month_vnd: 198_000_000,
    avg_refund_rate: 0.014,
  },
  creators: [
    {
      id: "creator-linh-nhi",
      handle: "@linh.nhi.beauty",
      status: "active",
      commission_pct: 10,
      gmv_this_month_vnd: 84_000_000,
      conversion_rate: 0.083,
      refund_rate: 0.009,
      fit_score: 0.91,
    },
    {
      id: "creator-beauty-hanoi",
      handle: "@beauty.hanoi",
      status: "active",
      commission_pct: 8,
      gmv_this_month_vnd: 31_000_000,
      conversion_rate: 0.068,
      refund_rate: 0.021,
      fit_score: 0.74,
    },
    {
      id: "creator-glow-skincare",
      handle: "@glow.skincare.vn",
      status: "pending_approval",
      commission_pct: 9,
      gmv_this_month_vnd: 0,
      conversion_rate: null,
      refund_rate: null,
      fit_score: 0.86,
    },
  ],
  orders_summary: {
    total_today: 312,
    processing: 48,
    delivered: 251,
    returned: 13,
    returned_delta: 3,
  },
  orders: [
    {
      id: "DH-20260527-8821",
      product_name: "Son Laneige Berry",
      quantity: 2,
      total_vnd: 370_000,
      status: "shipping",
      created_at: "2026-05-27T14:32:00+07:00",
    },
    {
      id: "DH-20260527-8820",
      product_name: "Kem chống nắng Anessa SPF50",
      quantity: 1,
      total_vnd: 420_000,
      status: "delivered",
      created_at: "2026-05-27T11:15:00+07:00",
    },
    {
      id: "DH-20260527-8819",
      product_name: "Nước tẩy trang Bioderma",
      quantity: 1,
      total_vnd: 295_000,
      status: "returned",
      created_at: "2026-05-27T09:44:00+07:00",
    },
  ],
  returns: [
    {
      id: "HR-001",
      order_id: "DH-20260527-8819",
      product_name: "Nước tẩy trang Bioderma",
      creator_handle: "@beauty.hanoi",
      reason: "Màu khác ảnh",
      gmv_impact_vnd: -295_000,
      status: "pending_review",
      created_at: "2026-05-27T10:10:00+07:00",
    },
  ],
};
