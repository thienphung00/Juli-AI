/** Stable recommendation fixture order — mirrors apps/demo/src/lib/recommendations.ts */
export const RECOMMENDATION_WORKFLOWS = [
  {
    workflowKey: "create_hero_product_1",
    subject: "Danh mục chăm sóc da",
    title: "Tạo sản phẩm nổi bật",
    isPriority: true,
  },
  {
    workflowKey: "optimize_product_2",
    subject: "Son môi số 12",
    title: "Tối ưu sản phẩm",
    isPriority: false,
  },
  {
    workflowKey: "replenish_inventory_3", // gitleaks:allow — documented mock workflow key
    subject: "Kem chống nắng SPF50",
    title: "Nhập thêm hàng",
    isPriority: false,
  },
  {
    workflowKey: "clear_excess_4",
    subject: "Áo khoác gió mùa hè",
    title: "Xả hàng tồn",
    isPriority: false,
  },
  {
    workflowKey: "process_order_5",
    subject: "6 đơn hàng chờ xử lý",
    title: "Xử lý đơn hàng có rủi ro trễ hạn",
    isPriority: false,
  },
  {
    workflowKey: "create_activity_7a",
    subject: "Nhóm chăm sóc da",
    title: "Tạo chương trình khuyến mãi",
    isPriority: false,
  },
  {
    workflowKey: "update_activity_7c",
    subject: "Flash Sale chăm sóc da",
    title: "Cập nhật chương trình khuyến mãi",
    isPriority: false,
  },
  {
    workflowKey: "delete_activity_7b",
    subject: "Giảm giá trực tiếp mùa hè",
    title: "Kết thúc chương trình khuyến mãi",
    isPriority: false,
  },
  {
    workflowKey: "prevent_cancellation_8a",
    subject: "1 yêu cầu huỷ đơn",
    title: "Xử lý yêu cầu huỷ đơn",
    isPriority: false,
  },
  {
    workflowKey: "prevent_return_8b",
    subject: "1 yêu cầu trả hàng",
    title: "Xử lý yêu cầu trả hàng",
    isPriority: false,
  },
  {
    workflowKey: "prevent_refund_8c",
    subject: "1 yêu cầu hoàn tiền",
    title: "Xử lý yêu cầu hoàn tiền",
    isPriority: false,
  },
] as const;

export const PRIORITY_WORKFLOW = RECOMMENDATION_WORKFLOWS[0];
