import { FormEvent, useState } from "react";

interface ChatInputProps {
  onSend: (text: string) => void;
  disabled?: boolean;
}

export function ChatInput({ onSend, disabled = false }: ChatInputProps) {
  const [value, setValue] = useState("");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex items-center gap-2 border-t pt-3"
      style={{ borderColor: "var(--border)" }}
      data-testid="chat-input-form"
    >
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Hỏi Juli về shop, creator, tồn kho..."
        className="flex-1 rounded-xl border px-4 py-2.5 text-sm outline-none"
        style={{
          borderColor: "var(--border)",
          background: "var(--background)",
          color: "var(--foreground)",
        }}
        disabled={disabled}
        data-testid="chat-input"
        aria-label="Nhập tin nhắn"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="rounded-xl px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        style={{ background: "linear-gradient(135deg, #ff006e 0%, #ff4d94 100%)" }}
        data-testid="chat-send-button"
        aria-label="Gửi tin nhắn"
      >
        Gửi
      </button>
    </form>
  );
}
