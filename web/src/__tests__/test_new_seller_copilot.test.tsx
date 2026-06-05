/**
 * Issue #119 — New Seller Copilot UI (mocked)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HomePage } from "@/components/HomePage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { ModeProvider } from "@/lib/mode-context";
import { clearTaskExecutorSession } from "@/lib/task-executor";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";

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
  usePathname: () => "/",
}));

function renderNewSellerHome() {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  document.documentElement.classList.add("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <HomePage uiOnly />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

const VIETNAMESE_DIACRITIC = /[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]/i;

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearTaskExecutorSession();
  document.documentElement.className = "";
});

describe("Issue #119: New Seller Copilot", () => {
  it("integration: new-seller persona renders at least 3 tasks with Vietnamese titles", async () => {
    const persona = loadPersona("new");
    const expectedTitles = persona.tasks
      .filter((task) => task.workflow === "new_seller")
      .map((task) => task.title);

    renderNewSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("new-seller-copilot-panel")).toBeInTheDocument();
    });

    const titles = screen.getAllByTestId("task-title");
    expect(titles.length).toBeGreaterThanOrEqual(3);

    const visibleTitles = titles.map((node) => node.textContent ?? "");
    for (const title of expectedTitles.slice(0, 3)) {
      expect(visibleTitles).toContain(title);
      expect(title).toMatch(VIETNAMESE_DIACRITIC);
    }
  });

  it("integration: each task shows Vietnamese justification body from fixtures", async () => {
    const persona = loadPersona("new");
    const firstTask = persona.tasks.find((task) => task.workflow === "new_seller")!;

    renderNewSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("new-seller-copilot-panel")).toBeInTheDocument();
    });

    expect(screen.getByText(firstTask.body)).toBeInTheDocument();
    expect(firstTask.body).toMatch(VIETNAMESE_DIACRITIC);
  });

  it("integration: first-sale milestone progress is visible with Vietnamese label", async () => {
    renderNewSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("first-sale-milestone")).toBeInTheDocument();
    });

    const milestone = screen.getByTestId("first-sale-milestone");
    expect(milestone).toHaveTextContent(/Tiến độ đơn hàng đầu tiên/i);
    expect(within(milestone).getByTestId("milestone-progress-bar")).toBeInTheDocument();
    expect(within(milestone).getByTestId("milestone-percent")).toBeInTheDocument();
  });

  it("integration: approve removes task from active queue", async () => {
    const user = userEvent.setup();
    renderNewSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("task-queue-list")).toBeInTheDocument();
    });

    const list = screen.getByTestId("task-queue-list");
    const initialCount = within(list).getAllByTestId("task-card").length;
    expect(initialCount).toBeGreaterThanOrEqual(3);

    await user.click(within(list).getAllByTestId("task-approve")[0]);

    await waitFor(() => {
      expect(within(list).getAllByTestId("task-card")).toHaveLength(initialCount - 1);
    });
  });

  it("renders empty state when all checklist tasks are completed in session", async () => {
    const user = userEvent.setup();
    renderNewSellerHome();

    await waitFor(() => {
      expect(screen.getByTestId("task-queue-list")).toBeInTheDocument();
    });

    const approveButtons = screen.getAllByTestId("task-approve");
    for (const button of approveButtons) {
      await user.click(button);
    }

    await waitFor(() => {
      expect(screen.getByTestId("task-queue-empty")).toBeInTheDocument();
    });

    expect(screen.getByTestId("new-seller-copilot-panel")).toBeInTheDocument();
    expect(screen.getByTestId("first-sale-milestone")).toBeInTheDocument();
  });
});
