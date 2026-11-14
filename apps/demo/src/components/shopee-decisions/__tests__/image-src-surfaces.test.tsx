import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Ini } from "../../shopee-analytics/ui";
import { CoverPreview } from "../builder-p92/panels-listing";

const ID = "vn-11134207-81ztc-mkajp4qtx79kbb";
const URL = `https://down-vn.img.susercontent.com/file/${ID}`;
const OVERLAY = { layout: "banner_bottom", badge_text: "Giảm 15%" } as const;

describe("Shopee image ids reach every product image", () => {
  it("the Ảnh bìa preview shows the product photo behind the text overlay", () => {
    const { container, getByTestId } = render(<CoverPreview image={ID} overlay={OVERLAY} />);
    expect(container.querySelector("img.p2-cover__img")?.getAttribute("src")).toBe(URL);
    expect(getByTestId("p2-cover-preview")).toHaveTextContent("Giảm 15%");
  });

  it("the Ảnh bìa preview keeps its placeholder when there is no usable image", () => {
    const { container } = render(<CoverPreview image="not-an-image-id" overlay={OVERLAY} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container).toHaveTextContent("ảnh thật, giữ nguyên");
  });

  it("the product tile shows the photo, or the initials without one", () => {
    const withPhoto = render(<Ini src={ID} text="GT" />);
    expect(withPhoto.container.querySelector("img")?.getAttribute("src")).toBe(URL);
    const without = render(<Ini src={null} text="GT" />);
    expect(without.container.querySelector("img")).toBeNull();
    expect(without.container).toHaveTextContent("GT");
  });
});
