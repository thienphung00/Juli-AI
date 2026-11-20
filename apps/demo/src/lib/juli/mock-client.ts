/**
 * In-memory `JuliClient` that replays the board fixtures. Used by tests and while the backend (T3)
 * is not wired; it speaks the same interface as `createJuliClient`.
 */
import type {
  JuliAgentEvent,
  JuliConversation,
  JuliConversationSummary,
  JuliStoredMessage,
} from "@juli/contracts";

import type { JuliClient, JuliStreamHandlers } from "./client";
import { FIXTURE_BY_KEY, TEMPLATES, UNSUPPORTED } from "./fixtures";

export interface MockJuliOptions {
  /** Delay between events (ms); 0 replays on the next macrotask. */
  delayMs?: number;
  /** Picks the events for an ask; defaults to the template fixture, else "unsupported". */
  script?: (request: { text?: string; template?: string; choice?: { item: string; value: string } }) => readonly JuliAgentEvent[];
  history?: readonly JuliConversation[];
  readOnly?: boolean;
}

export function createMockJuliClient(options: MockJuliOptions = {}): JuliClient & {
  readonly calls: { sendCard: [string, string][]; dismissCard: string[]; cancel: string[]; ask: unknown[] };
} {
  const delayMs = options.delayMs ?? 0;
  const calls = { sendCard: [] as [string, string][], dismissCard: [] as string[], cancel: [] as string[], ask: [] as unknown[] };
  const pending = new Map<string, { events: readonly JuliAgentEvent[]; question: string; conversationId: string }>();
  const conversations = new Map<string, JuliConversation>((options.history ?? []).map((c) => [c.id, c]));
  let counter = 0;

  const script =
    options.script ??
    ((request) => (request.template ? (FIXTURE_BY_KEY[request.template] ?? UNSUPPORTED) : UNSUPPORTED));

  return {
    calls,
    templates: async () => ({ templates: TEMPLATES, shop_state: { read_only: options.readOnly ?? false } }),
    async ask(request) {
      calls.ask.push(request);
      counter += 1;
      const conversationId = request.conversation_id ?? `conv-${counter}`;
      const messageId = `msg-${counter}`;
      const label = TEMPLATES.find((t) => t.key === request.template)?.label_vi;
      pending.set(messageId, {
        events: script(request),
        question: request.text ?? label ?? request.choice?.value ?? "",
        conversationId,
      });
      return { conversation_id: conversationId, message_id: messageId };
    },
    stream(messageId, handlers: JuliStreamHandlers) {
      let aborted = false;
      const run = pending.get(messageId);
      void (async () => {
        for (const event of run?.events ?? []) {
          await new Promise((r) => setTimeout(r, delayMs));
          if (aborted) return handlers.onClose?.("aborted");
          handlers.onEvent(event);
        }
        if (run) {
          const stored: JuliStoredMessage = { id: messageId, question: run.question, events: run.events, created_at: new Date().toISOString() };
          const existing = conversations.get(run.conversationId);
          conversations.set(run.conversationId, {
            id: run.conversationId,
            title: existing?.title ?? run.question,
            messages: [...(existing?.messages ?? []), stored],
          });
        }
        handlers.onClose?.("terminal-event");
      })();
      return { abort: () => { aborted = true; } };
    },
    async cancel(id) {
      calls.cancel.push(id);
    },
    async conversations() {
      return [...conversations.values()].map<JuliConversationSummary>((c) => ({
        id: c.id,
        title: c.title,
        updated_at: c.messages.at(-1)?.created_at ?? new Date().toISOString(),
      }));
    },
    async conversation(id) {
      const c = conversations.get(id);
      if (!c) throw new Error("not found");
      return c;
    },
    async sendCard(draftRef, versionLabel) {
      calls.sendCard.push([draftRef, versionLabel]);
      return { card_code: "JC-2611-0042" };
    },
    async dismissCard(draftRef) {
      calls.dismissCard.push(draftRef);
    },
  };
}
