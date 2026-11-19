"use client";

/**
 * State of the Juli tab: the open conversation, the running answer and its stream, the card
 * states, history (shared per shop). One question at a time (U3d): `running` blocks `send`.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  JuliAgentEvent,
  JuliAskRequest,
  JuliConversationSummary,
  JuliStoredMessage,
  JuliTemplate,
} from "@juli/contracts";

import { JuliApiError, type JuliClient, type JuliStreamHandle } from "./client";

export type ChatMessageStatus = "running" | "done" | "stopped" | "failed" | "saved";

export interface ChatMessage {
  readonly id: string;
  readonly question: string;
  readonly events: readonly JuliAgentEvent[];
  readonly status: ChatMessageStatus;
  /** The stream dropped and is being re-established. */
  readonly reconnecting: boolean;
  readonly createdAt?: string;
  /** Saved answers: "Số liệu đến dd/mm". */
  readonly dataUntilVi?: string;
  /** Saved answers: the JC code of the card this answer sent. */
  readonly sentCardCode?: string;
  /** The request that produced it, so "Thử lại" can send it again. */
  readonly request?: JuliAskRequest;
}

export type CardPhase = "sending" | "sent" | "dismissed" | "failed" | "forbidden";
export interface CardState {
  readonly phase: CardPhase;
  readonly code?: string;
}

export interface JuliChatOptions {
  readonly client: JuliClient;
  /** Skips loading the template list (tests and fixed lists). */
  readonly templates?: readonly JuliTemplate[];
}

export interface JuliChat {
  readonly messages: readonly ChatMessage[];
  readonly templates: readonly JuliTemplate[];
  readonly running: boolean;
  /** 429: when asking is possible again (ISO timestamp), else null. */
  readonly limitRetryAt: string | null;
  /** A send was refused as read-only (403). */
  readonly readOnlyDetected: boolean;
  readonly cardStates: Readonly<Record<string, CardState>>;
  readonly history: readonly JuliConversationSummary[];
  readonly activeConversationId: string | null;
  ask: (request: Omit<JuliAskRequest, "conversation_id">, question: string) => Promise<void>;
  stop: () => void;
  retry: () => void;
  askAgain: (messageId: string) => void;
  newConversation: () => void;
  openConversation: (id: string) => Promise<void>;
  refreshHistory: () => Promise<void>;
  sendCard: (draftRef: string, versionLabel: string) => Promise<void>;
  dismissCard: (draftRef: string) => Promise<void>;
}

function fromStored(m: JuliStoredMessage): ChatMessage {
  return {
    id: m.id,
    question: m.question,
    events: m.events,
    status: "saved",
    reconnecting: false,
    createdAt: m.created_at,
    dataUntilVi: m.data_until_vi,
    sentCardCode: m.sent_card_code,
  };
}

export function useJuliChat({ client, templates: fixedTemplates }: JuliChatOptions): JuliChat {
  const [messages, setMessages] = useState<readonly ChatMessage[]>([]);
  const [templates, setTemplates] = useState<readonly JuliTemplate[]>(fixedTemplates ?? []);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [limitRetryAt, setLimitRetryAt] = useState<string | null>(null);
  const [readOnlyDetected, setReadOnlyDetected] = useState(false);
  const [cardStates, setCardStates] = useState<Readonly<Record<string, CardState>>>({});
  const [history, setHistory] = useState<readonly JuliConversationSummary[]>([]);
  const streamRef = useRef<JuliStreamHandle | null>(null);
  const runningIdRef = useRef<string | null>(null);

  const patchMessage = useCallback((id: string, patch: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>)) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...(typeof patch === "function" ? patch(m) : patch) } : m)));
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      setHistory(await client.conversations());
    } catch {
      /* history stays as it was; the tab still works */
    }
  }, [client]);

  useEffect(() => {
    let alive = true;
    if (!fixedTemplates) {
      client
        .templates()
        .then((list) => alive && setTemplates(list))
        .catch(() => undefined);
    }
    client
      .conversations()
      .then((list) => alive && setHistory(list))
      .catch(() => undefined);
    return () => {
      alive = false;
      streamRef.current?.abort();
    };
  }, [client, fixedTemplates]);

  const ask = useCallback(
    async (request: Omit<JuliAskRequest, "conversation_id">, question: string) => {
      if (runningIdRef.current) return;
      const full: JuliAskRequest = { ...request, ...(conversationId ? { conversation_id: conversationId } : {}) };
      const tempId = `pending-${Date.now()}-${messages.length}`;
      runningIdRef.current = tempId;
      setMessages((prev) => [...prev, { id: tempId, question, events: [], status: "running", reconnecting: false, request: full }]);
      let response;
      try {
        response = await client.ask(full);
      } catch (error) {
        runningIdRef.current = null;
        if (error instanceof JuliApiError && error.status === 429) setLimitRetryAt(error.retryAt ?? null);
        if (error instanceof JuliApiError && error.status === 403) setReadOnlyDetected(true);
        setMessages((prev) =>
          error instanceof JuliApiError && (error.status === 429 || error.status === 403)
            ? prev.filter((m) => m.id !== tempId)
            : prev.map((m) => (m.id === tempId ? { ...m, status: "failed" as const } : m)),
        );
        return;
      }
      const id = response.message_id;
      runningIdRef.current = id;
      setConversationId(response.conversation_id);
      patchMessage(tempId, { id });
      const finish = (status: ChatMessageStatus) => {
        if (runningIdRef.current === id) runningIdRef.current = null;
        patchMessage(id, (m) => ({ status: m.status === "running" ? status : m.status, reconnecting: false }));
      };
      streamRef.current = client.stream(id, {
        onEvent: (event) => {
          patchMessage(id, (m) => ({ events: [...m.events, event] }));
          if (event.type === "done") finish("done");
          if (event.type === "error") finish("failed");
        },
        onReconnecting: (reconnecting) => patchMessage(id, { reconnecting }),
        onClose: (reason) => {
          if (reason === "failed") finish("failed");
          else if (reason === "terminal-event") finish("done");
        },
      });
      void refreshHistory();
    },
    [client, conversationId, messages.length, patchMessage, refreshHistory],
  );

  const stop = useCallback(() => {
    const id = runningIdRef.current;
    if (!id) return;
    streamRef.current?.abort();
    runningIdRef.current = null;
    patchMessage(id, { status: "stopped", reconnecting: false });
    if (!id.startsWith("pending-")) void client.cancel(id).catch(() => undefined);
  }, [client, patchMessage]);

  const retry = useCallback(() => {
    const last = messages.at(-1);
    if (!last?.request || runningIdRef.current) return;
    const { conversation_id: _ignored, ...request } = last.request;
    void _ignored;
    setMessages((prev) => prev.slice(0, -1));
    void ask(request, last.question);
  }, [ask, messages]);

  const askAgain = useCallback(
    (messageId: string) => {
      const m = messages.find((x) => x.id === messageId);
      if (m) void ask({ text: m.question }, m.question);
    },
    [ask, messages],
  );

  const newConversation = useCallback(() => {
    streamRef.current?.abort();
    runningIdRef.current = null;
    setMessages([]);
    setConversationId(null);
  }, []);

  const openConversation = useCallback(
    async (id: string) => {
      streamRef.current?.abort();
      runningIdRef.current = null;
      const conversation = await client.conversation(id);
      setConversationId(conversation.id);
      setMessages(conversation.messages.map(fromStored));
      setCardStates((prev) => {
        const next = { ...prev };
        for (const m of conversation.messages) {
          const card = m.events.find((e) => e.type === "card");
          if (card && card.type === "card" && m.sent_card_code) next[card.data.draft_ref] = { phase: "sent", code: m.sent_card_code };
        }
        return next;
      });
    },
    [client],
  );

  const sendCard = useCallback(
    async (draftRef: string, versionLabel: string) => {
      setCardStates((prev) => ({ ...prev, [draftRef]: { phase: "sending" } }));
      try {
        const { card_code } = await client.sendCard(draftRef, versionLabel);
        setCardStates((prev) => ({ ...prev, [draftRef]: { phase: "sent", code: card_code } }));
      } catch (error) {
        const forbidden = error instanceof JuliApiError && error.status === 403;
        if (forbidden) setReadOnlyDetected(true);
        setCardStates((prev) => ({ ...prev, [draftRef]: { phase: forbidden ? "forbidden" : "failed" } }));
      }
    },
    [client],
  );

  const dismissCard = useCallback(
    async (draftRef: string) => {
      setCardStates((prev) => ({ ...prev, [draftRef]: { phase: "dismissed" } }));
      try {
        await client.dismissCard(draftRef);
      } catch {
        /* nothing was written either way; the block stays dismissed */
      }
    },
    [client],
  );

  const running = messages.some((m) => m.status === "running");

  return {
    messages,
    templates,
    running,
    limitRetryAt,
    readOnlyDetected,
    cardStates,
    history,
    activeConversationId: conversationId,
    ask,
    stop,
    retry,
    askAgain,
    newConversation,
    openConversation,
    refreshHistory,
    sendCard,
    dismissCard,
  };
}
