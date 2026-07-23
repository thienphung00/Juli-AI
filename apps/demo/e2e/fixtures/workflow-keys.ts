/** Stable recommendation fixture order — mirrors apps/demo/src/lib/recommendations.ts */
export const RECOMMENDATION_WORKFLOWS = [
  {
    workflowKey: "create_hero_product_1",
    title: "Tạo sản phẩm nổi bật",
    isPriority: true,
  },
  {
    workflowKey: "optimize_product_2",
    title: "Tối ưu sản phẩm",
    isPriority: false,
  },
  {
    workflowKey: "replenish_inventory_3",
    title: "Nhập thêm hàng",
    isPriority: false,
  },
  {
    workflowKey: "clear_excess_4",
    title: "Xử lý tồn kho dư",
    isPriority: false,
  },
  {
    workflowKey: "process_order_5",
    title: "Xử lý đơn hàng",
    isPriority: false,
  },
  {
    workflowKey: "create_activity_7a",
    title: "Tạo hoạt động khuyến mãi",
    isPriority: false,
  },
  {
    workflowKey: "update_activity_7c",
    title: "Cập nhật hoạt động khuyến mãi",
    isPriority: false,
  },
  {
    workflowKey: "delete_activity_7b",
    title: "Xóa hoạt động khuyến mãi",
    isPriority: false,
  },
  {
    workflowKey: "prevent_cancellation_8a",
    title: "Xử lý yêu cầu hủy đơn",
    isPriority: false,
  },
  {
    workflowKey: "prevent_return_8b",
    title: "Xử lý yêu cầu trả hàng",
    isPriority: false,
  },
  {
    workflowKey: "prevent_refund_8c",
    title: "Xử lý yêu cầu hoàn tiền",
    isPriority: false,
  },
] as const;

export const PRIORITY_WORKFLOW = RECOMMENDATION_WORKFLOWS[0];
