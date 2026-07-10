/**
 * Issue #199 — Juli Chat UI with decision context (URL param + pipeline mock)
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AiChatPage } from "@/components/AiChatPage";
import { DemoPersonaProvider } from "@/lib/demo-persona-context";
import { isWorkflowSpecificPrompt } from "@/lib/decisions/chat-context";
import { ModeProvider } from "@/lib/mode-context";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/workspace-mode";

jest.mock("@/lib/ui-only", () => ({
  isUiOnly: true,
  UI_ONLY_DEMO_USER: { id: "demo-user", phone: "+84900000000" },
  UI_ONLY_DEMO_TOKEN: "ui-only-demo-token",
  UI_ONLY_DEMO_SHOP: { id: "demo-shop", name: "Cửa hàng demo", tiktok_shop_id: "demo" },
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

const mockSearchParams = new URLSearchParams();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  usePathname: () => "/ai-chat",
  useSearchParams: () => mockSearchParams,
}));

function renderChat() {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  document.documentElement.classList.remove("dark");

  return render(
    <ModeProvider>
      <DemoPersonaProvider>
        <AiChatPage uiOnly />
      </DemoPersonaProvider>
    </ModeProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  document.documentElement.className = "";
  for (const key of [...mockSearchParams.keys()]) {
    mockSearchParams.delete(key);
  }
});

describe("Issue #199: Juli Chat decision context UI", () => {
  it("renders workflow-specific prompt chips when ?decision= is set", async () => {
    const pipeline = runOperationsPipeline("new");
    const decisionId = pipeline.workflowRecommendations.recommended_workflows[0]!.workflow_id;
    mockSearchParams.set("decision", decisionId);

    renderChat();

    await waitFor(() => {
      expect(screen.getByTestId("suggested-prompts")).toBeInTheDocument();
    });

    expect(screen.getByText("Giải thích đề xuất này")).toBeInTheDocument();
    const chips = screen.getAllByTestId("suggested-prompt-chip");
    expect(
      chips.some((chip) => isWorkflowSpecificPrompt(chip.textContent ?? "", decisionId)),
    ).toBe(true);
    expect(screen.queryByText("Creator nào nên đẩy tối nay?")).not.toBeInTheDocument();

    expect(screen.getByTestId("ai-chat-page")).toHaveAttribute(
      "data-decision-context",
      decisionId,
    );
  });

  it("uses top-recommendation prompts instead of generic defaults without ?decision=", async () => {
    renderChat();

    await waitFor(() => {
      expect(screen.getByTestId("suggested-prompts")).toBeInTheDocument();
    });

    const pipeline = runOperationsPipeline("new");
    const top = pipeline.workflowRecommendations.recommended_workflows[0]!;

    expect(
      screen.getByText(`Giải thích đề xuất "${top.workflow_name}"`),
    ).toBeInTheDocument();
    expect(screen.queryByText("Creator nào nên đẩy tối nay?")).not.toBeInTheDocument();
  });

  it("mock reply references decision-specific content when context present", async () => {
    const user = userEvent.setup();
    const pipeline = runOperationsPipeline("new");
    const decision = pipeline.workflowRecommendations.recommended_workflows[0]!;
    mockSearchParams.set("decision", decision.workflow_id);

    renderChat();

    await waitFor(() => {
      expect(screen.getByText("Giải thích đề xuất này")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Giải thích đề xuất này"));

    await waitFor(() => {
      const assistantMessages = screen.getAllByTestId("chat-message-assistant");
      expect(assistantMessages.length).toBeGreaterThanOrEqual(2);
      expect(assistantMessages[assistantMessages.length - 1]?.textContent).toMatch(
        /được đưa ra vì/i,
      );
    });
  });
});
