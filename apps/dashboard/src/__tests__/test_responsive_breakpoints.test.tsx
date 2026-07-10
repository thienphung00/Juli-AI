/**
 * AC5 — Mobile-responsive layout with single-thumb operation patterns.
 * Tests that critical interactive elements meet touch-target minimums
 * and layout renders at mobile viewport.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { LoginForm } from "@/components/LoginForm";
import { AuthProvider } from "@/lib/auth-context";
import { ModeProvider } from "@/lib/mode-context";

jest.mock("@/lib/api-client", () => ({
  api: {
    auth: { sendOtp: jest.fn(), verifyOtp: jest.fn() },
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

beforeEach(() => {
  localStorage.clear();
});

describe("AC5: Mobile-responsive layout", () => {
  it("login form renders within a max-w-sm container for mobile", () => {
    const { container } = render(
      <AuthProvider>
        <ModeProvider>
          <LoginForm />
        </ModeProvider>
      </AuthProvider>
    );

    const wrapper = container.querySelector(".max-w-sm");
    expect(wrapper).toBeInTheDocument();
  });

  it("demo continue button has adequate touch target (py-3 = 12px padding)", () => {
    render(
      <AuthProvider>
        <ModeProvider>
          <LoginForm />
        </ModeProvider>
      </AuthProvider>
    );

    const button = screen.getByRole("button", { name: "Tiếp tục vào ứng dụng" });
    expect(button.className).toContain("py-3");
    expect(button.className).toContain("w-full");
  });

  it("demo login copy is readable on mobile", () => {
    render(
      <AuthProvider>
        <ModeProvider>
          <LoginForm />
        </ModeProvider>
      </AuthProvider>
    );

    expect(screen.getByText(/không cần mã xác thực/i)).toBeInTheDocument();
    expect(screen.getByText(/dữ liệu demo/i)).toBeInTheDocument();
  });
});
