/**
 * AC1 — Login screen with Vietnamese phone-number OTP via Supabase Auth
 * Tests the two-step OTP flow: phone entry → OTP verification
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginForm } from "@/components/LoginForm";
import { AuthProvider } from "@/lib/auth-context";
import { ModeProvider } from "@/lib/mode-context";
import { api } from "@/lib/api-client";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => "/login",
}));

jest.mock("@/lib/api-client", () => ({
  api: {
    auth: {
      sendOtp: jest.fn(),
      verifyOtp: jest.fn(),
    },
    shops: { list: jest.fn(), me: jest.fn() },
    orders: { list: jest.fn(), confirmShipment: jest.fn() },
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

const mockSendOtp = api.auth.sendOtp as jest.MockedFunction<typeof api.auth.sendOtp>;
const mockVerifyOtp = api.auth.verifyOtp as jest.MockedFunction<typeof api.auth.verifyOtp>;

function renderLogin() {
  return render(
    <AuthProvider>
      <ModeProvider>
        <LoginForm />
      </ModeProvider>
    </AuthProvider>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
});

describe("AC1: Login OTP flow", () => {
  it("renders phone input with Vietnamese label", () => {
    renderLogin();
    expect(screen.getByLabelText("Số điện thoại")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("+84 xxx xxx xxx")).toBeInTheDocument();
  });

  it("sends OTP when phone is submitted and transitions to OTP step", async () => {
    mockSendOtp.mockResolvedValue({ message: "sent" });
    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText("Số điện thoại"), "+84912345678");
    await user.click(screen.getByRole("button", { name: "Nhận mã OTP" }));

    await waitFor(() => {
      expect(mockSendOtp).toHaveBeenCalledWith("+84912345678");
    });

    expect(screen.getByLabelText("Nhập mã OTP")).toBeInTheDocument();
  });

  it("shows error when OTP send fails", async () => {
    mockSendOtp.mockRejectedValue(new Error("network error"));
    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText("Số điện thoại"), "+84912345678");
    await user.click(screen.getByRole("button", { name: "Nhận mã OTP" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Không thể gửi mã OTP"
      );
    });
  });

  it("verifies OTP and stores session", async () => {
    mockSendOtp.mockResolvedValue({ message: "sent" });
    mockVerifyOtp.mockResolvedValue({
      access_token: "jwt-token-123",
      user: { id: "user-1", phone: "+84912345678" },
    });

    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText("Số điện thoại"), "+84912345678");
    await user.click(screen.getByRole("button", { name: "Nhận mã OTP" }));

    await waitFor(() => {
      expect(screen.getByLabelText("Nhập mã OTP")).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText("Nhập mã OTP"), "123456");
    await user.click(screen.getByRole("button", { name: "Xác nhận" }));

    await waitFor(() => {
      expect(mockVerifyOtp).toHaveBeenCalledWith("+84912345678", "123456");
      expect(localStorage.getItem("access_token")).toBe("jwt-token-123");
    });
  });

  it("shows error on invalid OTP", async () => {
    mockSendOtp.mockResolvedValue({ message: "sent" });
    mockVerifyOtp.mockRejectedValue(new Error("invalid"));

    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText("Số điện thoại"), "+84912345678");
    await user.click(screen.getByRole("button", { name: "Nhận mã OTP" }));

    await waitFor(() => {
      expect(screen.getByLabelText("Nhập mã OTP")).toBeInTheDocument();
    });

    await user.type(screen.getByLabelText("Nhập mã OTP"), "000000");
    await user.click(screen.getByRole("button", { name: "Xác nhận" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Mã OTP không đúng"
      );
    });
  });

  it("allows returning to phone step", async () => {
    mockSendOtp.mockResolvedValue({ message: "sent" });
    const user = userEvent.setup();
    renderLogin();

    await user.type(screen.getByLabelText("Số điện thoại"), "+84912345678");
    await user.click(screen.getByRole("button", { name: "Nhận mã OTP" }));

    await waitFor(() => {
      expect(screen.getByLabelText("Nhập mã OTP")).toBeInTheDocument();
    });

    await user.click(screen.getByText("← Đổi số điện thoại"));

    expect(screen.getByLabelText("Số điện thoại")).toBeInTheDocument();
  });
});
