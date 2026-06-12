/**
 * Issue #76 — Mode selection gate after OTP login
 */
import type { ReactElement } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginForm } from "@/components/LoginForm";
import { ModeSelectionPage } from "@/components/ModeSelectionPage";
import { AuthProvider } from "@/lib/auth-context";
import { ModeProvider } from "@/lib/mode-context";
import {
  WORKSPACE_MODE_STORAGE_KEY,
  readStoredWorkspaceMode,
} from "@/lib/workspace-mode";
import { api } from "@/lib/api-client";

const mockReplace = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: jest.fn() }),
  usePathname: () => "/login",
}));

jest.mock("@/lib/api-client", () => ({
  api: {
    auth: {
      sendOtp: jest.fn(),
      verifyOtp: jest.fn(),
    },
    shops: { list: jest.fn(), me: jest.fn() },
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

function renderWithProviders(ui: ReactElement) {
  return render(
    <AuthProvider>
      <ModeProvider>{ui}</ModeProvider>
    </AuthProvider>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  document.documentElement.className = "";
});

describe("Mode selection gate (#76)", () => {
  it(
    "redirects to /mode-select after OTP when no workspace mode is saved",
    async () => {
      localStorage.setItem("access_token", "jwt-token");
      localStorage.setItem(
        "user",
        JSON.stringify({ id: "user-1", phone: "+84912345678" }),
      );

      renderWithProviders(<LoginForm />);

      await waitFor(() => {
        expect(mockReplace).toHaveBeenCalledWith("/mode-select");
      });
      expect(readStoredWorkspaceMode()).toBeNull();
    },
    15_000,
  );

  it("persists seller mode, applies light theme, and routes to /", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ModeSelectionPage />);

    await user.click(screen.getByRole("button", { name: "Người bán" }));

    await waitFor(() => {
      expect(localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBe("seller");
      expect(document.documentElement.classList.contains("dark")).toBe(false);
      expect(mockReplace).toHaveBeenCalledWith("/");
    });
  });

  it("persists affiliate mode, applies dark theme, and routes to /", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ModeSelectionPage />);

    await user.click(screen.getByRole("button", { name: "Affiliate" }));

    await waitFor(() => {
      expect(localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBe("affiliate");
      expect(document.documentElement.classList.contains("dark")).toBe(true);
      expect(mockReplace).toHaveBeenCalledWith("/");
    });
  });

  it("redirects returning users with saved mode straight to /", async () => {
    localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
    document.documentElement.classList.remove("dark");

    renderWithProviders(<ModeSelectionPage />);

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/");
    });
  });
});
