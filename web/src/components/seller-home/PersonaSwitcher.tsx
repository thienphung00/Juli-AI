"use client";

import { listPersonaIds } from "@/lib/mock-data/seller-personas";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { useDemoPersonaOptional } from "@/lib/demo-persona-context";
import { useWorkspaceModeOptional } from "@/lib/mode-context";
import { PERSONA_SWITCHER_LABELS } from "@/lib/seller-workflows";

export function PersonaSwitcher() {
  const modeContext = useWorkspaceModeOptional();
  const personaContext = useDemoPersonaOptional();

  if (modeContext?.mode !== "seller" || !personaContext) {
    return null;
  }

  const { personaId, setPersonaId } = personaContext;

  return (
    <div
      className="flex gap-1 rounded-full p-0.5"
      data-testid="persona-switcher"
      role="group"
      aria-label="Chọn persona demo"
      style={{ background: "var(--muted)", border: "1px solid var(--border)" }}
    >
      {listPersonaIds().map((id) => (
        <PersonaButton
          key={id}
          id={id}
          isActive={personaId === id}
          onSelect={setPersonaId}
        />
      ))}
    </div>
  );
}

function PersonaButton({
  id,
  isActive,
  onSelect,
}: {
  id: PersonaId;
  isActive: boolean;
  onSelect: (id: PersonaId) => void;
}) {
  const label = PERSONA_SWITCHER_LABELS[id];

  return (
    <button
      type="button"
      aria-pressed={isActive}
      aria-label={label}
      onClick={() => onSelect(id)}
      className="rounded-full px-2 py-1 text-[10px] font-semibold transition-opacity hover:opacity-90 sm:px-2.5 sm:text-xs"
      style={{
        background: isActive ? "var(--primary)" : "transparent",
        color: isActive ? "#fff" : "var(--foreground)",
      }}
    >
      {label}
    </button>
  );
}
