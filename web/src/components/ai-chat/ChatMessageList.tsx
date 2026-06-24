import type { ChatMessage } from "@/lib/mock-data/ai-chat";

function sanitizeContent(text: string): string {
  return text.replace(/[<>]/g, "");
}

export function ChatMessageList({ messages }: { messages: ChatMessage[] }) {
  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col gap-3" data-testid="chat-message-list">
        <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
          Chưa có tin nhắn — hãy chọn đề xuất hoặc nhập câu hỏi.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col gap-3" data-testid="chat-message-list">
      {messages.map((message) => (
        <div
          key={message.id}
          className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
          data-testid={`chat-message-${message.role}`}
        >
          <div
            className="max-w-[85%] rounded-2xl px-4 py-3 text-sm"
            style={{
              background:
                message.role === "user"
                  ? "var(--brand-gradient)"
                  : "var(--card)",
              color: message.role === "user" ? "#fff" : "var(--foreground)",
              border:
                message.role === "assistant" ? "1px solid var(--border)" : undefined,
            }}
          >
            <p>{sanitizeContent(message.content)}</p>
            {message.role === "assistant" && message.actions && message.actions.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-2">
                {message.actions.map((action) => (
                  <a
                    key={`${message.id}-${action.href}`}
                    href={action.href}
                    className="inline-flex rounded-lg px-2.5 py-1 text-xs font-semibold"
                    style={{
                      background: "var(--primary)",
                      color: "#fff",
                    }}
                    data-testid="chat-action-link"
                  >
                    {action.label}
                  </a>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
