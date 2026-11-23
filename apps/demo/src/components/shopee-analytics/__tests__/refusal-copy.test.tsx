import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ApiRefusal } from "../../../lib/shopee-analytics/client";
import { fakeApi } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { TongQuanView } from "../tong-quan";
import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { refusalCopy } from "../ui";
import { params, renderWith } from "./harness";

const REFUSALS: readonly ApiRefusal[] = ["not-shopee", "no-data", "not-materialized", "not-found", "invalid", "failed"];

describe("W3 · refusal copy follows the platform", () => {
  it("no refusal on a TikTok screen, or outside a host, names Shopee", () => {
    for (const platform of ["tiktok", null] as const) {
      for (const refusal of REFUSALS) {
        for (const sample of [false, true]) {
          const copy = refusalCopy(platform, refusal, sample);
          expect(`${copy.title} ${copy.body}`, `${platform} ${refusal}`).not.toMatch(/Shopee/);
        }
      }
    }
  });

  it("Shopee keeps its copy", () => {
    expect(refusalCopy("shopee", "not-shopee").title).toBe("Shop này không phải shop Shopee");
    expect(refusalCopy("shopee", "no-data").title).toBe("Shop chưa có dữ liệu Shopee");
    expect(refusalCopy("shopee", "no-data", true).body).toBe("Số liệu sẽ hiện ở đây khi có dữ liệu.");
  });

  it("a TikTok screen refused with no data shows TikTok Shop wording", async () => {
    const api = fakeApi();
    api.channelSplit = async () => {
      throw new ShopeeApiError(409, "no_tiktok_data", "x");
    };
    renderWith(<TongQuanView params={params()} />, api, { platform: "tiktok" });
    expect(await screen.findByTestId("sa-refusal-no-data")).toHaveTextContent("Shop chưa có dữ liệu TikTok Shop");
    expect(screen.getByTestId("sa-refusal-no-data").textContent).not.toMatch(/Shopee/);
  });
});
