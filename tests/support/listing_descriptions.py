"""Synthetic Vietnamese product descriptions for listing-structure tests (P76-3).

No real shop, brand or product names. Each value is the raw description a seller
might have saved; the keys name the shape being exercised.
"""

from __future__ import annotations

DESCRIPTIONS: dict[str, str] = {
    "headings_and_bullets": (
        "<h2>Giới thiệu sản phẩm</h2>"
        "<p>Bình giữ nhiệt dung tích 500ml, giữ nóng 12 giờ, giữ lạnh 24 giờ.</p>"
        "<h3>Đặc điểm nổi bật</h3>"
        "<ul><li>Thép không gỉ 304</li><li>Nắp kín chống rò rỉ</li><li>Dễ vệ sinh</li></ul>"
        "<p><strong>Bảo hành 6 tháng</strong></p>"
        "<p>Liên hệ shop để được tư vấn.</p>"
    ),
    "plain_text_emoji": (
        "🌿 Bộ chăm sóc da mẫu thử\n"
        "✅ Dịu nhẹ, phù hợp da nhạy cảm\n"
        "✅ Không chứa cồn\n\n"
        "📦 Giao hàng toàn quốc trong 3 ngày.\n\n"
        "Cảm ơn bạn đã ghé shop 💚"
    ),
    "br_only": (
        "Áo thun cotton mềm mịn<br>Size M, L, XL<br><br>"
        "Chất vải co giãn 4 chiều<br>Giặt máy thoải mái<br><br><br>Giao nhanh 2 ngày"
    ),
    "nested_lists": (
        "<p>Thông số kỹ thuật:</p>"
        "<ul><li>Kích thước<ul><li>Dài 20cm</li><li>Rộng 10cm</li></ul></li>"
        "<li>Chất liệu<ol><li>Nhựa ABS</li><li>Silicone</li></ol></li></ul>"
        "<ol><li>Mở hộp</li><li>Kiểm tra</li></ol>"
    ),
    "messy_html": (
        "<div><span style='color:red'>Ốp lưng   điện thoại</span>\n"
        "<b>Chống sốc</b> &amp; chống trượt"
        "<p>&nbsp;</p><div>Hàng <i>có sẵn</i><br/>Đổi trả trong 7 ngày</div></div>"
        "<ul><li>  Viền cao  </li><li></li></ul>"
    ),
    "bold_headings": (
        "<p><b>Công dụng</b></p><p>Làm sạch sâu, dưỡng ẩm.</p>"
        "<strong>Hướng dẫn sử dụng</strong><br>Thoa đều lên da mặt.<br>Rửa lại bằng nước sạch."
    ),
    "with_image": (
        '<p>Mẫu mới về</p><img src="https://example.invalid/a.jpg" width="400">'
        "<ul><li>Màu đen</li><li>Màu trắng</li></ul>"
    ),
    "single_line": "Khăn lau đa năng, thấm hút tốt.",
    "empty": "",
    "whitespace_only": " \n\t ",
}
