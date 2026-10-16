import { body as chiSo } from "./chi-so-tiktok-shop-ctr-ctor-aov";
import { body as aiAnhVideo } from "./cong-cu-ai-tao-anh-video-san-pham-tiktok-shop";
import { body as congCu } from "./cong-cu-cho-nha-ban-tiktok-shop-2026";
import { body as phanTich } from "./cong-cu-phan-tich-tiktok-shop-2026";
import { body as doanhThuGiam } from "./doanh-thu-tiktok-shop-giam";
import { body as gmvLaGi } from "./gmv-la-gi-tiktok-shop";
import { body as daKenh } from "./phan-mem-quan-ly-ban-hang-da-kenh-2026";
import { body as khongRaDon } from "./tiktok-shop-khong-ra-don";
import { body as theSanPham } from "./toi-uu-the-san-pham-tiktok-shop";

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
};
