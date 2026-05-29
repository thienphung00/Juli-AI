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

  it("OTP button has adequate touch target (py-3 = 12px padding)", () => {
    render(
      <AuthProvider>
        <ModeProvider>
          <LoginForm />
        </ModeProvider>
      </AuthProvider>
    );

    const button = screen.getByRole("button", { name: "Nhận mã OTP" });
    expect(button.className).toContain("py-3");
    expect(button.className).toContain("w-full");
  });

  it("phone input has large text (text-lg) for easy reading", () => {
    render(
      <AuthProvider>
        <ModeProvider>
          <LoginForm />
        </ModeProvider>
      </AuthProvider>
    );

    const input = screen.getByLabelText("Số điện thoại");
    expect(input.className).toContain("text-lg");
  });

  it("phone input uses numeric keyboard on mobile", () => {
    render(
      <AuthProvider>
        <ModeProvider>
          <LoginForm />
        </ModeProvider>
      </AuthProvider>
    );

    const input = screen.getByLabelText("Số điện thoại");
    expect(input).toHaveAttribute("inputMode", "numeric");
    expect(input).toHaveAttribute("type", "tel");
  });
});
