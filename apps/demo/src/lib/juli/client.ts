/**
 * HTTP + SSE client of the Juli tab (`/v1/demo/juli`, shop from `X-Shop-Id`, bearer in a header).
 * The stream reuses the app's SSE framing and header helpers (`agent-event-stream.ts`) and follows
 * the same reconnect rules (Last-Event-ID, capped backoff, 401/403/404 never retry); the Juli events are
 * not run events, so the validation is `parseJuliEvent` rather than `validateAgentEvent`.
 */
import {
  isJuliTerminalEvent,
  parseJuliEvent,
  type JuliAgentEvent,
  type JuliAskRequest,
  type JuliAskResponse,
  type JuliConversation,
  type JuliConversationSummary,
  type JuliSendCardResponse,
  type JuliServerMessage,
  type JuliStoredMessage,
  type JuliTemplatesResponse,
} from "@juli/contracts";

import { buildAgentEventStreamHeaders, extractSseFrames, parseSseFrame } from "../agent-event-stream";

export const JULI_BASE = "/v1/demo/juli";

export class JuliApiError extends Error {
  readonly status: number;
  /** 429: when the limit lifts (ISO timestamp). */
  readonly retryAt?: string;
  /** The server's error code (`detail.code`), e.g. `juli_limited`, `juli_card_refused`. */
  readonly code?: string;
  constructor(status: number, retryAt?: string, code?: string) {
    super(`juli api failed with status ${status}`);
    this.name = "JuliApiError";
    this.status = status;
    this.retryAt = retryAt;
    this.code = code;
  }
}

export type JuliStreamCloseReason = "terminal-event" | "aborted" | "failed";

export interface JuliStreamHandlers {
  onEvent: (event: JuliAgentEvent) => void;
  /** true while the connection is being re-established (the seller sees "Đang kết nối lại…"). */
  onReconnecting?: (reconnecting: boolean) => void;
  onClose?: (reason: JuliStreamCloseReason) => void;
}

export interface JuliStreamHandle {
  abort: () => void;
}

export interface JuliClient {
  templates(): Promise<JuliTemplatesResponse>;
  ask(request: JuliAskRequest): Promise<JuliAskResponse>;
  stream(messageId: string, handlers: JuliStreamHandlers): JuliStreamHandle;
  cancel(messageId: string): Promise<void>;
  conversations(): Promise<readonly JuliConversationSummary[]>;
  conversation(id: string): Promise<JuliConversation>;
  sendCard(draftRef: string, versionLabel: string): Promise<JuliSendCardResponse>;
  dismissCard(draftRef: string): Promise<void>;
}

export interface JuliClientConfig {
  token: string;
  shopId: string;
  base?: string;
  fetchImpl?: typeof fetch;
  maxReconnectAttempts?: number;
  /** Delay before reconnect attempt n (1-based); tests pass 0. */
  reconnectDelayMs?: (attempt: number) => number;
}

const DEFAULT_MAX_RECONNECTS = 10;

function backoff(attempt: number): number {
  return Math.min(1000 * 2 ** (attempt - 1), 15_000);
}

/** Server rows (user + assistant, events as `{seq, type, payload}`) -> the pairs the page renders. */
export function adaptConversation(raw: { id: string; title: string; messages: readonly JuliServerMessage[] }): JuliConversation {
  const messages: JuliStoredMessage[] = [];
  let asked: JuliServerMessage | null = null;
  for (const row of raw.messages) {
    if (row.role === "user") {
      asked = row;
      continue;
    }
    const events = (row.events ?? [])
      .map((e) => parseJuliEvent(e.payload, e.type))
      .filter((e): e is JuliAgentEvent => e !== null);
    messages.push({
      id: row.id,
      question: asked?.text ?? asked?.template ?? asked?.choice?.value ?? "",
      template: asked?.template ?? undefined,
      events,
      created_at: row.created_at,
      data_until_vi: row.data_until_vi ?? undefined,
      cards: row.cards,
    });
    asked = null;
  }
  return { id: raw.id, title: raw.title, messages };
}

export function createJuliClient(config: JuliClientConfig): JuliClient {
  const base = config.base ?? JULI_BASE;
  const doFetch: typeof fetch = (...args) => (config.fetchImpl ?? fetch)(...args);

  const headers = (json = false): Headers => {
    const h = new Headers();
    h.set("Authorization", `Bearer ${config.token}`);
    h.set("X-Shop-Id", config.shopId);
    if (json) h.set("Content-Type", "application/json");
    return h;
  };

  async function call<T>(path: string, init: RequestInit = {}, json = false): Promise<T> {
    const response = await doFetch(`${base}${path}`, { ...init, headers: headers(json) });
    if (!response.ok) {
      let retryAt: string | undefined;
      let code: string | undefined;
      try {
        // FastAPI: {"detail": {"code", "message", "retry_at"?}}; `detail` can also be a plain string.
        const body = (await response.json()) as { detail?: { code?: string; retry_at?: string } | string };
        if (typeof body.detail === "object" && body.detail !== null) {
          retryAt = body.detail.retry_at;
          code = body.detail.code;
        }
      } catch {
        /* no JSON body */
      }
      throw new JuliApiError(response.status, retryAt, code);
    }
    if (response.status === 204) return undefined as T;
    const text = await response.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }

  function stream(messageId: string, handlers: JuliStreamHandlers): JuliStreamHandle {
    const controller = new AbortController();
    let lastId: number | null = null;
    let attempts = 0;
    let closed = false;
    const max = config.maxReconnectAttempts ?? DEFAULT_MAX_RECONNECTS;

    const finish = (reason: JuliStreamCloseReason) => {
      if (closed) return;
      closed = true;
      handlers.onReconnecting?.(false);
      handlers.onClose?.(reason);
    };

    const wait = (ms: number) =>
      new Promise<void>((resolve) => {
        const t = setTimeout(resolve, ms);
        controller.signal.addEventListener("abort", () => {
          clearTimeout(t);
          resolve();
        });
      });

    async function connectOnce(): Promise<"terminal" | "ended"> {
      const response = await doFetch(`${base}/messages/${encodeURIComponent(messageId)}/events`, {
        method: "GET",
        headers: buildAgentEventStreamHeaders(config.token, lastId, config.shopId),
        signal: controller.signal,
      });
      if (!response.ok) throw new JuliApiError(response.status);
      if (!response.body) throw new Error("juli stream has no body");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) return "ended";
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        const { frames, remainder } = extractSseFrames(buffer);
        buffer = remainder;
        for (const raw of frames) {
          const frame = parseSseFrame(raw);
          if (!frame) continue;
          let json: unknown;
          try {
            json = JSON.parse(frame.data);
          } catch {
            continue;
          }
          const event = parseJuliEvent(json, frame.event);
          if (!event) continue;
          const id = frame.id !== null && /^\d+$/.test(frame.id) ? Number(frame.id) : null;
          if (id !== null) {
            if (lastId !== null && id <= lastId) continue; // replayed prefix
            lastId = id;
          }
          attempts = 0;
          handlers.onReconnecting?.(false);
          handlers.onEvent(event);
          if (isJuliTerminalEvent(event)) return "terminal";
        }
      }
    }

    void (async () => {
      while (!closed) {
        try {
          const outcome = await connectOnce();
          if (outcome === "terminal") return finish("terminal-event");
        } catch (error) {
          if (controller.signal.aborted) return finish("aborted");
          if (error instanceof JuliApiError && [401, 403, 404].includes(error.status)) {
            return finish("failed");
          }
        }
        if (controller.signal.aborted) return finish("aborted");
        attempts += 1;
        if (attempts > max) return finish("failed");
        handlers.onReconnecting?.(true);
        await wait((config.reconnectDelayMs ?? backoff)(attempts));
      }
    })();

    return { abort: () => controller.abort() };
  }

  return {
    templates: () => call<JuliTemplatesResponse>("/templates"),
    ask: (request) => call<JuliAskResponse>("/ask", { method: "POST", body: JSON.stringify(request) }, true),
    stream,
    cancel: (id) => call<void>(`/messages/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
    conversations: async () => (await call<{ conversations: readonly JuliConversationSummary[] }>("/conversations")).conversations,
    conversation: async (id) =>
      adaptConversation(await call<{ id: string; title: string; messages: readonly JuliServerMessage[] }>(`/conversations/${encodeURIComponent(id)}`)),
    sendCard: (draftRef, versionLabel) =>
      call<JuliSendCardResponse>(
        `/cards/${encodeURIComponent(draftRef)}/send`,
        { method: "POST", body: JSON.stringify({ version_label: versionLabel }) },
        true,
      ),
    dismissCard: (draftRef) => call<void>(`/cards/${encodeURIComponent(draftRef)}/dismiss`, { method: "POST" }),
  };
}
