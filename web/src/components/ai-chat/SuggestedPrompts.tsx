interface SuggestedPromptsProps {
  prompts: string[];
  onSelect: (prompt: string) => void;
  disabled?: boolean;
}

export function SuggestedPrompts({ prompts, onSelect, disabled = false }: SuggestedPromptsProps) {
  if (prompts.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2" data-testid="suggested-prompts">
      {prompts.map((prompt) => (
        <button
          key={prompt}
          type="button"
          onClick={() => onSelect(prompt)}
          disabled={disabled}
          className="rounded-full border px-3 py-1.5 text-xs font-medium disabled:opacity-50"
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
