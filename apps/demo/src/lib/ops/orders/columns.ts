/**
 * The order export's header allowlist (Đơn hàng › Xuất, `Order.all.<from>_<to>.xlsx`, sheet
 * `orders`, 62 columns). The SAME table as `scripts/shopee_exports/orders.py`; the parity
 * fixture in `__fixtures__/` keeps the two parsers equal.
 *
 * Every header must be in {@link READ} (its cells are used) or {@link IGNORED} (known; its
 * cells are never decoded). Any other header stops the load: Seller Centre changed the export,
 * and an unreviewed column might carry a buyer's data.
 */

export type Scope = "line" | "order";

/** header -> [field, scope]. These are the ONLY columns whose cells are ever decoded. */
export const READ: Readonly<Record<string, readonly [string, Scope]>> = {
  "Mã đơn hàng": ["order_id", "order"],
  "Ngày đặt hàng": ["ordered_at", "order"],
  "Trạng Thái Đơn Hàng": ["status", "order"],
  "Thời gian giao hàng": ["delivered_at", "order"],
  "Trạng thái Trả hàng/Hoàn tiền": ["return_status", "line"],
  "SKU sản phẩm": ["sku", "line"],
  "SKU phân loại hàng": ["variation_sku", "line"],
  "Giá gốc": ["original_price", "line"],
  "Được Shopee trợ giá": ["shopee_subsidy", "line"],
  "Tổng số tiền được người bán trợ giá": ["seller_subsidy", "line"],
  "Giá ưu đãi": ["deal_price", "line"],
  "Số lượng": ["qty", "line"],
  "Số lượng sản phẩm được hoàn trả": ["returned_qty", "line"],
  "Tổng giá trị đơn hàng (VND)": ["order_value", "order"],
  "Mã giảm giá của Shop": ["shop_voucher", "order"],
  "Mã giảm giá của Shopee": ["platform_voucher", "order"],
  "Giảm giá từ combo Shopee": ["shopee_combo", "order"],
  "Giảm giá từ Combo của Shop": ["shop_combo", "order"],
  "Số tiền được giảm khi thanh toán bằng thẻ Ghi nợ": ["bank_promo", "order"],
  "Phí vận chuyển mà người mua trả": ["buyer_shipping_fee", "order"],
  "Tổng số tiền người mua thanh toán": ["buyer_total", "order"],
  "Thời gian hoàn thành đơn hàng": ["completed_at", "order"],
  "Thời gian đơn hàng được thanh toán": ["paid_at", "order"],
  "Phí cố định": ["fee_fixed", "order"],
  "Phí Dịch Vụ": ["fee_service", "order"],
  "Phí xử lý giao dịch": ["fee_payment", "order"],
};

/** Known headers whose cells are NEVER decoded (buyer data, identifiers, free text, names ...). */
export const IGNORED: ReadonlySet<string> = new Set([
  "Mã Kiện Hàng",
  "Sản Phẩm Bán Chạy",
  "Lý do hủy",
  "Nhận xét từ Người mua",
  "Mã vận đơn",
  "Đơn Vị Vận Chuyển",
  "Phương thức giao hàng",
  "Loại đơn hàng",
  "Ngày giao hàng dự kiến",
  "Ngày gửi hàng",
  "Tên sản phẩm",
  "Cân nặng sản phẩm",
  "Tổng cân nặng",
  "Tên phân loại hàng",
  "Người bán trợ giá",
  "Tổng số tiền Người mua thanh toán",
  "Hoàn Xu",
  "Chỉ tiêu Combo Khuyến Mãi",
  "Shopee Xu được hoàn",
  "Trade-in Discount",
  "Trade-in Bonus",
  "Phí vận chuyển (dự kiến)",
  "Trade-in Bonus by Seller",
  "Phí vận chuyển tài trợ bởi Shopee (dự kiến)",
  "Phí vận chuyển trả hàng (đơn Trả hàng/hoàn tiền)",
  "Phương thức thanh toán",
  "Tiền ký quỹ",
  "Người Mua",
  "Tên Người nhận",
  "Số điện thoại",
  "Tỉnh/Thành phố",
  "TP / Quận / Huyện",
  "Quận",
  "Địa chỉ nhận hàng",
  "Quốc gia",
  "Ghi chú",
]);

/** Headers that must never have a value read, whatever else changes (the buyer's own data). */
export const BUYER_HEADERS: ReadonlySet<string> = new Set([
  "Mã Kiện Hàng",
  "Nhận xét từ Người mua",
  "Mã vận đơn",
  "Người Mua",
  "Tên Người nhận",
  "Số điện thoại",
  "Tỉnh/Thành phố",
  "TP / Quận / Huyện",
  "Quận",
  "Địa chỉ nhận hàng",
  "Quốc gia",
  "Ghi chú",
]);

/** Headers that must be present: without them a line cannot be formed. */
export const REQUIRED: readonly string[] = [
  "Mã đơn hàng",
  "Ngày đặt hàng",
  "Trạng Thái Đơn Hàng",
  "SKU sản phẩm",
  "Giá gốc",
  "Giá ưu đãi",
  "Số lượng",
];

/** Order-level money fields: repeated on each line of an order, split by line value. */
export const ORDER_MONEY: readonly string[] = [
  "order_value",
  "shop_voucher",
  "platform_voucher",
  "shopee_combo",
  "shop_combo",
  "bank_promo",
  "buyer_shipping_fee",
  "buyer_total",
  "fee_fixed",
  "fee_service",
  "fee_payment",
];

export const SHEET = "orders";
export const MAX_UPLOAD_LINES = 1000;
