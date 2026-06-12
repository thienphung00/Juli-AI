"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import {
  buildDecisionChatContext,
  isValidatedWorkflowId,
  takeTopDecisions,
  toDecisionsFromRecommendations,
} from "@/lib/decisions";
import {
  readActiveDecisionForChat,
  saveActiveDecisionForChat,
} from "@/lib/decisions/chat-session";
import { useDemoPersona } from "@/lib/demo-persona-context";
import { useWorkspaceMode } from "@/lib/mode-context";
import type { ChatMessage } from "@/lib/mock-data/ai-chat";
import { useOperationsPipeline } from "@/lib/operations/use-operations-pipeline";
import {
  createUserMessage,
  getChatBootstrap,
  sendMockMessage,
  type ChatBootstrapOptions,
} from "@/lib/services/ai-chat";
import { isUiOnly } from "@/lib/ui-only";

import { AuthenticatedShell } from "./AuthenticatedShell";
import { ChatInput } from "./ai-chat/ChatInput";
import { ChatMessageList } from "./ai-chat/ChatMessageList";
import { SuggestedPrompts } from "./ai-chat/SuggestedPrompts";

function ChatLoadingSkeleton() {
  return (
    <div className="space-y-4" data-testid="ai-chat-loading-skeleton" aria-busy="true">
      <div className="skeleton h-16 w-3/4 rounded-2xl" />
      <div className="skeleton ml-auto h-12 w-2/3 rounded-2xl" />
      <div className="skeleton h-20 w-4/5 rounded-2xl" />
    </div>
  );
}

function resolveChatBootstrapOptions(
  mode: "seller" | "affiliate",
  decisionParam: string | null,
  personaReady: boolean,
  pipeline: ReturnType<typeof useOperationsPipeline>,
): ChatBootstrapOptions | undefined {
  if (mode !== "seller" || !personaReady) {
    return undefined;
  }

  const recommendations = pipeline.workflowRecommendations.recommended_workflows;
  if (recommendations.length === 0) {
    return undefined;
  }

  const workflowId =
    (decisionParam && isValidatedWorkflowId(decisionParam) ? decisionParam : null) ??
    readActiveDecisionForChat();

  if (workflowId) {
    const recommendation = recommendations.find((item) => item.workflow_id === workflowId);
    if (recommendation) {
      return {
        decisionContext: buildDecisionChatContext(recommendation, pipeline.healthResults),
      };
    }
  }

  const topDecision = takeTopDecisions(toDecisionsFromRecommendations(recommendations), 1)[0];
  if (!topDecision) {
    return undefined;
  }

  const topRecommendation = recommendations.find(
    (item) => item.workflow_id === topDecision.workflow_id,
  );
  if (!topRecommendation) {
    return undefined;
  }

  return { topRecommendation };
}

export function AiChatPage({ uiOnly = isUiOnly }: { uiOnly?: boolean }) {
  const { mode } = useWorkspaceMode();
  const searchParams = useSearchParams();
  const decisionParam = searchParams.get("decision");
  const { personaId, isReady: personaReady } = useDemoPersona();
  const pipeline = useOperationsPipeline({ personaId });

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [suggestedPrompts, setSuggestedPrompts] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);

  const chatOptions = useMemo(
    () =>
      mode
        ? resolveChatBootstrapOptions(mode, decisionParam, personaReady, pipeline)
        : undefined,
    [decisionParam, mode, personaReady, pipeline],
  );

  useEffect(() => {
    if (decisionParam && isValidatedWorkflowId(decisionParam)) {
      saveActiveDecisionForChat(decisionParam);
    }
  }, [decisionParam]);

  useEffect(() => {
    if (!mode) return;

    const workspaceMode = mode;
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const bootstrap = await getChatBootstrap(workspaceMode, chatOptions);
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

    if (workspaceMode === "seller" && !personaReady) {
      return;
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [chatOptions, mode, personaReady]);

  const handleSend = useCallback(
    async (text: string) => {
      if (!mode || sending) return;

      const userMessage = createUserMessage(text);
      setMessages((prev) => [...prev, userMessage]);
      setSending(true);

      try {
        const reply = await sendMockMessage(mode, text, chatOptions);
        setMessages((prev) => [...prev, reply]);
      } catch (error) {
        console.error("ai_chat_send_failed", { error });
      } finally {
        setSending(false);
      }
    },
    [chatOptions, mode, sending],
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
      <div
        className="flex min-h-[calc(100vh-12rem)] flex-col gap-4"
        data-testid="ai-chat-page"
        data-decision-context={chatOptions?.decisionContext?.workflow_id ?? ""}
      >
        {loading ? (
          <ChatLoadingSkeleton />
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
