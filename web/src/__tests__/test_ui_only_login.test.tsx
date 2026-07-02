/**
 * Demo login — one-click reviewer entry without backend auth.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginForm } from "@/components/LoginForm";
import { AuthProvider } from "@/lib/auth-context";
import { ModeProvider } from "@/lib/mode-context";

jest.mock("@/lib/ui-only", () => ({
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

beforeEach(() => {
  localStorage.clear();
  document.documentElement.className = "";
});

describe("Demo login", () => {
  it("enters the app with one click", async () => {
    const user = userEvent.setup();
    render(
      <AuthProvider>
        <ModeProvider>
          <LoginForm />
        </ModeProvider>
      </AuthProvider>
    );

    expect(screen.getByText(/không cần mã xác thực/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tiếp tục vào ứng dụng" }));

    await waitFor(() => {
      expect(localStorage.getItem("access_token")).toBe("ui-only-demo-token");
      expect(mockReplace).toHaveBeenCalledWith("/mode-select");
    });
  });
});
