import {
  buildMockAssistantReply,
  getMockSeedMessages,
  getMockSuggestedPrompts,
  getMockWelcome,
  nextMessageId,
  type ChatMessage,
} from "@/lib/mock-data/ai-chat";
import { isUiOnly } from "@/lib/ui-only";
import type { WorkspaceMode } from "@/lib/workspace-mode";

export type { ChatMessage, ChatActionLink } from "@/lib/mock-data/ai-chat";

export interface ChatBootstrap {
  welcome: string;
  suggestedPrompts: string[];
  seedMessages: ChatMessage[];
}

const MOCK_REPLY_DELAY_MS = process.env.NODE_ENV === "test" ? 0 : 400;

export async function getChatBootstrap(mode: WorkspaceMode): Promise<ChatBootstrap> {
  if (!isUiOnly) {
    // v1.5: wire to POST /v1/ai/chat bootstrap endpoint
    return {
      welcome: getMockWelcome(mode),
      suggestedPrompts: getMockSuggestedPrompts(mode),
      seedMessages: [],
    };
  }

  return {
    welcome: getMockWelcome(mode),
    suggestedPrompts: getMockSuggestedPrompts(mode),
    seedMessages: getMockSeedMessages(),
  };
}

export async function sendMockMessage(
  mode: WorkspaceMode,
  text: string
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
