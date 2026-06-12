/**
 * UI-only mode: OTP flow works without backend.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginForm } from "@/components/LoginForm";
import { AuthProvider } from "@/lib/auth-context";
import { ModeProvider } from "@/lib/mode-context";

jest.mock("@/lib/ui-only", () => ({
  isUiOnly: true,
  UI_ONLY_DEMO_USER: {
    id: "00000000-0000-4000-8000-000000000001",
    phone: "+84900000000",
  },
  UI_ONLY_DEMO_TOKEN: "ui-only-demo-token",
  UI_ONLY_DEMO_SHOP: {
    id: "00000000-0000-4000-8000-000000000002",
    name: "Cửa hàng demo",
    tiktok_shop_id: "demo",
  },
}));

const mockReplace = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: jest.fn() }),
  usePathname: () => "/login",
}));

jest.mock("@/lib/api-client", () => ({
  api: {
    auth: {
      sendOtp: jest.fn().mockRejectedValue(new Error("should not call API")),
      verifyOtp: jest.fn().mockRejectedValue(new Error("should not call API")),
    },
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
});

describe("UI-only login", () => {
  it("accepts any phone and 6-digit OTP without API", async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <ModeProvider>
          <LoginForm />
        </ModeProvider>
      </AuthProvider>
    );

    await user.type(screen.getByLabelText("Số điện thoại"), "+84901234567");
    await user.click(screen.getByRole("button", { name: "Nhận mã OTP" }));

    await waitFor(() => {
      expect(screen.getByRole("group", { name: "Nhập mã OTP" })).toBeInTheDocument();
    });

    const otpInputs = screen.getAllByRole("textbox", { name: /Chữ số OTP/i });
    for (let i = 0; i < 6; i++) {
      await user.type(otpInputs[i]!, String(i + 1));
    }
    await user.click(screen.getByRole("button", { name: "Xác nhận" }));

    await waitFor(() => {
      expect(localStorage.getItem("access_token")).toBe("ui-only-demo-token");
      expect(mockReplace).toHaveBeenCalledWith("/mode-select");
    });
  });
});
