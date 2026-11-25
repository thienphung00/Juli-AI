"use client";

import { useState, type KeyboardEvent, type RefObject } from "react";
import type { JuliTemplate } from "@juli/contracts";

/** The API accepts at most this many characters per question (juli_agent.py text max_length). */
export const MAX_QUESTION_CHARS = 2000;
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

/** Grow the textarea to its content; CSS max-height takes over with a scrollbar. Plain DOM write, no state. */
function fit(el: HTMLTextAreaElement | null) {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
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
  readonly inputRef: RefObject<HTMLTextAreaElement | null>;
  readonly onSubmit: (text: string) => void;
  readonly onStop: () => void;
}) {
  const [text, setText] = useState("");
  const trimmed = text.trim();
  const canSend = !running && !disabled && trimmed.length > 0;
  const send = () => {
    if (!canSend) return;
    onSubmit(trimmed);
    setText("");
    if (inputRef.current) inputRef.current.style.height = "";
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey) return; // Shift+Enter: a new line
    // A Vietnamese Telex / IME composition uses Enter to commit the word: never send then.
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    send();
  };
  return (
    <form
      className={`juli-input${disabled ? " juli-input--off" : ""}`}
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      <textarea
        ref={inputRef}
        className="juli-input__field"
        rows={1}
        aria-label="Hỏi Juli về shop của bạn"
        placeholder={running ? INPUT_PLACEHOLDER_RUNNING : INPUT_PLACEHOLDER}
        value={text}
        disabled={disabled}
        maxLength={MAX_QUESTION_CHARS}
        onKeyDown={onKeyDown}
        onChange={(e) => {
          setText(e.target.value);
          fit(e.target);
        }}
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
