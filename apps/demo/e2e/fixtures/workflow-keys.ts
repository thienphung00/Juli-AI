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
    workflowKey: "replenish_inventory_3", // gitleaks:allow — documented mock workflow key
    title: "Nhập thêm hàng",
    isPriority: false,
  },
  {
    workflowKey: "clear_excess_4",
    title: "Xả hàng tồn",
    isPriority: false,
  },
  {
    workflowKey: "process_order_5",
    title: "Xử lý đơn hàng có rủi ro trễ hạn",
    isPriority: false,
  },
  {
    workflowKey: "create_activity_7a",
    title: "Tạo chương trình khuyến mãi",
    isPriority: false,
  },
  {
    workflowKey: "update_activity_7c",
    title: "Cập nhật chương trình khuyến mãi",
    isPriority: false,
  },
  {
    workflowKey: "delete_activity_7b",
    title: "Kết thúc chương trình khuyến mãi",
    isPriority: false,
  },
  {
    workflowKey: "prevent_cancellation_8a",
    title: "Xử lý yêu cầu huỷ đơn",
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
