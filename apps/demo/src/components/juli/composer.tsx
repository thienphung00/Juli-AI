"use client";

import { useState, type RefObject } from "react";
import type { JuliTemplate } from "@juli/contracts";

export const INPUT_PLACEHOLDER = "Hỏi Juli về shop của bạn…";
export const INPUT_PLACEHOLDER_RUNNING = "Bạn có thể gõ câu tiếp theo…";

/** U2c: template buttons under the input; one swipeable row on mobile (CSS). Hidden while running or blocked. */
export function TemplateRow({
  templates,
  onPick,
}: {
  readonly templates: readonly JuliTemplate[];
  readonly onPick: (template: JuliTemplate) => void;
}) {
  return (
    <div className="juli-chips" role="group" aria-label="Mẫu câu hỏi">
      {templates.map((t) => (
        <button key={t.key} type="button" className="juli-chip" onClick={() => onPick(t)}>
          {t.label_vi}
        </button>
      ))}
    </div>
  );
}

export function Composer({
  running,
  disabled,
  inputRef,
  onSubmit,
  onStop,
}: {
  readonly running: boolean;
  /** Limit or backfilling: the input is off. */
  readonly disabled: boolean;
  readonly inputRef: RefObject<HTMLInputElement | null>;
  readonly onSubmit: (text: string) => void;
  readonly onStop: () => void;
}) {
  const [text, setText] = useState("");
  const trimmed = text.trim();
  const canSend = !running && !disabled && trimmed.length > 0;
  return (
    <form
      className={`juli-input${disabled ? " juli-input--off" : ""}`}
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSend) return;
        onSubmit(trimmed);
        setText("");
      }}
    >
      <input
        ref={inputRef}
        className="juli-input__field"
        type="text"
        aria-label="Hỏi Juli về shop của bạn"
        placeholder={running ? INPUT_PLACEHOLDER_RUNNING : INPUT_PLACEHOLDER}
        value={text}
        disabled={disabled}
        maxLength={500}
        onChange={(e) => setText(e.target.value)}
      />
      {running ? (
        <button type="button" className="juli-stop" onClick={onStop}>
          <span className="juli-stop__sq" aria-hidden="true" />
          Dừng
        </button>
      ) : null}
      <button type="submit" className="juli-send" aria-label="Gửi" disabled={!canSend}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      </button>
    </form>
  );
}
