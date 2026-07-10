import {
  MOCK_OPERATION_AFFILIATE,
  type AffiliateOperationData,
} from "@/lib/mock-data/operation-affiliate";
import {
  MOCK_OPERATION_SELLER,
  type SellerOperationData,
} from "@/lib/mock-data/operation-seller";
import { isUiOnly } from "@/lib/ui-only";
import type { WorkspaceMode } from "@/lib/workspace-mode";

export type OperationData = SellerOperationData | AffiliateOperationData;

export function getMockOperationData(mode: WorkspaceMode): OperationData {
  return mode === "seller" ? MOCK_OPERATION_SELLER : MOCK_OPERATION_AFFILIATE;
}

function emptySellerOperation(): SellerOperationData {
  return {
    mode: "seller",
    products_summary: {
      total_products: 0,
      active_products: 0,
      gmv_this_month_vnd: 0,
      low_stock_count: 0,
    },
    products: [],
    creators_summary: {
      active_creators: 0,
      gmv_this_month_vnd: 0,
      avg_refund_rate: 0,
    },
    creators: [],
    orders_summary: {
      total_today: 0,
      processing: 0,
      delivered: 0,
      returned: 0,
      returned_delta: 0,
    },
    orders: [],
    returns: [],
  };
}

function emptyAffiliateOperation(): AffiliateOperationData {
  return {
    mode: "affiliate",
    products_summary: {
      active_partnerships: 0,
      commission_this_month_vnd: 0,
      commission_mom_pct: 0,
    },
    products: [],
    orders: [],
    returns: [],
  };
}

export async function getOperationData(mode: WorkspaceMode): Promise<OperationData> {
  if (isUiOnly) {
    return getMockOperationData(mode);
  }

  return mode === "seller" ? emptySellerOperation() : emptyAffiliateOperation();
}
