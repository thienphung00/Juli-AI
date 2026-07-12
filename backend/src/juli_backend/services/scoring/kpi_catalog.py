"""KPI → execution_layer workflow mapping from visual_layer.md + ml_layer.md."""

from __future__ import annotations

from juli_backend.services.aggregates.types import ShopProfile
from juli_backend.services.scoring.types import ExecutionWorkflowKey, KpiId, VisualLayerDomain

KPI_DOMAIN: dict[KpiId, VisualLayerDomain] = {
    "sps": VisualLayerDomain.SHOP_STATUS,
    "ahr": VisualLayerDomain.SHOP_STATUS,
    "violation_points": VisualLayerDomain.SHOP_STATUS,
    "net_revenue": VisualLayerDomain.REVENUE,
    "aov": VisualLayerDomain.REVENUE,
    "revenue_by_sku": VisualLayerDomain.REVENUE,
    "conversion_rate_by_category": VisualLayerDomain.REVENUE,
    "repeat_purchase_rate": VisualLayerDomain.REVENUE,
    "roas": VisualLayerDomain.ADS,
    "cac": VisualLayerDomain.ADS,
    "ctr": VisualLayerDomain.ADS,
    "inventory_turnover": VisualLayerDomain.INVENTORY,
    "dsi": VisualLayerDomain.INVENTORY,
    "stockout_rate": VisualLayerDomain.INVENTORY,
    "fulfillment_accuracy_rate": VisualLayerDomain.OPERATIONS,
    "orders_at_sla_risk": VisualLayerDomain.OPERATIONS,
    "seller_fault_cancellation_rate": VisualLayerDomain.OPERATIONS,
    "csat": VisualLayerDomain.CUSTOMER_SERVICE,
    "after_sales_handling_time": VisualLayerDomain.CUSTOMER_SERVICE,
    "return_request_rate": VisualLayerDomain.CUSTOMER_SERVICE,
}

# visual_layer.md KPI → workflow rows (execution_layer keys aligned with webhook_catalog)
# Shop Status (SPS/AHR/VP): mock/fixture display only — Partner API fields unavailable;
# no workflow_keys until a live source exists (visual_layer.md §1).
KPI_WORKFLOW_KEYS: dict[KpiId, tuple[ExecutionWorkflowKey, ...]] = {
    "sps": (),
    "ahr": (),
    "violation_points": (),
    "net_revenue": ("optimize_product_2", "create_hero_product_1"),
    "aov": ("create_hero_product_1", "optimize_product_2"),
    "revenue_by_sku": ("optimize_product_2", "create_hero_product_1"),
    "conversion_rate_by_category": ("optimize_product_2",),
    "repeat_purchase_rate": ("create_hero_product_1", "optimize_product_2"),
    "roas": ("create_activity_7a", "update_activity_7c", "delete_activity_7b"),
    "cac": ("delete_activity_7b", "update_activity_7c"),
    "ctr": ("create_activity_7a", "update_activity_7c"),
    "inventory_turnover": ("replenish_inventory_3", "clear_excess_4"),
    "dsi": ("clear_excess_4",),
    "stockout_rate": ("replenish_inventory_3",),
    "fulfillment_accuracy_rate": ("process_order_5",),
    "orders_at_sla_risk": ("process_order_5",),
    "seller_fault_cancellation_rate": ("prevent_cancellation_8a",),
    "csat": (),
    "after_sales_handling_time": ("prevent_return_8b",),
    "return_request_rate": ("prevent_return_8b",),
}

NEW_SHOP_WORKFLOW_KEYS: frozenset[str] = frozenset(
    {
        "create_hero_product_1",
        "optimize_product_2",
        "process_order_5",
        "prevent_cancellation_8a",
    }
)

MID_LARGE_WORKFLOW_KEYS: frozenset[str] = frozenset(
    {
        "create_hero_product_1",
        "optimize_product_2",
        "create_activity_7a",
        "update_activity_7c",
        "delete_activity_7b",
        "replenish_inventory_3",
        "clear_excess_4",
        "process_order_5",
        "prevent_cancellation_8a",
        "prevent_return_8b",
        "prevent_refund_8c",
    }
)

WORKFLOW_DISPLAY_NAMES: dict[str, str] = {
    "create_hero_product_1": "Tạo sản phẩm chủ lực",
    "optimize_product_2": "Tối ưu sản phẩm",
    "create_activity_7a": "Tạo chiến dịch quảng cáo",
    "update_activity_7c": "Cập nhật chiến dịch",
    "delete_activity_7b": "Giảm ngân sách quảng cáo",
    "replenish_inventory_3": "Bổ sung tồn kho",
    "clear_excess_4": "Thanh lý tồn kho dư",
    "process_order_5": "Xử lý đơn hàng",
    "prevent_cancellation_8a": "Ngăn hủy đơn",
    "prevent_return_8b": "Ngăn hoàn trả",
    "prevent_refund_8c": "Ngăn hoàn tiền",
}


def get_workflows_for_profile(profile: ShopProfile) -> frozenset[str]:
    if profile == ShopProfile.NEW_SHOP:
        return NEW_SHOP_WORKFLOW_KEYS
    return MID_LARGE_WORKFLOW_KEYS
