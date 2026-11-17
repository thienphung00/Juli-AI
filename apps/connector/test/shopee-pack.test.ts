// The Shopee pack behind the PlatformPack interface: the same hosts, readers, forms and saved
// signal the Connector used before the core / platforms split.
import { describe, expect, it } from "vitest";
import manifest from "../public/manifest.json";
import { registry } from "../src/platforms";
import { shopeePack } from "../src/platforms/shopee/pack";
import { READER_DATASETS, READER_IDS, READERS_ACTIVE, SELLER_CENTRE_ORIGIN } from "../src/platforms/shopee/config";
import { BANNER_FILLED, BANNER_PAGE_ONLY, JOB_LABELS } from "../src/platforms/shopee/fill/labels";

describe("the Shopee pack", () => {
  it("is the registry's first (legacy-scope) pack, found by its id and its pages", () => {
    expect(registry.legacy).toBe(shopeePack);
    expect(registry.get("shopee")).toBe(shopeePack);
    expect(registry.forUrl(`${SELLER_CENTRE_ORIGIN}/portal/product/123`)).toBe(shopeePack);
    expect(registry.forUrl("https://shopee.vn/search?keyword=x")).toBe(shopeePack);
  });

  it("holds exactly the manifest's Shopee host permissions and asks for nothing optional", () => {
    const hosts = (manifest.host_permissions as string[]).filter((h) => !h.includes("__JULI_API_ORIGIN__"));
    expect([...shopeePack.hosts].sort()).toEqual([...hosts].sort());
    expect(shopeePack.optionalHosts).toEqual([]);
  });

  it("recognises the fill-job form pages, other Seller Centre pages and the public search page", () => {
    expect(shopeePack.recognise(`${SELLER_CENTRE_ORIGIN}/portal/product/123`)).toBe("product_edit");
    expect(shopeePack.recognise(`${SELLER_CENTRE_ORIGIN}/portal/marketing/vouchers/new?usecase=1`)).toBe("voucher_new");
    expect(shopeePack.recognise(`${SELLER_CENTRE_ORIGIN}/datacenter/products`)).toBe("seller_centre");
    expect(shopeePack.recognise("https://shopee.vn/search?keyword=x")).toBe("market_search");
    expect(shopeePack.recognise("https://example.com/portal/product/1")).toBeNull();
    expect(shopeePack.recognise("not a url")).toBeNull();
  });

  it("lists every reader in schedule order with its datasets and switch", () => {
    expect(shopeePack.readers.map((r) => r.id)).toEqual([...READER_IDS]);
    for (const r of shopeePack.readers) {
      expect(r.datasets).toEqual(READER_DATASETS[r.id as keyof typeof READER_DATASETS]);
      expect(r.active).toBe(READERS_ACTIVE[r.id as keyof typeof READERS_ACTIVE]);
    }
  });

  it("has a form for every fill-job action", () => {
    expect(Object.keys(shopeePack.forms).sort()).toEqual(["ads_edit", "affiliate_commission", "combo", "description_first_line", "title", "voucher"]);
  });

  it("sees the person's save of a voucher or a combo in the page's own POST answer", () => {
    expect(shopeePack.savedSignal({ method: "POST", pathname: "/api/marketing/v4/voucher/create", body: { data: { voucher_id: 99 } } })).toEqual({ ref: "99" });
    expect(shopeePack.savedSignal({ method: "POST", pathname: "/api/marketing/v4/bundle_deal/create", body: { bundle_deal_id: "7" } })).toEqual({ ref: "7" });
    expect(shopeePack.savedSignal({ method: "GET", pathname: "/api/marketing/v4/voucher/create", body: { voucher_id: 99 } })).toBeNull();
    expect(shopeePack.savedSignal({ method: "POST", pathname: "/api/marketing/v4/voucher/list", body: { voucher_id: 99 } })).toBeNull();
  });

  it("keeps the on-page texts word for word", () => {
    expect(BANNER_FILLED).toBe("Juli đã điền — kiểm tra rồi bấm Lưu của Shopee");
    expect(BANNER_PAGE_ONLY).toBe("Trang đã mở. Làm theo các bước bên dưới rồi bấm nút của Shopee — Juli không bấm thay bạn.");
    expect(JOB_LABELS.filled).toBe("Juli đã điền đủ — kiểm tra rồi bấm nút của Shopee");
    expect(JOB_LABELS.halt).toBe("Shopee đang hỏi lại mật khẩu. Juli dừng lại và không mở thêm trang nào; hãy tự xác nhận trong Shopee.");
    expect(shopeePack.labels.name).toBe("Shopee");
  });
});
