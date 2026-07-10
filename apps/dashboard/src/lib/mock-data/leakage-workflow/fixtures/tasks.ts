import type { LeakageWorkflowTask } from "../schemas";

const SHOP_ID = "shop_trendy_viet_002";

function daysAgoIso(daysAgo: number): string {
  return new Date(Date.now() - daysAgo * 24 * 60 * 60 * 1000).toISOString();
}

export const LEAKAGE_WORKFLOW_TASKS: LeakageWorkflowTask[] = [
  {
    id: "task_leak_001",
    workflow: "leakage",
    type: "return_spike",
    severity: "high",
    title: "Tỷ lệ trả hàng tăng 19% — cao hơn ngưỡng an toàn",
    body: "7 ngày qua có 5 đơn trả hàng liên quan size và mô tả sản phẩm. Ước tính mất 2.094.000₫ GMV. Cập nhật bảng size và ảnh thực tế có thể giảm 40% trả hàng.",
    cta_label: "Xem chi tiết trả hàng",
    estimated_impact_vnd: 2_094_000,
    evidence_refs: ["ret_leak_001", "ret_leak_002", "ret_leak_004"],
    copy_source: "mock",
    workflow_status: "new",
    detail: {
      summary_vi:
        "Tỷ lệ trả hàng 7 ngày qua là 19%, cao hơn 6 điểm so với trung vị ngành. Phần lớn lý do liên quan size và mô tả sản phẩm.",
      charts: [
        { label_vi: "Tỷ lệ trả hàng 7 ngày", value: 19, unit: "%" },
        { label_vi: "Đơn trả hàng", value: 5, unit: "đơn" },
      ],
      benchmarks: [
        { label_vi: "Tỷ lệ trả hàng shop", shop_value: 0.19, peer_median: 0.13 },
      ],
      affected_product_ids: ["prod_ao_thun_oversize", "prod_ao_so_mi_ke"],
      estimated_gmv_leakage_vnd: 2_094_000,
    },
    evidence_bundle: {
      orders: [
        {
          id: "ord_leak_001",
          shop_id: SHOP_ID,
          buyer_id: "buyer_***1204",
          product_title: "Áo Thun Oversize Cotton — Trắng Kem",
          quantity: 1,
          total_vnd: 289_000,
          status: "returned",
          created_at: daysAgoIso(1),
        },
        {
          id: "ord_leak_006",
          shop_id: SHOP_ID,
          buyer_id: "buyer_***6618",
          product_title: "Áo Sơ Mi Kẻ Caro — Xanh Navy",
          quantity: 2,
          total_vnd: 598_000,
          status: "returned",
          created_at: daysAgoIso(5),
        },
      ],
      returns: [
        {
          id: "ret_leak_001",
          order_id: "ord_leak_001",
          buyer_id: "buyer_***1204",
          product_title: "Áo Thun Oversize Cotton — Trắng Kem",
          reason: "Size không vừa — đổi size không thành công",
          refund_vnd: 289_000,
          status: "approved",
          created_at: daysAgoIso(0),
          return_type: "item_swap",
        },
        {
          id: "ret_leak_002",
          order_id: "ord_leak_002",
          buyer_id: "buyer_***3389",
          product_title: "Quần Jeans Ống Rộng — Xanh Đậm",
          reason: "Chất vải khác mô tả",
          refund_vnd: 459_000,
          status: "approved",
          created_at: daysAgoIso(1),
          return_type: "empty_return",
        },
        {
          id: "ret_leak_004",
          order_id: "ord_leak_006",
          buyer_id: "buyer_***6618",
          product_title: "Áo Sơ Mi Kẻ Caro — Xanh Navy",
          reason: "Đổi ý — không cần nữa",
          refund_vnd: 598_000,
          status: "approved",
          created_at: daysAgoIso(4),
        },
      ],
      order_items: [],
      profile_metrics: [
        { key: "return_rate_30d", value: "0.19", label_vi: "Tỷ lệ trả hàng 30 ngày" },
      ],
      timeline_events: [
        {
          id: "tl_leak_001",
          label_vi: "Đỉnh trả hàng trong 7 ngày",
          occurred_at: daysAgoIso(0),
        },
      ],
    },
    root_cause: {
      classification: "seller_optimization",
      confidence: 0.82,
      summary_vi:
        "Nguyên nhân khả dĩ nhất là mô tả size và ảnh sản phẩm chưa khớp thực tế, dẫn đến trả hàng vì size/SNAD.",
      possible_causes: [
        "Bảng size thiếu số đo chi tiết",
        "Ảnh sản phẩm không phản ánh form thật",
        "Mô tả chất liệu chưa đủ cụ thể",
      ],
    },
    recommended_action: {
      action_type: "listing_update",
      summary_vi:
        "Cập nhật bảng size, ảnh thực tế và mô tả form fit cho các SKU bị trả hàng nhiều nhất.",
      checklist: [
        "Thêm bảng size cm cho áo thun oversize",
        "Bổ sung ảnh mặc thật cho áo sơ mi kẻ",
        "Làm rõ chất vải và độ co giãn",
      ],
    },
    execution_plan: {
      steps: [
        {
          id: "exec_return_spike_1",
          title_vi: "Tạo bản nháp cập nhật listing",
          description_vi: "Soạn thay đổi mô tả size và ảnh cho SKU bị ảnh hưởng.",
          mock_duration_ms: 1200,
        },
        {
          id: "exec_return_spike_2",
          title_vi: "Áp dụng cập nhật (mock)",
          description_vi: "Mô phỏng gửi cập nhật lên TikTok Shop.",
          mock_duration_ms: 800,
        },
      ],
    },
    success: {
      headline_vi: "Đã cập nhật listing — theo dõi tỷ lệ trả hàng 14 ngày tới",
      metrics_vi: [
        "Ước tính giảm 40% trả hàng liên quan size",
        "2 SKU được cập nhật bảng size và ảnh",
      ],
    },
    skip_reason: null,
    skip_note: null,
  },
  {
    id: "task_leak_002",
    workflow: "leakage",
    type: "buyer_cancellation_cluster",
    severity: "high",
    title: "Cụm buyer hủy đơn bất thường — 3 đơn trong 10 ngày",
    body: "Buyer buyer_***9912 hủy 3 đơn ngay sau khi đặt trong 10 ngày qua. Mẫu hủy đơn lặp lại có thể là rủi ro buyer — gói điều tra và báo cáo hỗ trợ.",
    cta_label: "Xem bằng chứng hủy đơn",
    estimated_impact_vnd: 1_207_000,
    evidence_refs: ["ord_leak_cancel_001", "ord_leak_cancel_002", "ord_leak_cancel_003"],
    copy_source: "mock",
    workflow_status: "new",
    detail: {
      summary_vi:
        "Phát hiện cụm 3 đơn hủy từ cùng buyer trong 10 ngày — cao hơn ngưỡng cảnh báo buyer-risk.",
      charts: [
        { label_vi: "Đơn hủy (buyer cụm)", value: 3, unit: "đơn" },
        { label_vi: "GMV mất ước tính", value: 1_207_000, unit: "VND" },
      ],
      benchmarks: [
        { label_vi: "Tỷ lệ hủy đơn shop", shop_value: 0.08, peer_median: 0.04 },
      ],
      affected_product_ids: [],
      estimated_gmv_leakage_vnd: 1_207_000,
    },
    evidence_bundle: {
      orders: [
        {
          id: "ord_leak_cancel_001",
          shop_id: SHOP_ID,
          buyer_id: "buyer_***9912",
          product_title: "Áo Thun Oversize Cotton — Trắng Kem",
          quantity: 1,
          total_vnd: 289_000,
          status: "cancelled",
          created_at: daysAgoIso(2),
        },
        {
          id: "ord_leak_cancel_002",
          shop_id: SHOP_ID,
          buyer_id: "buyer_***9912",
          product_title: "Quần Legging Yoga Cao Cấp",
          quantity: 1,
          total_vnd: 279_000,
          status: "cancelled",
          created_at: daysAgoIso(5),
        },
        {
          id: "ord_leak_cancel_003",
          shop_id: SHOP_ID,
          buyer_id: "buyer_***9912",
          product_title: "Áo Polo Nam Pique — Xanh Lá",
          quantity: 1,
          total_vnd: 319_000,
          status: "cancelled",
          created_at: daysAgoIso(8),
        },
      ],
      returns: [],
      order_items: [],
      profile_metrics: [
        { key: "cancellation_rate_7d", value: "0.08", label_vi: "Tỷ lệ hủy đơn 7 ngày" },
      ],
      timeline_events: [
        {
          id: "tl_leak_cancel_001",
          label_vi: "Buyer hủy đơn thứ 3 trong cụm",
          occurred_at: daysAgoIso(8),
        },
      ],
    },
    root_cause: {
      classification: "buyer_risk",
      confidence: 0.76,
      summary_vi:
        "Mẫu hủy đơn lặp lại từ cùng buyer trong thời gian ngắn — khả năng cao là hành vi buyer-risk, không phải lỗi listing.",
      possible_causes: [
        "Buyer đặt thử nhiều size rồi hủy",
        "Buyer lạm dụng khuyến mãi",
        "Địa chỉ giao hàng không hợp lệ",
      ],
    },
    recommended_action: {
      action_type: "investigation_package",
      summary_vi:
        "Tạo gói điều tra với timeline hủy đơn và soạn báo cáo hỗ trợ TikTok Shop.",
      checklist: [
        "Thu thập timeline 3 đơn hủy",
        "Đối chiếu pattern với ngưỡng buyer-risk",
        "Soạn báo cáo hỗ trợ (mock)",
      ],
    },
    execution_plan: {
      steps: [
        {
          id: "exec_cancel_1",
          title_vi: "Tạo báo cáo điều tra",
          description_vi: "Tổng hợp timeline và bằng chứng hủy đơn theo buyer.",
          mock_duration_ms: 1500,
        },
        {
          id: "exec_cancel_2",
          title_vi: "Soạn case hỗ trợ (mock)",
          description_vi: "Mô phỏng gửi báo cáo buyer-risk tới TikTok Shop.",
          mock_duration_ms: 1000,
        },
      ],
    },
    success: {
      headline_vi: "Đã tạo gói điều tra — case hỗ trợ sẵn sàng gửi",
      metrics_vi: [
        "3 đơn hủy được ghi nhận trong báo cáo",
        "Buyer được đánh dấu theo dõi (mock)",
      ],
    },
    skip_reason: null,
    skip_note: null,
  },
  {
    id: "task_leak_003",
    workflow: "leakage",
    type: "refund_cluster",
    severity: "medium",
    title: "Nhóm hoàn tiền tập trung ở áo sơ mi kẻ",
    body: "3/5 đơn trả hàng tuần này là áo sơ mi — lý do 'form rộng hơn ảnh'. Cập nhật mô tả form fit có thể giảm hoàn tiền.",
    cta_label: "Sửa listing",
    estimated_impact_vnd: 1_017_000,
    evidence_refs: ["ord_leak_006", "ord_leak_008"],
    copy_source: "mock",
    workflow_status: "new",
    detail: {
      summary_vi:
        "Hoàn tiền tập trung ở một SKU (áo sơ mi kẻ) — 60% trả hàng tuần này liên quan sản phẩm này.",
      charts: [
        { label_vi: "Hoàn tiền cụm SKU", value: 1_017_000, unit: "VND" },
        { label_vi: "Tỷ trọng trả hàng SKU", value: 60, unit: "%" },
      ],
      benchmarks: [
        { label_vi: "Hoàn tiền/SKU trung bình", shop_value: 339_000, peer_median: 180_000 },
      ],
      affected_product_ids: ["prod_ao_so_mi_ke"],
      estimated_gmv_leakage_vnd: 1_017_000,
    },
    evidence_bundle: {
      orders: [
        {
          id: "ord_leak_006",
          shop_id: SHOP_ID,
          buyer_id: "buyer_***6618",
          product_title: "Áo Sơ Mi Kẻ Caro — Xanh Navy",
          quantity: 2,
          total_vnd: 598_000,
          status: "returned",
          created_at: daysAgoIso(5),
        },
        {
          id: "ord_leak_008",
          shop_id: SHOP_ID,
          buyer_id: "buyer_***4487",
          product_title: "Đầm Suông Công Sở — Đen",
          quantity: 1,
          total_vnd: 419_000,
          status: "returned",
          created_at: daysAgoIso(7),
        },
      ],
      returns: [
        {
          id: "ret_leak_004",
          order_id: "ord_leak_006",
          buyer_id: "buyer_***6618",
          product_title: "Áo Sơ Mi Kẻ Caro — Xanh Navy",
          reason: "Đổi ý — không cần nữa",
          refund_vnd: 598_000,
          status: "approved",
          created_at: daysAgoIso(4),
        },
        {
          id: "ret_leak_005",
          order_id: "ord_leak_008",
          buyer_id: "buyer_***4487",
          product_title: "Đầm Suông Công Sở — Đen",
          reason: "Form rộng hơn ảnh",
          refund_vnd: 419_000,
          status: "approved",
          created_at: daysAgoIso(6),
        },
      ],
      order_items: [],
      profile_metrics: [],
      timeline_events: [],
    },
    root_cause: {
      classification: "seller_optimization",
      confidence: 0.71,
      summary_vi:
        "Hoàn tiền tập trung do mô tả form fit chưa chính xác — buyer kỳ vọng form ôm hơn thực tế.",
      possible_causes: [
        "Ảnh sản phẩm dùng model size nhỏ",
        "Mô tả 'regular fit' không rõ ràng",
        "Thiếu số đo ngực/vai trong listing",
      ],
    },
    recommended_action: {
      action_type: "monitoring",
      summary_vi:
        "Tạo báo cáo hoàn tiền theo SKU và thêm SKU vào danh sách theo dõi.",
      checklist: [
        "Xuất báo cáo hoàn tiền 14 ngày",
        "Thêm áo sơ mi kẻ vào watchlist",
        "Đặt cảnh báo khi hoàn tiền > 2 đơn/tuần",
      ],
    },
    execution_plan: {
      steps: [
        {
          id: "exec_refund_1",
          title_vi: "Tạo báo cáo hoàn tiền",
          description_vi: "Tổng hợp hoàn tiền theo SKU và lý do trả hàng.",
          mock_duration_ms: 900,
        },
        {
          id: "exec_refund_2",
          title_vi: "Thêm vào watchlist (mock)",
          description_vi: "Mô phỏng đánh dấu SKU theo dõi hoàn tiền.",
          mock_duration_ms: 600,
        },
      ],
    },
    success: {
      headline_vi: "SKU đã được thêm watchlist — theo dõi hoàn tiền 14 ngày",
      metrics_vi: [
        "Báo cáo hoàn tiền đã tạo",
        "1 SKU trong danh sách theo dõi",
      ],
    },
    skip_reason: null,
    skip_note: null,
  },
  {
    id: "task_leak_004",
    workflow: "leakage",
    type: "return_window_policy",
    severity: "low",
    title: "Rà soát chính sách đổi trả 7 ngày",
    body: "Shop đang dùng chính sách đổi trả 14 ngày — dài hơn 68% shop cùng ngành. Rút ngắn có thể giảm lạm dụng đổi trả.",
    cta_label: "Cập nhật chính sách",
    estimated_impact_vnd: 800_000,
    evidence_refs: ["profile:return_rate_30d=0.19"],
    copy_source: "mock",
    workflow_status: "new",
    detail: {
      summary_vi:
        "Chính sách đổi trả 14 ngày dài hơn trung vị ngành (7 ngày) — có thể tăng lạm dụng đổi trả.",
      charts: [
        { label_vi: "Cửa sổ đổi trả hiện tại", value: 14, unit: "ngày" },
        { label_vi: "Trung vị ngành", value: 7, unit: "ngày" },
      ],
      benchmarks: [
        { label_vi: "Cửa sổ đổi trả shop", shop_value: 14, peer_median: 7 },
      ],
      affected_product_ids: [],
      estimated_gmv_leakage_vnd: 800_000,
    },
    evidence_bundle: {
      orders: [],
      returns: [],
      order_items: [],
      profile_metrics: [
        { key: "return_rate_30d", value: "0.19", label_vi: "Tỷ lệ trả hàng 30 ngày" },
        { key: "return_window_days", value: "14", label_vi: "Cửa sổ đổi trả hiện tại" },
      ],
      timeline_events: [],
    },
    root_cause: {
      classification: "shop_config",
      confidence: 0.68,
      summary_vi:
        "Cấu hình cửa sổ đổi trả dài hơn chuẩn ngành — tăng khả năng lạm dụng chính sách.",
      possible_causes: [
        "Cửa sổ đổi trả 14 ngày chưa được rà soát",
        "Shop mới chưa tối ưu chính sách",
        "Ngành thời trang thường dùng 7 ngày",
      ],
    },
    recommended_action: {
      action_type: "shop_settings",
      summary_vi: "Rút ngắn cửa sổ đổi trả từ 14 xuống 7 ngày và cập nhật mô tả chính sách.",
      checklist: [
        "Xem lại chính sách đổi trả hiện tại",
        "So sánh với benchmark ngành",
        "Áp dụng cấu hình 7 ngày (mock)",
      ],
    },
    execution_plan: {
      steps: [
        {
          id: "exec_policy_1",
          title_vi: "Xem lại cài đặt shop",
          description_vi: "Kiểm tra cửa sổ đổi trả và điều khoản hiện tại.",
          mock_duration_ms: 700,
        },
        {
          id: "exec_policy_2",
          title_vi: "Áp dụng cấu hình 7 ngày (mock)",
          description_vi: "Mô phỏng cập nhật chính sách đổi trả shop.",
          mock_duration_ms: 800,
        },
      ],
    },
    success: {
      headline_vi: "Chính sách đổi trả đã cập nhật — theo dõi tỷ lệ trả hàng",
      metrics_vi: [
        "Cửa sổ đổi trả: 14 → 7 ngày (mock)",
        "Ước tính giảm lạm dụng đổi trả",
      ],
    },
    skip_reason: null,
    skip_note: null,
  },
];
