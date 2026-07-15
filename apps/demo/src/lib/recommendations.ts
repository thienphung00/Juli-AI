import { formatVND } from "@juli/utils";

export interface RecommendationFixture {
  capabilityLabel: string;
  confidenceLabel: string;
  confidenceLevel: "high" | "medium" | "low";
  eligibility: string;
  evidence: string;
  expectedImpactLabel: string;
  isPriority: boolean;
  knownLimits: string;
  reasoning: string;
  risks: string;
  signal: string;
  title: string;
  toolName: string;
  workflowKey: string;
}

const FBS_EXECUTABLE = "Có thể thực thi qua FBS";

export const recommendationFixtures = [
  {
    workflowKey: "create_hero_product_1",
    toolName: "listing.create_hero_product",
    title: "Tạo sản phẩm nổi bật",
    isPriority: true,
    confidenceLevel: "high",
    confidenceLabel: "Độ tin cậy: Cao",
    capabilityLabel: FBS_EXECUTABLE,
    signal:
      "Nhóm ngành chăm sóc da đang có nhu cầu tăng nhưng shop chưa có sản phẩm nào đáp ứng.",
    expectedImpactLabel: "—",
    reasoning:
      "Juli phát hiện khoảng trống nhu cầu chưa được đáp ứng trong danh mục chăm sóc da.",
    evidence:
      "Đã theo dõi tín hiệu nhu cầu trong khoảng thời gian tối thiểu theo quy tắc hiện có; chưa có sản phẩm nào của shop đang hoạt động trong danh mục này.",
    eligibility:
      "Cần shop đã được xác thực, khả năng tạo sản phẩm, danh mục xác định được, đủ thuộc tính/nhãn hiệu/hình ảnh bắt buộc, và một kho FBS được gán.",
    knownLimits:
      "Ngưỡng chính xác để phát hiện khoảng trống danh mục chưa được xác định — Juli không tự suy diễn con số này. Luồng FBT (giao hàng do TikTok quản lý) cho sản phẩm mới chưa được hỗ trợ.",
    risks:
      "Nếu thiếu thuộc tính hoặc nhãn hiệu bắt buộc, sản phẩm sẽ cần bổ sung thông tin trước khi có thể tạo.",
  },
  {
    workflowKey: "optimize_product_2",
    toolName: "listing.optimize_product",
    title: "Tối ưu sản phẩm",
    isPriority: false,
    confidenceLevel: "medium",
    confidenceLabel: "Độ tin cậy: Trung bình",
    capabilityLabel: FBS_EXECUTABLE,
    signal:
      'Tiêu đề và ảnh sản phẩm "Son môi số 12" chưa đạt điểm chất lượng tối thiểu.',
    expectedImpactLabel: formatVND(2_100_000),
    reasoning:
      "Hiệu suất bán hàng thực tế cho thấy sản phẩm này có thể tối ưu tiêu đề, ảnh và giá.",
    evidence:
      "Dữ liệu hiệu suất theo SKU và tỷ lệ chuyển đổi theo danh mục cho thấy sản phẩm chưa đạt mức kỳ vọng.",
    eligibility:
      "Cần một tin đăng đã xác thực và có thể sửa, đủ dữ liệu hiệu suất thực tế, thuộc tính danh mục hợp lệ, và giá trên mức sàn lợi nhuận của shop.",
    knownLimits:
      "Ngưỡng chính xác và khoảng thời gian đánh giá để đề xuất tối ưu chưa được xác định.",
    risks: "Thay đổi giá sẽ bị chặn nếu thấp hơn mức sàn lợi nhuận đã cấu hình.",
  },
  {
    workflowKey: "replenish_inventory_3", // gitleaks:allow — documented mock workflow key
    toolName: "inventory.replenish",
    title: "Nhập thêm hàng",
    isPriority: false,
    confidenceLevel: "high",
    confidenceLabel: "Độ tin cậy: Cao",
    capabilityLabel: FBS_EXECUTABLE,
    signal:
      'Tồn kho "Kem chống nắng SPF50" còn đủ cho 4 ngày bán theo tốc độ hiện tại.',
    expectedImpactLabel: "—",
    reasoning:
      "Tốc độ bán hiện tại cho thấy sản phẩm sẽ hết hàng trong vài ngày tới nếu không nhập thêm.",
    evidence: "Số lượng tồn kho hiện tại tại kho FBS và tốc độ bán gần đây.",
    eligibility:
      "Cần một SKU đã xác thực, kho FBS xác định, số liệu tồn kho hiện tại, và số lượng đặt hàng lại được duyệt.",
    knownLimits:
      "Ngưỡng hết hàng chính xác, khoảng thời gian dự báo, và hợp đồng với nhà cung cấp/ERP chưa được xác định — luồng FBT (giao hàng do TikTok quản lý) cho việc nhập hàng cũng chưa được hỗ trợ.",
    risks:
      "Việc cập nhật tồn kho cần xác nhận số lượng nhận hàng thực tế trước khi ghi nhận.",
  },
  {
    workflowKey: "clear_excess_4",
    toolName: "inventory.clear_excess",
    title: "Xả hàng tồn",
    isPriority: false,
    confidenceLevel: "medium",
    confidenceLabel: "Độ tin cậy: Trung bình",
    capabilityLabel: FBS_EXECUTABLE,
    signal:
      'Lô "Áo khoác gió mùa hè" tồn quá 60 ngày, vượt ngưỡng quay vòng hàng đã đặt.',
    expectedImpactLabel: formatVND(1_600_000),
    reasoning:
      "Hàng tồn lâu ngày đang chiếm kho và có thể được xả bằng khuyến mãi hoặc giảm giá.",
    evidence:
      "Dữ liệu tuổi hàng tồn và tốc độ quay vòng cho thấy lô hàng này bán chậm hơn mức bình thường.",
    eligibility:
      "Cần một SKU FBS đã xác thực, tồn kho hiện tại, giá có thể sửa, đủ điều kiện chạy khuyến mãi, và điều khoản xả hàng được shop duyệt.",
    knownLimits:
      "Ngưỡng tốc độ quay vòng/tuổi hàng chính xác để kích hoạt đề xuất này chưa được xác định. Juli không tự suy diễn kết quả đủ điều kiện Flash Sale.",
    risks:
      "Việc xoá tồn kho về 0 là bước không thể hoàn tác — chỉ thực hiện sau khi có xác nhận thực tế.",
  },
  {
    workflowKey: "process_order_5",
    toolName: "fulfillment.process_order",
    title: "Xử lý đơn hàng có rủi ro trễ hạn",
    isPriority: false,
    confidenceLevel: "high",
    confidenceLabel: "Độ tin cậy: Cao",
    capabilityLabel: FBS_EXECUTABLE,
    signal:
      "6 đơn hàng đang chờ xử lý và có nguy cơ trễ hạn giao vận theo thời hạn SLA.",
    expectedImpactLabel: "Giảm rủi ro trễ hạn cho 6 đơn hàng",
    reasoning:
      "Các đơn hàng này đang ở trạng thái chờ giao và gần tới hạn xử lý theo SLA.",
    evidence:
      "Trạng thái đơn hàng, hạn chót, và loại vận chuyển được đọc trực tiếp từ đơn hàng đã xác thực.",
    eligibility:
      "Cần đơn hàng FBS đã xác thực, địa chỉ đầy đủ, trạng thái chờ giao hàng, và thông tin vận chuyển/lấy hàng hợp lệ.",
    knownLimits:
      "Ngưỡng thời gian chính xác để tạo đề xuất này chưa được xác định. Đơn hàng FBT (giao hàng do TikTok quản lý) chỉ được đọc/theo dõi, chưa hỗ trợ xử lý trực tiếp.",
    risks:
      "Không thể tạo hoặc giao lô hàng khi đơn đang ở trạng thái tạm giữ; thông tin khách hàng chỉ hiển thị ở mức tối thiểu cần thiết.",
  },
  {
    workflowKey: "create_activity_7a",
    toolName: "promotion.create_activity",
    title: "Quản lý chương trình khuyến mãi",
    isPriority: false,
    confidenceLevel: "medium",
    confidenceLabel: "Độ tin cậy: Trung bình",
    capabilityLabel: FBS_EXECUTABLE,
    signal:
      "Nhóm sản phẩm chăm sóc da phù hợp để chạy một chương trình khuyến mãi mới trong tuần này.",
    expectedImpactLabel: "—",
    reasoning:
      "Các SKU này đủ điều kiện chạy khuyến mãi và chưa có chương trình đang hoạt động trùng lặp.",
    evidence:
      "Giá và SKU hiện tại đã được xác thực; không có chương trình khuyến mãi trùng lặp đang hoạt động.",
    eligibility:
      "Cần shop đã xác thực, SKU/giá đã biết, và đủ điều kiện chạy khuyến mãi.",
    knownLimits:
      "Ngưỡng tăng trưởng/hiệu suất để tạo đề xuất này chưa được xác định. Việc tìm chương trình khuyến mãi hiện có theo từ khoá chưa được hỗ trợ — cập nhật/kết thúc chương trình chỉ áp dụng cho một `activity_id` đã biết (nhánh update_activity_7c/delete_activity_7b).",
    risks:
      "Không có số tiền giảm giá hoặc tác động nào được tự suy diễn — mọi thay đổi cần shop xác nhận trước khi gửi.",
  },
  {
    workflowKey: "prevent_cancellation_8a",
    toolName: "returns.prevent_cancellation",
    title: "Xử lý yêu cầu huỷ đơn",
    isPriority: false,
    confidenceLevel: "medium",
    confidenceLabel: "Độ tin cậy: Trung bình",
    capabilityLabel: FBS_EXECUTABLE,
    signal: "1 yêu cầu huỷ đơn đang chờ quyết định trước hạn xử lý.",
    expectedImpactLabel: "—",
    reasoning:
      "Người mua đã gửi yêu cầu huỷ đơn trước khi hàng được giao; shop cần quyết định phê duyệt hoặc từ chối.",
    evidence:
      "Trạng thái yêu cầu, hạn xử lý, và lý do người mua nêu được đọc trực tiếp từ đơn hàng.",
    eligibility:
      "Áp dụng trước khi giao hàng và trong thời gian shop còn được phép quyết định.",
    knownLimits:
      "Chính sách tự động phê duyệt/từ chối chính xác chưa được xác định — mọi trường hợp chưa rõ ràng đều cần shop tự quyết định, Juli không tự động xử lý thay.",
    risks:
      "Việc giữ hàng chờ quyết định sẽ tự động giải phóng theo kết quả — không có thao tác cập nhật tồn kho nào được thực hiện thủ công.",
  },
  {
    workflowKey: "prevent_return_8b",
    toolName: "returns.prevent_return",
    title: "Xử lý yêu cầu trả hàng",
    isPriority: false,
    confidenceLevel: "medium",
    confidenceLabel: "Độ tin cậy: Trung bình",
    capabilityLabel: FBS_EXECUTABLE,
    signal: "1 yêu cầu trả hàng sau giao đang chờ xác minh và quyết định.",
    expectedImpactLabel: "—",
    reasoning:
      "Người mua đã gửi yêu cầu trả hàng sau khi nhận hàng; cần xác minh tình trạng thực tế trước khi quyết định.",
    evidence:
      "Trạng thái yêu cầu và lý do trả hàng được đọc trực tiếp; dữ liệu rủi ro dựa trên quy tắc hiện có, không phải điểm số dự đoán.",
    eligibility:
      "Cần yêu cầu còn trong thời hạn xử lý; việc nhập lại kho FBS chỉ áp dụng sau khi kiểm tra thực tế xác nhận hàng còn bán được.",
    knownLimits:
      "Chính sách/ngưỡng gian lận tự động chưa được xác định và không hiển thị như một khả năng đang hoạt động. Luồng FBT (giao hàng do TikTok quản lý) chỉ ghi nhận, chưa hỗ trợ xử lý trực tiếp.",
    risks:
      "Chỉ nhập lại kho sau khi có kết quả kiểm tra thực tế — không tự động nhập lại kho khi chưa xác minh.",
  },
  {
    workflowKey: "prevent_refund_8c",
    toolName: "returns.prevent_refund",
    title: "Xử lý yêu cầu hoàn tiền",
    isPriority: false,
    confidenceLevel: "high",
    confidenceLabel: "Độ tin cậy: Cao",
    capabilityLabel: FBS_EXECUTABLE,
    signal: "1 yêu cầu hoàn tiền đang chờ quyết định sau khi có kết quả tính toán.",
    expectedImpactLabel: "—",
    reasoning:
      "Yêu cầu hoàn tiền đã được ghi nhận và có kết quả tính toán số tiền hợp lệ.",
    evidence:
      "Yêu cầu được xác thực qua hệ thống hậu mãi; số tiền tính toán chỉ hiển thị khi có kết quả hợp lệ.",
    eligibility:
      "Cần một yêu cầu hậu mãi hợp lệ và kết quả tính toán hoàn tiền thành công.",
    knownLimits:
      "Chính sách tự động xử lý/leo thang và ngưỡng đề xuất chính xác chưa được xác định.",
    risks:
      "Không có hoàn tiền nào được xác nhận đã thực hiện trước khi có xác nhận trạng thái cuối cùng; không có hành động tồn kho nào gắn với luồng này (được xử lý riêng ở luồng trả hàng).",
  },
] as const satisfies readonly RecommendationFixture[];
