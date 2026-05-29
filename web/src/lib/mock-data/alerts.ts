import type { HomeAlertCard } from "@/lib/mock-data/home";
import type { WorkspaceMode } from "@/lib/workspace-mode";

/** Aligns with `prod-laneige-berry-3` in operation-seller mock inventory. */
export const SELLER_LOW_STOCK_LANEIGE = {
  product_id: "prod-laneige-berry-3",
  product_name: "Son dưỡng môi Laneige #3 Berry",
  stock_units: 12,
  velocity_units_per_day: 4.2,
  days_until_stockout: 3,
  risk_level: "critical" as const,
};

export type WorkspaceAlertType =
  | "inventory_risk"
  | "livestream"
  | "commission_opportunity"
  | "return_impact";

export type WorkspaceAlertSeverity = "high" | "medium" | "low" | "info";

export interface WorkspaceAlert {
  id: string;
  type: WorkspaceAlertType;
  severity: WorkspaceAlertSeverity;
  mode: WorkspaceMode;
  title: string;
  message: string;
  product_id?: string;
  product_name?: string;
  stock_units?: number;
  days_until_stockout?: number;
  velocity_units_per_day?: number;
  risk_level?: "critical" | "warning" | "safe";
  action_label?: string;
  action_href?: string;
}

export function formatInventoryRiskMessage(product: {
  product_name: string;
  stock_units: number;
  days_until_stockout: number;
}): string {
  const days = Math.max(1, Math.round(product.days_until_stockout));
  return `${product.product_name} còn ${product.stock_units} đơn vị. Dự kiến hết hàng sau ${days} ngày.`;
}

function sellerInventoryAlert(): WorkspaceAlert {
  const inventory = SELLER_LOW_STOCK_LANEIGE;
  return {
    id: "alert-seller-inventory-laneige",
    type: "inventory_risk",
    severity: "high",
    mode: "seller",
    title: "Tồn kho sắp hết",
    message: formatInventoryRiskMessage(inventory),
    product_id: inventory.product_id,
    product_name: inventory.product_name,
    stock_units: inventory.stock_units,
    days_until_stockout: inventory.days_until_stockout,
    velocity_units_per_day: inventory.velocity_units_per_day,
    risk_level: inventory.risk_level,
    action_label: "Xem",
    action_href: "/operation?tab=products",
  };
}

const MOCK_ALERTS_SELLER: WorkspaceAlert[] = [
  sellerInventoryAlert(),
  {
    id: "alert-seller-livestream-2841",
    type: "livestream",
    severity: "info",
    mode: "seller",
    title: "Livestream đang diễn ra",
    message:
      "Phiên live #2841 đạt 1.2K người xem — GMV tăng 18% so với trung bình.",
    action_label: "Xem live",
    action_href: "/livestreams",
  },
];

const MOCK_ALERTS_AFFILIATE: WorkspaceAlert[] = [
  {
    id: "alert-affiliate-commission-romand",
    type: "commission_opportunity",
    severity: "high",
    mode: "affiliate",
    title: "Cơ hội hoa hồng",
    message:
      "Son Romand Juicy #Cherry đang viral — hoa hồng 12%, chuyển đổi 9.1% trong 7 ngày qua.",
    product_id: "prod-romand-cherry",
    product_name: "Son Romand Juicy Lasting Tint #Cherry",
    action_label: "Đăng ký",
    action_href: "/trends?tab=product&q=romand+berry",
  },
  {
    id: "alert-affiliate-return-laneige",
    type: "return_impact",
    severity: "medium",
    mode: "affiliate",
    title: "Hoàn trả ảnh hưởng hoa hồng",
    message:
      "Đơn Son Laneige #3 Berry hoàn trả — tác động hoa hồng −₫37.000 (ước tính).",
    product_id: "prod-laneige-berry",
    product_name: "Son Laneige #3 Berry",
    action_label: "Xem đơn",
    action_href: "/operation?tab=returns",
  },
  {
    id: "alert-affiliate-livestream-reminder",
    type: "livestream",
    severity: "info",
    mode: "affiliate",
    title: "Livestream sắp bắt đầu",
    message: "Phiên live skincare tối nay 20:00 — gợi ý 3 sản phẩm audience fit cao.",
    action_label: "Chuẩn bị",
    action_href: "/livestreams",
  },
];

export function getMockWorkspaceAlerts(mode: WorkspaceMode): WorkspaceAlert[] {
  return mode === "seller" ? [...MOCK_ALERTS_SELLER] : [...MOCK_ALERTS_AFFILIATE];
}

export function toHomeAlertCard(alert: WorkspaceAlert): HomeAlertCard {
  return {
    id: alert.id,
    type: alert.type,
    severity: alert.severity,
    title: alert.title,
    body: alert.message,
    action_label: alert.action_label,
    action_href: alert.action_href,
  };
}

export function toHomeAlertCards(alerts: WorkspaceAlert[]): HomeAlertCard[] {
  return alerts.map(toHomeAlertCard);
}
