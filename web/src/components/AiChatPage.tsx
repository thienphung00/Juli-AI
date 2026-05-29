"use client";

import { useCallback, useEffect, useState } from "react";
import { AuthenticatedShell } from "./AuthenticatedShell";
import { ChatInput } from "./ai-chat/ChatInput";
import { ChatMessageList } from "./ai-chat/ChatMessageList";
import { SuggestedPrompts } from "./ai-chat/SuggestedPrompts";
import { useWorkspaceMode } from "@/lib/mode-context";
import type { ChatMessage } from "@/lib/mock-data/ai-chat";
import {
  createUserMessage,
  getChatBootstrap,
  sendMockMessage,
} from "@/lib/services/ai-chat";
import { isUiOnly } from "@/lib/ui-only";

export function AiChatPage({ uiOnly = isUiOnly }: { uiOnly?: boolean }) {
  const { mode } = useWorkspaceMode();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [suggestedPrompts, setSuggestedPrompts] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!mode) return;

    const workspaceMode = mode;
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const bootstrap = await getChatBootstrap(workspaceMode);
        if (cancelled) return;

        const welcomeMessage: ChatMessage = {
          id: "welcome",
          role: "assistant",
          content: bootstrap.welcome,
          timestamp: new Date().toISOString(),
        };

        setSuggestedPrompts(bootstrap.suggestedPrompts);
        setMessages([welcomeMessage, ...bootstrap.seedMessages]);
      } catch (error) {
        console.error("ai_chat_bootstrap_failed", { error });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [mode]);

  const handleSend = useCallback(
    async (text: string) => {
      if (!mode || sending) return;

      const userMessage = createUserMessage(text);
      setMessages((prev) => [...prev, userMessage]);
      setSending(true);

      try {
        const reply = await sendMockMessage(mode, text);
        setMessages((prev) => [...prev, reply]);
      } catch (error) {
        console.error("ai_chat_send_failed", { error });
      } finally {
        setSending(false);
      }
    },
    [mode, sending]
  );

  if (!mode) {
    return (
      <AuthenticatedShell title="Juli">
        <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
          Đang tải chế độ làm việc...
        </p>
      </AuthenticatedShell>
    );
  }

  return (
    <AuthenticatedShell title="Juli" subtitle={uiOnly ? "Demo UI" : undefined}>
      <div className="flex min-h-[calc(100vh-12rem)] flex-col gap-4" data-testid="ai-chat-page">
        {loading ? (
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
            Đang tải...
          </p>
        ) : (
          <>
            <ChatMessageList messages={messages} />
            <SuggestedPrompts
              prompts={suggestedPrompts}
              onSelect={handleSend}
              disabled={sending}
            />
            <ChatInput onSend={handleSend} disabled={sending} />
          </>
        )}
      </div>
    </AuthenticatedShell>
  );
}
