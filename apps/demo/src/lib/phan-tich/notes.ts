/** Backend `render.NOTES`, verbatim. */
export const ANALYSIS_NOTES = [
  "Mọi số trong bảng là trung bình mỗi ngày của từng khoảng 30 ngày, cộng từ số liệu từng ngày của TikTok.",
  "Tỷ lệ của một khoảng thời gian được tính từ tổng của khoảng đó (ví dụ CTR = tổng lượt nhấp chia tổng lượt hiển thị), giống cách Trung tâm người bán tính, không lấy trung bình các tỷ lệ từng ngày.",
  "CTR = lượt nhấp vào sản phẩm chia lượt hiển thị sản phẩm. Tỷ lệ thêm vào giỏ hàng = số lượt thêm vào giỏ chia lượt nhấp. CTOR = đơn hàng SKU chia lượt nhấp. AOV (SKU) = GMV chia đơn hàng SKU.",
  "GMV là GMV của TikTok, đã gồm đơn bị hủy và hoàn tiền; không trừ gì thêm.",
  "Thay đổi GMV được tách thành bốn phần theo tỷ lệ lôgarit của từng yếu tố; bốn phần cộng lại đúng bằng thay đổi GMV.",
  "Tab Cửa hàng không có số liệu thêm vào giỏ hàng; đơn hàng SKU của kênh này được ước tính bằng CTOR nhân lượt nhấp. Kênh này trùng một phần với các kênh khác nên không cộng vào tổng shop.",
  "Ở Video và LIVE của người bán, khách thường mua ngay không qua giỏ hàng, nên CTOR gồm cả khách mua thẳng.",
  'Mức tin cậy: "Rõ" khi mỗi kỳ có từ 30 đơn trở lên và khoảng tin cậy 90 % của chênh lệch không chứa 0; "Tham khảo" khi một kỳ có 10 đến 29 đơn hoặc chênh lệch nằm trong biên độ nhiễu; "Chưa đủ dữ liệu" khi một kỳ có dưới 10 đơn. Tỷ lệ dùng kiểm định hai tỷ lệ; lượt hiển thị, GMV và AOV dùng chuỗi số từng ngày.',
  "Kết luận sản phẩm: GMV đổi dưới 10 % là Ổn định; dưới 30 đơn hàng SKU trong một kỳ là Chưa đủ dữ liệu; nếu yếu tố lớn nhất là lượt hiển thị thì xét yếu tố tiếp theo; nếu là CTOR thì tách thành trước giỏ (tỷ lệ thêm vào giỏ) và sau giỏ (đơn trên lượt thêm vào giỏ).",
  "Một ngày là ngày flash sale khi flash sale chạy từ nửa ngày trở lên. Độ sâu thật so giá flash với giá đã giảm sẵn bởi chương trình giảm giá sản phẩm đang chạy, không so với giá niêm yết.",
  "Voucher được phân loại theo cấu hình (ngưỡng đơn, phạm vi, số lượt) so với giá một món phổ biến, là trung vị giá trị các đơn một món trong 30 ngày gần đây; không dựa vào tên voucher.",
  "Ngày sale nền tảng (ngày trùng tháng như 9/9, 10/10) được đánh dấu, không bị loại khỏi số liệu.",
  "Số liệu đơn hàng lấy theo ngày tạo đơn, theo giờ Việt Nam.",
];
