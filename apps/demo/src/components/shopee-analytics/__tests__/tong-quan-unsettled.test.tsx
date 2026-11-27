import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { channelSplit, fakeApi } from "../../../lib/shopee-analytics/__tests__/fixtures";
import type { ChannelSplit } from "../../../lib/shopee-analytics/types";
import { TongQuanView } from "../tong-quan";
import { params, renderWith } from "./harness";

/** Owner #101: Tổng quan flags orders completed over 2 days ago with no settlement yet. */

const withUnsettled = (unsettled: NonNullable<NonNullable<ChannelSplit["freshness"]>["unsettled_orders"]>) =>
  channelSplit({ freshness: { unsettled_orders: unsettled } });

describe("Tổng quan: unsettled orders (owner #101)", () => {
  it("shows the count next to Cập nhật, the oldest completion day in its title", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi({ split: withUnsettled({ count: 3, oldest_completed_on: "2026-11-20" }) }));
    const chip = await screen.findByTestId("sa-unsettled");
    expect(chip).toHaveTextContent(/^3 đơn chưa có thanh toán$/);
    expect(chip).toHaveAttribute("title", "Đơn sớm nhất hoàn thành 20/11");
  });

  it("no chip when every completed order is settled", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi({ split: withUnsettled({ count: 0, oldest_completed_on: null }) }));
    await screen.findByTestId("sa-fresh");
    expect(screen.queryByTestId("sa-unsettled")).toBeNull();
  });

  it("no chip without the field (TikTok, older servers)", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    await screen.findByTestId("sa-fresh");
    expect(screen.queryByTestId("sa-unsettled")).toBeNull();
  });
});
