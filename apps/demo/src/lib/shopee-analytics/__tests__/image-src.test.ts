import { describe, expect, it } from "vitest";

import { SHOPEE_IMAGE_CDN, shopeeImageSrc } from "../image-src";

describe("shopeeImageSrc", () => {
  it("passes a full URL and a same-origin path through", () => {
    expect(shopeeImageSrc("https://down-vn.img.susercontent.com/file/x")).toBe("https://down-vn.img.susercontent.com/file/x");
    expect(shopeeImageSrc("/sample-shop/hn-nrc.svg")).toBe("/sample-shop/hn-nrc.svg");
  });

  it("turns Seller Centre's bare image id into a Shopee VN image URL", () => {
    expect(shopeeImageSrc("vn-11134207-7r98o-lstabc123")).toBe(`${SHOPEE_IMAGE_CDN}vn-11134207-7r98o-lstabc123`);
  });

  it("gives null for nothing or a value that is neither (the card shows its plain tile)", () => {
    for (const v of [null, undefined, "", "  ", "sample_hn-nrc_cover", "javascript:alert(1)", "//evil.example/x.png"]) {
      expect(shopeeImageSrc(v)).toBeNull();
    }
  });
});
