import { FormEvent, useState } from "react";

interface ChatInputProps {
  onSend: (text: string) => void;
  disabled?: boolean;
  borderless?: boolean;
}

export function ChatInput({ onSend, disabled = false, borderless = false }: ChatInputProps) {
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
      className={borderless ? "mt-2 flex items-center gap-2" : "flex items-center gap-2 border-t pt-3"}
      style={borderless ? undefined : { borderColor: "var(--border)" }}
      data-testid="chat-input-form"
    >
      <input
        type="text"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Hỏi Juli về shop, creator, tồn kho..."
        className="flex-1 rounded-xl border px-4 py-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
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
        className="min-h-[44px] rounded-xl px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
        style={{ background: "var(--brand-gradient)" }}
        data-testid="chat-send-button"
        aria-label="Gửi tin nhắn"
      >
        Gửi
      </button>
    </form>
  );
}
