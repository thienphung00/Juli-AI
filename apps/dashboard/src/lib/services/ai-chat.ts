import type { DecisionChatContext } from "@/lib/decisions/chat-context";
import {
  buildContextualSuggestedPrompts,
  buildDecisionAwareMockReply,
  buildDecisionAwareWelcome,
  buildDefaultDecisionPrompts,
  buildTopDecisionWelcome,
} from "@/lib/decisions/chat-context";
import {
  buildMockAssistantReply,
  getMockSeedMessages,
  getMockSuggestedPrompts,
  getMockWelcome,
  nextMessageId,
  type ChatMessage,
} from "@/lib/mock-data/ai-chat";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";
import { isUiOnly } from "@/lib/ui-only";
import type { WorkspaceMode } from "@/lib/workspace-mode";

export type { ChatMessage, ChatActionLink } from "@/lib/mock-data/ai-chat";

export interface ChatBootstrapOptions {
  decisionContext?: DecisionChatContext;
  topRecommendation?: WorkflowRecommendation;
}

export interface ChatBootstrap {
  welcome: string;
  suggestedPrompts: string[];
  seedMessages: ChatMessage[];
}

const MOCK_REPLY_DELAY_MS = process.env.NODE_ENV === "test" ? 0 : 400;

function resolveSellerBootstrap(
  options?: ChatBootstrapOptions,
): Pick<ChatBootstrap, "welcome" | "suggestedPrompts"> {
  if (options?.decisionContext) {
    return {
      welcome: buildDecisionAwareWelcome(options.decisionContext),
      suggestedPrompts: buildContextualSuggestedPrompts(options.decisionContext),
    };
  }

  if (options?.topRecommendation) {
    return {
      welcome: buildTopDecisionWelcome(options.topRecommendation),
      suggestedPrompts: buildDefaultDecisionPrompts(options.topRecommendation),
    };
  }

  return {
    welcome: getMockWelcome("seller"),
    suggestedPrompts: getMockSuggestedPrompts("seller"),
  };
}

export async function getChatBootstrap(
  mode: WorkspaceMode,
  options?: ChatBootstrapOptions,
): Promise<ChatBootstrap> {
  const sellerDecisionBootstrap =
    mode === "seller" ? resolveSellerBootstrap(options) : null;

  if (!isUiOnly) {
    // v1.5: wire to POST /v1/ai/chat bootstrap endpoint
    return {
      welcome: sellerDecisionBootstrap?.welcome ?? getMockWelcome(mode),
      suggestedPrompts:
        sellerDecisionBootstrap?.suggestedPrompts ?? getMockSuggestedPrompts(mode),
      seedMessages: [],
    };
  }

  return {
    welcome: sellerDecisionBootstrap?.welcome ?? getMockWelcome(mode),
    suggestedPrompts:
      sellerDecisionBootstrap?.suggestedPrompts ?? getMockSuggestedPrompts(mode),
    seedMessages: mode === "seller" && options?.decisionContext ? [] : getMockSeedMessages(),
  };
}

export async function sendMockMessage(
  mode: WorkspaceMode,
  text: string,
  options?: ChatBootstrapOptions,
): Promise<ChatMessage> {
  const trimmed = text.trim();
  if (!trimmed) {
    throw new Error("empty_message");
  }

  if (!isUiOnly) {
    // v1.5: POST /v1/ai/chat — never call api-client in UI-only MVP
    throw new Error("live_chat_not_available");
  }

  if (MOCK_REPLY_DELAY_MS > 0) {
    await new Promise((resolve) => setTimeout(resolve, MOCK_REPLY_DELAY_MS));
  }

  if (mode === "seller" && options?.decisionContext) {
    return {
      id: nextMessageId("assistant"),
      role: "assistant",
      content: buildDecisionAwareMockReply(options.decisionContext, trimmed),
      timestamp: new Date().toISOString(),
      data_sources: ["src/lib/decisions", "src/lib/operations/health-check"],
    };
  }

  return buildMockAssistantReply(mode, trimmed);
}

export function createUserMessage(text: string): ChatMessage {
  return {
    id: nextMessageId("user"),
    role: "user",
    content: text.trim(),
    timestamp: new Date().toISOString(),
  };
}
