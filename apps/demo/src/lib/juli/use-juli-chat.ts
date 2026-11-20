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

export type ChatMessageStatus = "running" | "done" | "stopped" | "failed" | "saved" | "refused";

/** Why an ask was refused: no "Thử lại" for these (repeating cannot help). */
export type AskRefusal = "busy" | "invalid" | "read_only";

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
  readonly refusal?: AskRefusal;
}

export type CardPhase = "sending" | "sent" | "dismissed" | "failed" | "forbidden" | "refused";
export interface CardState {
  readonly phase: CardPhase;
  readonly code?: string;
  readonly versionLabel?: string;
}

export interface JuliChatOptions {
  readonly client: JuliClient;
  /** Skips loading the template list (tests and fixed lists). */
  readonly templates?: readonly JuliTemplate[];
  /** The shop's platform: history is listed for it (`GET /conversations?platform=`). */
  readonly platform?: "shopee" | "tiktok";
}

export interface JuliChat {
  readonly messages: readonly ChatMessage[];
  readonly templates: readonly JuliTemplate[];
  readonly running: boolean;
  /** 429 (ask or stream): asking is limited. */
  readonly limited: boolean;
  /** When asking is possible again (ISO timestamp); null = the server did not say. */
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

function fromStored(m: JuliStoredMessage, templates: readonly JuliTemplate[]): ChatMessage {
  const label = m.template ? templates.find((t) => t.key === m.template)?.label_vi : undefined;
  return {
    id: m.id,
    question: label ?? m.question,
    events: m.events,
    status: "saved",
    reconnecting: false,
    createdAt: m.created_at,
    dataUntilVi: m.data_until_vi && !m.data_until_vi.startsWith("Số liệu") ? `Số liệu đến ${m.data_until_vi}` : m.data_until_vi,
    sentCardCode: m.cards?.find((c) => c.status === "sent")?.sent_card_code ?? undefined,
  };
}

export function useJuliChat({ client, templates: fixedTemplates, platform }: JuliChatOptions): JuliChat {
  const [messages, setMessages] = useState<readonly ChatMessage[]>([]);
  const [templates, setTemplates] = useState<readonly JuliTemplate[]>(fixedTemplates ?? []);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [limited, setLimited] = useState(false);
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
      setHistory(await client.conversations(platform));
    } catch {
      /* history stays as it was; the tab still works */
    }
  }, [client, platform]);

  useEffect(() => {
    let alive = true;
    if (!fixedTemplates) {
      client
        .templates()
        .then((res) => {
          if (!alive) return;
          setTemplates(res.templates);
          if (res.shop_state.read_only) setReadOnlyDetected(true);
        })
        .catch(() => undefined);
    }
    client
      .conversations(platform)
      .then((list) => alive && setHistory(list))
      .catch(() => undefined);
    return () => {
      alive = false;
      streamRef.current?.abort();
    };
  }, [client, fixedTemplates, platform]);

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
        const status = error instanceof JuliApiError ? error.status : 0;
        if (status === 429) {
          setLimited(true);
          setLimitRetryAt((error as JuliApiError).retryAt ?? null);
          setMessages((prev) => prev.filter((m) => m.id !== tempId));
          return;
        }
        const refusal: AskRefusal | undefined = status === 409 ? "busy" : status === 422 ? "invalid" : status === 403 ? "read_only" : undefined;
        if (status === 403) setReadOnlyDetected(true);
        setMessages((prev) =>
          prev.map((m) => (m.id === tempId ? { ...m, status: refusal ? ("refused" as const) : ("failed" as const), refusal } : m)),
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
        onClose: (reason, info) => {
          if (reason === "limited") {
            // The stream's 429 is a limit, not a drop: show the limit message, never retry it.
            setLimited(true);
            setLimitRetryAt(info?.retryAt ?? null);
            if (runningIdRef.current === id) runningIdRef.current = null;
            setMessages((prev) => prev.filter((m) => m.id !== id));
          } else if (reason === "failed") finish("failed");
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
      setMessages(conversation.messages.map((m) => fromStored(m, templates)));
      setCardStates((prev) => {
        const next = { ...prev };
        for (const m of conversation.messages) {
          for (const c of m.cards ?? []) {
            if (c.status === "sent" && c.sent_card_code) {
              next[c.draft_ref] = { phase: "sent", code: c.sent_card_code, versionLabel: c.version_label ?? undefined };
            } else if (c.status === "dismissed") next[c.draft_ref] = { phase: "dismissed" };
          }
        }
        return next;
      });
    },
    [client, templates],
  );

  const sendCard = useCallback(
    async (draftRef: string, versionLabel: string) => {
      setCardStates((prev) => ({ ...prev, [draftRef]: { phase: "sending" } }));
      try {
        const { card_code } = await client.sendCard(draftRef, versionLabel);
        setCardStates((prev) => ({
          ...prev,
          [draftRef]: card_code ? { phase: "sent", code: card_code, versionLabel } : { phase: "failed" },
        }));
      } catch (error) {
        const forbidden = error instanceof JuliApiError && error.status === 403;
        const refused = error instanceof JuliApiError && error.code === "juli_card_refused";
        if (forbidden) setReadOnlyDetected(true);
        setCardStates((prev) => ({ ...prev, [draftRef]: { phase: forbidden ? "forbidden" : refused ? "refused" : "failed" } }));
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
    limited,
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
