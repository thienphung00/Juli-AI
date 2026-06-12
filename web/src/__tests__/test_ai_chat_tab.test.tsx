/**
 * Issue #82 — Juli AI chat tab (mode-aware prompts + UI-only mock)
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AiChatPage } from "@/components/AiChatPage";
import { ModeProvider } from "@/lib/mode-context";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";
import * as aiChatService from "@/lib/services/ai-chat";
import { api } from "@/lib/api-client";

jest.mock("@/lib/ui-only", () => ({
  isUiOnly: true,
  UI_ONLY_DEMO_USER: { id: "demo-user", phone: "+84900000000" },
  UI_ONLY_DEMO_TOKEN: "ui-only-demo-token",
  UI_ONLY_DEMO_SHOP: { id: "demo-shop", name: "Cửa hàng demo", tiktok_shop_id: "demo" },
}));

jest.mock("@/lib/services/ai-chat", () => ({
  ...jest.requireActual("@/lib/services/ai-chat"),
  getChatBootstrap: jest.fn(),
  sendMockMessage: jest.fn(),
}));

jest.mock("@/lib/api-client", () => ({
  api: {
    auth: { sendOtp: jest.fn(), verifyOtp: jest.fn() },
    shops: { list: jest.fn() },
    orders: { list: jest.fn(), confirmShipment: jest.fn() },
    products: { list: jest.fn() },
    inventory: { list: jest.fn() },
    livestreams: { list: jest.fn() },
    creators: { list: jest.fn() },
    alerts: { history: jest.fn(), upsertConfig: jest.fn() },
    recommendations: { list: jest.fn() },
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
      this.name = "ApiError";
    }
  },
}));

jest.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
    user: { id: "user-1", phone: "+84912345678" },
    token: "jwt-token",
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => "/ai-chat",
}));

const mockGetChatBootstrap = aiChatService.getChatBootstrap as jest.MockedFunction<
  typeof aiChatService.getChatBootstrap
>;
const mockSendMockMessage = aiChatService.sendMockMessage as jest.MockedFunction<
  typeof aiChatService.sendMockMessage
>;

function renderChat(mode: "seller" | "affiliate") {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, mode);
  if (mode === "seller") {
    document.documentElement.classList.remove("dark");
  } else {
    document.documentElement.classList.add("dark");
  }

  return render(
    <ModeProvider>
      <AiChatPage uiOnly />
    </ModeProvider>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  document.documentElement.className = "";

  const actual = jest.requireActual<typeof import("@/lib/services/ai-chat")>(
    "@/lib/services/ai-chat"
  );

  mockGetChatBootstrap.mockImplementation(actual.getChatBootstrap);
  mockSendMockMessage.mockImplementation(actual.sendMockMessage);
});

describe("Juli AI chat tab (#82)", () => {
  it("renders message list, input, and send button", async () => {
    renderChat("seller");

    await waitFor(() => {
      expect(screen.getByTestId("chat-message-list")).toBeInTheDocument();
    });

    expect(screen.getByTestId("chat-input")).toBeInTheDocument();
    expect(screen.getByTestId("chat-send-button")).toBeInTheDocument();
  });

  it("shows seller suggested prompts in seller mode", async () => {
    renderChat("seller");

    await waitFor(() => {
      expect(screen.getByTestId("suggested-prompts")).toBeInTheDocument();
    });

    expect(screen.getByText("Creator nào nên đẩy tối nay?")).toBeInTheDocument();
    expect(screen.queryByText("Sản phẩm nào đang xu hướng trước khi bão hòa?")).not.toBeInTheDocument();
  });

  it("shows out-of-scope in affiliate mode instead of chat UI", async () => {
    renderChat("affiliate");

    await waitFor(() => {
      expect(screen.getByTestId("affiliate-out-of-scope")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("suggested-prompts")).not.toBeInTheDocument();
    expect(screen.queryByTestId("chat-input")).not.toBeInTheDocument();
  });

  it("appends user message and mock assistant reply when sending", async () => {
    const user = userEvent.setup();

    renderChat("seller");

    await waitFor(() => {
      expect(screen.getByTestId("chat-input")).toBeInTheDocument();
    });

    const input = screen.getByTestId("chat-input");
    await user.type(input, "Creator nào chuyển đổi tốt nhất?");
    await user.click(screen.getByTestId("chat-send-button"));

    expect(screen.getByText("Creator nào chuyển đổi tốt nhất?")).toBeInTheDocument();

    await waitFor(() => {
      expect(
        screen.getByText(/@linh.nhi.beauty đang có tỷ lệ chuyển đổi cao nhất/)
      ).toBeInTheDocument();
    });
  });

  it("uses mock service only in UI-only mode without calling API", async () => {
    renderChat("seller");

    await waitFor(() => {
      expect(screen.getByTestId("chat-message-list")).toBeInTheDocument();
    });

    expect(mockGetChatBootstrap).toHaveBeenCalledWith("seller");
    expect(api.shops.list).not.toHaveBeenCalled();
  });
});
