import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { detailOf, fakeReco, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { Card } from "../../../lib/shopee-decisions/types";
import { CardPage } from "../card-page";
import { renderReco } from "./harness";

/** A listing card (Sửa dòng đầu mô tả, tiêu đề, ảnh bìa, ẩn sản phẩm…) carries no five numbers. */
function listingCard(): Card {
  return {
    ...voucherCard(),
    id: "card-desc",
    family: "listing",
    family_label: "Tên, từ khoá, ảnh bìa",
    change_kind: "description_first_line",
    title: "Sửa dòng đầu mô tả — Túi Bio",
    status: "approved",
    five_numbers: null,
  } as unknown as Card;
}

describe("thẻ không có 5 con số (P96: in-progress listing cards crashed the page)", () => {
  it("renders an approved description card without the numbers table instead of crashing", async () => {
    renderReco(<CardPage from={null} id="card-desc" />, fakeReco({ detail: detailOf(listingCard()) }));
    expect(await screen.findByText("Sửa dòng đầu mô tả — Túi Bio")).toBeInTheDocument();
    expect(screen.queryByTestId("sd-numbers")).toBeNull();
    expect(screen.getByTestId("sd-no-numbers")).toHaveTextContent("không có 5 con số");
  });
});
