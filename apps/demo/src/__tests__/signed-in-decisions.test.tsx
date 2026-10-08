import {
  GOLDEN_DEMO_DECISION_EXECUTABLE,
  GOLDEN_DEMO_DECISION_NON_EXECUTABLE,
  type DemoDecisionItem,
} from "@juli/contracts";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoStateProvider } from "../components/demo-state";
import { SignedInDecisions } from "../components/signed-in-decisions";
import {
  DemoDecisionApproveError,
  DemoRecommendationsFetchError,
  type approveDemoDecision,
  type fetchRecommendations,
} from "../lib/recommendations-api-client";
import adr106Item from "../lib/__tests__/fixtures/adr106-decision-item.json";
import { storeActiveShop } from "../lib/shop-session";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => "/decisions"),
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push,
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
}));

const TOKEN = "real-bearer-token";
const SHOP = { id: "1862f13b-de2c-4fae-a4ad-70298cead913", name: "Shop Minh Anh" };
const RUN_ID = "3f65f4b2-8f2a-47f6-9c93-2a2d0a2f9b11";

function renderSignedIn({
  loadDecisions = vi.fn().mockResolvedValue([GOLDEN_DEMO_DECISION_EXECUTABLE]),
  approve = vi.fn().mockResolvedValue({ runId: RUN_ID }),
}: {
  loadDecisions?: ReturnType<typeof vi.fn>;
  approve?: ReturnType<typeof vi.fn>;
} = {}) {
  render(
    <DemoStateProvider>
      <SignedInDecisions
        approve={approve as unknown as typeof approveDemoDecision}
        loadDecisions={loadDecisions as unknown as typeof fetchRecommendations}
        token={TOKEN}
      />
    </DemoStateProvider>,
  );
  return { loadDecisions, approve };
}

describe("SignedInDecisions — the signed-in Decisions branch (#1909)", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    storeActiveShop(SHOP);
    push.mockClear();
  });

  afterEach(() => {
    window.sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("reads GET /v1/demo/decisions with the bearer token and the SELECTED shop's id, and renders the response", async () => {
    const { loadDecisions } = renderSignedIn();

    await waitFor(() => {
      expect(screen.getByText(GOLDEN_DEMO_DECISION_EXECUTABLE.title)).toBeInTheDocument();
    });

    expect(loadDecisions).toHaveBeenCalledTimes(1);
    expect(loadDecisions.mock.calls[0][0]).toMatchObject({
      token: TOKEN,
      shopId: SHOP.id,
    });
  });

  it("tells a multi-shop seller which shop they are acting as (dictionary decisions.signed_in.acting_shop)", async () => {
    renderSignedIn();

    await waitFor(() => {
      expect(screen.getByText(GOLDEN_DEMO_DECISION_EXECUTABLE.title)).toBeInTheDocument();
    });

    expect(
      screen.getByText((_, el) => el?.textContent === `Bạn đang thao tác trên: ${SHOP.name}`, {
        selector: ".demo-decisions__acting-shop",
      }),
    ).toBeInTheDocument();
  });

  it("with no stored acting shop, issues no request and renders the honest connect-shop recovery", async () => {
    window.sessionStorage.clear();
    const { loadDecisions } = renderSignedIn();

    expect(
      await screen.findByText("Bạn chưa chọn shop đang thao tác. Mở Kết nối TikTok Shop để chọn shop."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Kết nối TikTok Shop" })).toHaveAttribute(
      "href",
      "/auth/connect-shop",
    );
    expect(loadDecisions).not.toHaveBeenCalled();
  });

  it("surfaces a failed read honestly with a retry — never recommendationFixtures", async () => {
    const loadDecisions = vi
      .fn()
      .mockRejectedValueOnce(new DemoRecommendationsFetchError(503))
      .mockResolvedValueOnce([GOLDEN_DEMO_DECISION_EXECUTABLE]);
    renderSignedIn({ loadDecisions });

    expect(
      await screen.findByText("Không thể tải đề xuất cho shop của bạn. Vui lòng thử lại."),
    ).toBeInTheDocument();
    // The anonymous branch's first fixture title must NOT stand in.
    expect(screen.queryByText("Tạo sản phẩm nổi bật")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Thử lại" }));

    await waitFor(() => {
      expect(screen.getByText(GOLDEN_DEMO_DECISION_EXECUTABLE.title)).toBeInTheDocument();
    });
    expect(loadDecisions).toHaveBeenCalledTimes(2);
  });

  it("approve asks for consent, issues exactly one POST, and navigates with the run_id FROM THE RESPONSE", async () => {
    const user = userEvent.setup();
    const { approve } = renderSignedIn();

    await waitFor(() => {
      expect(screen.getByText(GOLDEN_DEMO_DECISION_EXECUTABLE.title)).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Phê duyệt" }));

    // Two-step consent (#1317's pattern): nothing was sent yet.
    expect(approve).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Phê duyệt đề xuất này?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Phê duyệt" }));

    await waitFor(() => {
      expect(push).toHaveBeenCalledWith(`/decisions/in-progress/${RUN_ID}`);
    });
    expect(approve).toHaveBeenCalledTimes(1);
    expect(approve.mock.calls[0][0]).toBe(GOLDEN_DEMO_DECISION_EXECUTABLE.id);
    expect(approve.mock.calls[0][1]).toMatchObject({ token: TOKEN, shopId: SHOP.id });
  });

  it.each([
    [401, "Phiên đăng nhập của bạn không còn hiệu lực. Vui lòng đăng nhập với Google lại, rồi phê duyệt."],
    [404, "Đề xuất này không còn tồn tại hoặc không thuộc shop bạn đang thao tác."],
    [409, "Đề xuất này đã được xử lý, hoặc sản phẩm đang có luồng khác chạy. Hãy kiểm tra tab Đang thực hiện."],
  ])("renders the distinct honest message for a %s from approve — no fixture, no navigation", async (status, message) => {
    const user = userEvent.setup();
    const approve = vi.fn().mockRejectedValue(new DemoDecisionApproveError(status as number));
    renderSignedIn({ approve });

    await waitFor(() => {
      expect(screen.getByText(GOLDEN_DEMO_DECISION_EXECUTABLE.title)).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Phê duyệt" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Phê duyệt" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message as string);
    expect(push).not.toHaveBeenCalled();
    expect(screen.queryByText("Tạo sản phẩm nổi bật")).not.toBeInTheDocument();
  });

  it("offers no approve control on a non-executable decision", async () => {
    const loadDecisions = vi
      .fn()
      .mockResolvedValue([GOLDEN_DEMO_DECISION_NON_EXECUTABLE]);
    renderSignedIn({ loadDecisions });

    await waitFor(() => {
      expect(screen.getByText(GOLDEN_DEMO_DECISION_NON_EXECUTABLE.title)).toBeInTheDocument();
    });

    expect(screen.queryByRole("button", { name: "Phê duyệt" })).not.toBeInTheDocument();
  });
});

describe("SignedInDecisions — mock recommendation card + funnel evidence (AC-7.6)", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    storeActiveShop(SHOP);
  });

  it("renders stage, lever, trigger, recoverable GMV and the funnel table from the real P7-B item", async () => {
    const item = adr106Item as unknown as DemoDecisionItem;
    renderSignedIn({ loadDecisions: vi.fn().mockResolvedValue([item]) });

    const block = await screen.findByTestId("decision-evidence");
    expect(within(block).getByText("Hiển thị → Nhấp (thẻ sản phẩm)")).toBeInTheDocument();
    expect(within(block).getByText("Viết lại tiêu đề")).toBeInTheDocument();
    expect(
      within(block).getByText(/^CTR thẻ sản phẩm ước tính thấp hơn 60 %/),
    ).toBeInTheDocument();
    expect(within(block).getByTestId("decision-recoverable-gmv")).toHaveTextContent(
      "Có thể lấy lại khoảng 1.200.000 ₫ GMV mỗi ngày (ước tính theo quy tắc, chưa phải mô hình)",
    );
    // The sentence is shown once (not again as the reasoning's expected impact).
    expect(screen.getAllByText(/Có thể lấy lại khoảng/)).toHaveLength(1);
    expect(within(block).getByRole("columnheader", { name: "30 ngày gần đây" })).toBeInTheDocument();
    expect(within(block).getByRole("columnheader", { name: "30 ngày trước" })).toBeInTheDocument();
    for (const label of [
      "Lượt hiển thị sản phẩm",
      "CTR",
      "CTOR",
      "AOV",
      "GMV trung bình mỗi ngày",
      "Đơn hàng SKU mỗi ngày",
    ]) {
      expect(within(block).getByRole("rowheader", { name: label })).toBeInTheDocument();
    }
    const ctr = within(block).getByRole("rowheader", { name: "CTR" }).closest("tr");
    expect(ctr).toHaveTextContent("2,00 %");
    expect(ctr).toHaveTextContent("Tham khảo");
    const aov = within(block).getByRole("rowheader", { name: "AOV" }).closest("tr");
    expect(aov).toHaveTextContent("200.000 ₫");
    const cart = within(block)
      .getByRole("rowheader", { name: /^Tỷ lệ thêm vào giỏ hàng/ })
      .closest("tr");
    expect(cart).toHaveTextContent("20,00 %");
    expect(cart).toHaveTextContent("chỉ tính trên 5 ngày có số liệu");
    // Codes never reach the seller.
    expect(block).not.toHaveTextContent(/add_to_cart_rate|count_per_day|shop_median/);
  });

  it("renders no evidence block for an item without the new fields, and keeps Phê duyệt / Từ chối / Mở rộng", async () => {
    const user = userEvent.setup();
    renderSignedIn();
    await screen.findByText(GOLDEN_DEMO_DECISION_EXECUTABLE.title);
    expect(screen.queryByTestId("decision-evidence")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Phê duyệt" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Từ chối" }));
    expect(screen.queryByText(GOLDEN_DEMO_DECISION_EXECUTABLE.title)).not.toBeInTheDocument();
    expect(screen.getByText(/Đã gỡ đề xuất bạn từ chối khỏi danh sách/)).toBeInTheDocument();
  });
});
