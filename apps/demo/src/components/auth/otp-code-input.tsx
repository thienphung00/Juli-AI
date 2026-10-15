"use client";

import { useRef, useState, type ClipboardEvent, type KeyboardEvent } from "react";

import { authOtpDigitLabel } from "../../lib/auth-screen-copy";
import { normaliseOtpCode } from "../../lib/supabase-auth";

/**
 * The OTP view's 6 boxes (D44.5, research REPORT §3). One digit per box,
 * `inputmode="numeric"`, `autocomplete="one-time-code"` on the first box (where
 * iOS / Android offer the code). A paste anywhere, or an autofill that drops the
 * whole code into one box, fills every box; a full code calls `onComplete`
 * (auto-submit). Backspace on an empty box steps back; arrows move.
 *
 * Uncontrolled from the parent's point of view: remount it (`key`) to clear.
 */

const LENGTH = 6;

export interface OtpCodeInputProps {
  readonly legend: string;
  readonly disabled?: boolean;
  readonly autoFocus?: boolean;
  readonly describedBy?: string;
  readonly invalid?: boolean;
  readonly onChange?: (code: string) => void;
  readonly onComplete: (code: string) => void;
}

export function OtpCodeInput({ legend, disabled, autoFocus, describedBy, invalid, onChange, onComplete }: OtpCodeInputProps) {
  const [digits, setDigits] = useState<string[]>(() => Array(LENGTH).fill(""));
  const refs = useRef<(HTMLInputElement | null)[]>([]);

  const focusBox = (index: number) => {
    const box = refs.current[Math.max(0, Math.min(LENGTH - 1, index))];
    box?.focus();
    box?.select();
  };

  const commit = (next: string[], focusIndex: number) => {
    setDigits(next);
    const code = next.join("");
    onChange?.(code);
    if (code.length === LENGTH && next.every((digit) => digit !== "")) {
      onComplete(code);
    } else {
      focusBox(focusIndex);
    }
  };

  /** Spread `incoming` digits from `start`; a full code always starts at box 1. */
  const fill = (start: number, incoming: string) => {
    const from = incoming.length >= LENGTH ? 0 : start;
    const next = [...digits];
    const chars = incoming.slice(0, LENGTH - from).split("");
    chars.forEach((char, offset) => {
      next[from + offset] = char;
    });
    commit(next, from + chars.length);
  };

  const onInput = (index: number, raw: string) => {
    const incoming = normaliseOtpCode(raw);
    if (incoming.length === 0) {
      const next = [...digits];
      next[index] = "";
      setDigits(next);
      onChange?.(next.join(""));
      return;
    }
    if (incoming.length === 1) {
      const next = [...digits];
      next[index] = incoming;
      commit(next, index + 1);
      return;
    }
    // Autofill or a paste the browser routed through `input`: the whole code
    // (or the part that fits), never "old digit + new digit" — focus selects
    // the box's content, so typing over a digit replaces it.
    fill(index, incoming);
  };

  const onPaste = (index: number, event: ClipboardEvent<HTMLInputElement>) => {
    const incoming = normaliseOtpCode(event.clipboardData.getData("text"));
    event.preventDefault();
    if (incoming.length > 0) fill(index, incoming);
  };

  const onKeyDown = (index: number, event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Backspace" && digits[index] === "" && index > 0) {
      event.preventDefault();
      const next = [...digits];
      next[index - 1] = "";
      setDigits(next);
      onChange?.(next.join(""));
      focusBox(index - 1);
    } else if (event.key === "ArrowLeft" && index > 0) {
      event.preventDefault();
      focusBox(index - 1);
    } else if (event.key === "ArrowRight" && index < LENGTH - 1) {
      event.preventDefault();
      focusBox(index + 1);
    }
  };

  return (
    <fieldset aria-describedby={describedBy} className="auth-otp">
      <legend className="auth-label">{legend}</legend>
      <div className="auth-otp__boxes">
        {digits.map((digit, index) => (
          <input
            aria-invalid={invalid || undefined}
            aria-label={authOtpDigitLabel(index)}
            autoComplete={index === 0 ? "one-time-code" : "off"}
            // The view swaps in after "Gửi mã": focus belongs on box 1.
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus={autoFocus && index === 0}
            className="auth-otp__box"
            disabled={disabled}
            inputMode="numeric"
            key={index}
            name={index === 0 ? "code" : undefined}
            onChange={(event) => onInput(index, event.target.value)}
            onFocus={(event) => event.target.select()}
            onKeyDown={(event) => onKeyDown(index, event)}
            onPaste={(event) => onPaste(index, event)}
            pattern="[0-9]*"
            ref={(element) => {
              refs.current[index] = element;
            }}
            type="text"
            value={digit}
          />
        ))}
      </div>
    </fieldset>
  );
}
