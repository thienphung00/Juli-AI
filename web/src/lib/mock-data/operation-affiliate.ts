export interface AffiliateProductSummary {
  active_partnerships: number;
  commission_this_month_vnd: number;
  commission_mom_pct: number;
}

export interface AffiliateProduct {
  id: string;
  name: string;
  orders_this_month: number;
  commission_vnd: number;
  commission_pct: number;
  conversion_rate: number;
}

export interface AffiliateOrder {
  id: string;
  product_name: string;
  quantity: number;
  total_vnd: number;
  status: "shipping" | "delivered" | "returned" | "processing";
  created_at: string;
}

export interface AffiliateReturn {
  id: string;
  product_name: string;
  status: "pending_review" | "approved" | "rejected";
  commission_impact_vnd: number;
  created_at: string;
}

export interface AffiliateOperationData {
  mode: "affiliate";
  products_summary: AffiliateProductSummary;
  products: AffiliateProduct[];
  orders: AffiliateOrder[];
  returns: AffiliateReturn[];
}

export const MOCK_OPERATION_AFFILIATE: AffiliateOperationData = {
  mode: "affiliate",
  products_summary: {
    active_partnerships: 8,
    commission_this_month_vnd: 38_400_000,
    commission_mom_pct: 22,
  },
  products: [
    {
      id: "prod-laneige-berry",
      name: "Son Laneige #3 Berry",
      orders_this_month: 142,
      commission_vnd: 14_200_000,
      commission_pct: 10,
      conversion_rate: 0.083,
    },
    {
      id: "prod-anessa-spf50",
      name: "Kem chống nắng Anessa SPF50",
      orders_this_month: 89,
      commission_vnd: 9_800_000,
      commission_pct: 8,
      conversion_rate: 0.074,
    },
    {
      id: "prod-bioderma-micellar",
      name: "Nước tẩy trang Bioderma H2O",
      orders_this_month: 71,
      commission_vnd: 6_200_000,
      commission_pct: 10,
      conversion_rate: 0.069,
    },
  ],
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
  ],
  returns: [
    {
      id: "HR-001",
      product_name: "Nước tẩy trang Bioderma",
      status: "pending_review",
      commission_impact_vnd: -18_500,
      created_at: "2026-05-27T10:10:00+07:00",
    },
  ],
};
