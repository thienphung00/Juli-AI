interface SuggestedPromptsProps {
  prompts: string[];
  onSelect: (prompt: string) => void;
  disabled?: boolean;
}

export function SuggestedPrompts({ prompts, onSelect, disabled = false }: SuggestedPromptsProps) {
  if (prompts.length === 0) return null;

  return (
    <div
      className="scrollbar-hide -mx-1 flex gap-2 overflow-x-auto px-1 pb-2"
      data-testid="suggested-prompts"
    >
      {prompts.map((prompt) => (
        <button
          key={prompt}
          type="button"
          onClick={() => onSelect(prompt)}
          disabled={disabled}
          className="shrink-0 rounded-full border px-3 py-1.5 text-xs font-medium whitespace-nowrap disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
          style={{
            borderColor: "var(--border)",
            color: "var(--foreground)",
            background: "var(--card)",
          }}
          data-testid="suggested-prompt-chip"
        >
          {prompt}
        </button>
      ))}
    </div>
  );
}
