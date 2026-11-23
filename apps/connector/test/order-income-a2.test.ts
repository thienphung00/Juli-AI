// @vitest-environment jsdom
// batch-1123-a2 C-A10: "Doanh thu từng đơn: Tạm dừng: Seller Centre đã thay đổi" on 0.3.32. The only
// drift path of order_income is mapOrderIncome's "components.final_amount" (no answer with a final
// amount). The order page reader (0.3.32) posted the page's income rows as soon as the page showed
// its product lines, so a page read before (or without) its "Doanh Thu Đơn Hàng" row became an
// answer without a final amount: drift, and the dataset stopped for the whole version. Now the
// reader waits for that row, a page read without it is never drift, and the job says so.
// DOM per the read-only captures of 22/11 and 23/11 (c/order-detail-page.md, c2/05); values synthetic.
import { describe, expect, it } from "vitest";
import { incomeItemsIn, pageItemsIn } from "../src/platforms/shopee/order-page-dom";
import { mapOrderIncome, pageIncomeFinal } from "../src/platforms/shopee/orders-map";
import { INCOME_NOT_SHOWN, pollingWaitFor, type ReaderEnv, type ReaderResponse, runReaderJob } from "../src/platforms/shopee/reader";
import { mapReaderJob } from "../src/platforms/shopee/reader-map";
import { Pacer } from "../src/platforms/shopee/runner";

const SC = "https://banhang.shopee.vn";
const NOW = Date.UTC(2026, 10, 23, 11, 0, 0);
const row = (label: string, value: string) =>
  `<div class="income-item"><div class="income-label"><div class="income-label-text">${label}</div></div><div class="income-value">${value}</div></div>`;
const LINE = `<div class="product-item product"><div class="product-meta"><div>Phân loại: Mẫu A</div><div>SKU phân loại: SKU-A</div></div><div>1</div><div>₫100.000</div></div>`;
const FEES = `<div class="income-container">${row("Giá sản phẩm", "₫100.000")}${row("Phí cố định", "-₫16.000")}${row("Phí Dịch Vụ", "-₫8.500")}`;
const FINAL = row("Doanh Thu Đơn Hàng", "₫65.735");

function envFor(doc: Document, onSleep?: (clock: number) => void): ReaderEnv {
  let clock = NOW;
  const sleep = async (ms: number) => {
    clock += ms;
    onSleep?.(clock);
  };
  return {
    origin: SC,
    pacer: new Pacer({ sleep, now: () => clock, random: () => 0 }),
    now: () => clock,
    session: () => ({}),
    hasSession: () => true,
    template: () => undefined,
    waitFor: pollingWaitFor(sleep, () => clock),
    fetch: async () => {
      throw new Error("nothing is requested");
    },
    orderPageIncome: () => incomeItemsIn(doc),
    orderPageItems: () => pageItemsIn(doc),
  };
}
const job = { id: "order_income" as const, orderIds: ["5001"], orderSns: ["261123INCOME01"], incomeFor: [true] };

describe("C-A10: the order page's income never trips drift", () => {
  it("pageIncomeFinal: the 'Doanh Thu Đơn Hàng' row is the final amount", () => {
    expect(pageIncomeFinal([{ name: "Phí cố định" }, { name: "Doanh Thu Đơn Hàng" }])).toBe(true);
    expect(pageIncomeFinal([{ name: "Phí cố định" }])).toBe(false);
  });

  it("waits for the final row drawn after the lines, then posts one income row (no drift)", async () => {
    document.body.innerHTML = LINE + FEES + "</div>";
    let drawn = false;
    const env = envFor(document, (clock) => {
      if (!drawn && clock - NOW >= 3_000) {
        drawn = true;
        document.querySelector(".income-container")!.insertAdjacentHTML("beforeend", FINAL);
      }
    });
    const outcome = await runReaderJob(job, env);
    expect(outcome.status).toBe("done");
    const [income] = mapReaderJob(job, outcome.responses, NOW);
    expect(income).toMatchObject({ dataset: "order_income", drift: null });
    expect(income!.rows).toHaveLength(1);
    expect(income!.rows[0]).toMatchObject({ payout: 65_735, fee_fixed: 16_000, fee_service: 8_500 });
  });

  it("a page that never shows the final row posts nothing for the income, says so, and is not drift", async () => {
    document.body.innerHTML = LINE + FEES + "</div>";
    const outcome = await runReaderJob(job, envFor(document));
    expect(outcome.detail).toBe(INCOME_NOT_SHOWN);
    expect(outcome.responses.filter((r) => r.endpoint === "order_income_components")).toEqual([]);
    const [income] = mapReaderJob(job, outcome.responses, NOW);
    expect(income!.drift).toBeNull();
  });

  it("mapOrderIncome: a page answer without a final amount is skipped; the income call's own answer without one is still drift", () => {
    const page: ReaderResponse = { endpoint: "order_income_components", url: "u", status: 200, body: { code: 0, data: { items: [{ name: "Phí cố định", amount: -16000 }] } }, capturedAt: NOW, source: "page", orderId: "5001" };
    expect(mapOrderIncome([page], NOW).drift).toBeNull();
    const call: ReaderResponse = { ...page, source: "replay" };
    expect(mapOrderIncome([call], NOW).drift).toEqual({ unexpected: [], missing: ["components.final_amount"] });
  });
});
