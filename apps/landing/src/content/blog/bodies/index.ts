import { body as chiSo } from "./chi-so-tiktok-shop-ctr-ctor-aov";
import { body as aiAnhVideo } from "./cong-cu-ai-tao-anh-video-san-pham-tiktok-shop";
import { body as congCu } from "./cong-cu-cho-nha-ban-tiktok-shop-2026";
import { body as phanTich } from "./cong-cu-phan-tich-tiktok-shop-2026";
import { body as doanhThuGiam } from "./doanh-thu-tiktok-shop-giam";
import { body as gmvLaGi } from "./gmv-la-gi-tiktok-shop";
import { body as daKenh } from "./phan-mem-quan-ly-ban-hang-da-kenh-2026";
import { body as phiSan } from "./phi-san-tiktok-shop-2026";
import { body as luotHienThi } from "./san-pham-tiktok-shop-khong-co-luot-hien-thi";
import { body as giaTriDon } from "./tang-gia-tri-don-hang-trung-binh-tiktok-shop";
import { body as thueBanHang } from "./thue-ban-hang-tiktok-shop";
import { body as khachXemKhongMua } from "./khach-xem-nhung-khong-mua-tiktok-shop";
import { body as liveKhongRaDon } from "./live-tiktok-shop-khong-ra-don";
import { body as khongRaDon } from "./tiktok-shop-khong-ra-don";
import { body as theSanPham } from "./toi-uu-the-san-pham-tiktok-shop";
import { body as videoNhieuView } from "./video-tiktok-nhieu-view-khong-ra-don";
import { body as hoanHang } from "./ty-le-hoan-hang-tiktok-shop";
import { body as moTaSanPham } from "./mo-ta-san-pham-tiktok-shop";
import { body as quyDinhLivestream } from "./quy-dinh-livestream-ban-hang";
import { body as datTenSanPham } from "./dat-ten-san-pham-tiktok-shop";
import { body as anhBiaSanPham } from "./anh-bia-san-pham-tiktok-shop";
import { body as doHieuQua } from "./do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop";
import { body as sauSale } from "./doanh-thu-sau-sale-tiktok-shop";
import { body as dungThu } from "./dung-thu-juli-ai-mien-phi-3-thang";
import { body as keoGmvXuong } from "./tim-san-pham-keo-gmv-xuong-tiktok-shop";
import { body as ctrTheSanPham } from "./ctr-the-san-pham-thap-doi-tieu-de-anh-bia";
import { body as ctorMoTa } from "./ctor-thap-viet-lai-mo-ta-san-pham";

/**
 * Post bodies by slug. Only the post page imports this (the route registry
 * reads `../posts.ts`, which stays small).
 */
export const BLOG_BODIES: Readonly<Record<string, string>> = {
  "chi-so-tiktok-shop-ctr-ctor-aov": chiSo,
  "toi-uu-the-san-pham-tiktok-shop": theSanPham,
  "cong-cu-cho-nha-ban-tiktok-shop-2026": congCu,
  "gmv-la-gi-tiktok-shop": gmvLaGi,
  "tiktok-shop-khong-ra-don": khongRaDon,
  "doanh-thu-tiktok-shop-giam": doanhThuGiam,
  "phan-mem-quan-ly-ban-hang-da-kenh-2026": daKenh,
  "cong-cu-phan-tich-tiktok-shop-2026": phanTich,
  "cong-cu-ai-tao-anh-video-san-pham-tiktok-shop": aiAnhVideo,
  "san-pham-tiktok-shop-khong-co-luot-hien-thi": luotHienThi,
  "thue-ban-hang-tiktok-shop": thueBanHang,
  "video-tiktok-nhieu-view-khong-ra-don": videoNhieuView,
  "live-tiktok-shop-khong-ra-don": liveKhongRaDon,
  "ty-le-hoan-hang-tiktok-shop": hoanHang,
  "phi-san-tiktok-shop-2026": phiSan,
  "khach-xem-nhung-khong-mua-tiktok-shop": khachXemKhongMua,
  "tang-gia-tri-don-hang-trung-binh-tiktok-shop": giaTriDon,
  "mo-ta-san-pham-tiktok-shop": moTaSanPham,
  "quy-dinh-livestream-ban-hang": quyDinhLivestream,
  "dat-ten-san-pham-tiktok-shop": datTenSanPham,
  "anh-bia-san-pham-tiktok-shop": anhBiaSanPham,
  "do-hieu-qua-sau-khi-sua-san-pham-tiktok-shop": doHieuQua,
  "doanh-thu-sau-sale-tiktok-shop": sauSale,
  "dung-thu-juli-ai-mien-phi-3-thang": dungThu,
  "tim-san-pham-keo-gmv-xuong-tiktok-shop": keoGmvXuong,
  "ctr-the-san-pham-thap-doi-tieu-de-anh-bia": ctrTheSanPham,
  "ctor-thap-viet-lai-mo-ta-san-pham": ctorMoTa,
};
