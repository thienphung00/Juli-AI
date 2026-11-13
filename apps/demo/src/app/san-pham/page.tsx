import { SellerShopeePage } from "../../components/shopee-analytics/hosts";
import { SellerDataShopTabs } from "../../components/shopee-analytics/data-shop-tabs";

/** Dữ liệu shop › Sản phẩm: the shop's products, each opening its product page. */
export default function SanPhamPage() {
  return (
    <>
      <div className="sa-page">
        <SellerDataShopTabs active="san-pham" />
      </div>
      <SellerShopeePage screen="san-pham" />
    </>
  );
}
