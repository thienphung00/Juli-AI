"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

import {
  GUIDE_CLOSE_LABEL,
  GUIDE_COLLAPSE_LABEL,
  GUIDE_DONE_LABEL,
  GUIDE_DURATION,
  GUIDE_EYEBROW,
  GUIDE_INTRO,
  GUIDE_PARTS,
  GUIDE_SHEET_TITLE,
  GUIDE_START_OVER,
  GUIDE_STEPS,
  GUIDE_STEPS_LABEL,
  GUIDE_TITLE,
  guideContinueLabel,
  guidePillLabel,
  guideProgress,
  type GuidePart,
  type GuideStep,
} from "../../lib/reviewer/guide-copy";
import { useReviewerGuide } from "../../lib/reviewer/guide-context";
import { useNarrow } from "../quyet-dinh/use-narrow";

/**
 * The partner reviewer guide (fast track P77): eight steps in three parts
 * (Read / Write / Check). A right-hand panel beside the page on desktop (it
 * stacks below the content when narrow), a floating pill when collapsed, and a
 * bottom sheet with Read / Write / Check tabs on phones. Rendered only for a
 * reviewer account; a seller never gets it. Steps tick on their own (see
 * `lib/reviewer/guide-context.tsx`) and by hand.
 */

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

function CloseIcon() {
  return (
    <svg aria-hidden="true" fill="none" height="18" stroke="currentColor" strokeLinecap="round" strokeWidth="2" viewBox="0 0 24 24" width="18">
      <path d="M6 6l12 12" />
      <path d="M18 6L6 18" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg aria-hidden="true" fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" viewBox="0 0 24 24" width="15">
      <path d="M5 12l5 5 9-10" />
    </svg>
  );
}

function StepRow({
  step,
  n,
  done,
  compact,
  onToggle,
  onSwitch,
}: {
  readonly step: GuideStep;
  readonly n: number;
  readonly done: boolean;
  readonly compact: boolean;
  readonly onToggle: () => void;
  readonly onSwitch?: () => void;
}) {
  return (
    <li className="rg-step" data-done={done ? "true" : "false"}>
      <button aria-pressed={done} className="rg-step__toggle" data-testid={`guide-step-${step.id}`} onClick={onToggle} type="button">
        <span aria-hidden="true" className={done ? "rg-step__mark rg-step__mark--done" : "rg-step__mark"}>
          {done ? <CheckIcon /> : n}
        </span>
        <span className="rg-step__text">
          <span className="rg-step__title">{compact ? step.shortTitle : step.title}</span>
          <span className="rg-step__body">{compact ? step.shortBody : step.body}</span>
        </span>
      </button>
      {(
        step.href ? (
          <Link className="rg-step__where" href={step.href}>
            {step.where}
          </Link>
        ) : (
          <button className="rg-step__where" data-testid="guide-switch-shop" onClick={onSwitch} type="button">
            {step.where}
          </button>
        )
      )}
    </li>
  );
}

export function ReviewerGuide({ onSwitchToSandbox }: { readonly onSwitchToSandbox?: () => void }) {
  const guide = useReviewerGuide();
  const narrow = useNarrow();
  const [tab, setTab] = useState<GuidePart>("read");
  const pillRef = useRef<HTMLButtonElement>(null);
  const sheetRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const focusPill = useRef(false);

  const { open } = guide.state;
  const enabled = guide.enabled;

  // After a collapse, focus moves to the pill that replaced the panel.
  useEffect(() => {
    if (!open && focusPill.current) {
      focusPill.current = false;
      pillRef.current?.focus();
    }
  }, [open]);

  // The phone sheet is modal: focus goes in when it opens.
  useEffect(() => {
    if (enabled && narrow && open) closeRef.current?.focus();
  }, [enabled, narrow, open]);

  if (!enabled) return null;

  const done = guide.state.done;
  const total = GUIDE_STEPS.length;
  const count = GUIDE_STEPS.filter((step) => done.includes(step.id)).length;
  const nextIndex = GUIDE_STEPS.findIndex((step) => !done.includes(step.id));
  const finished = nextIndex === -1;
  const nextStep = finished ? null : GUIDE_STEPS[nextIndex];

  const collapse = () => {
    focusPill.current = true;
    guide.setOpen(false);
  };

  const onEscape = (event: ReactKeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      collapse();
    }
  };

  const onSheetKey = (event: ReactKeyboardEvent<HTMLElement>) => {
    onEscape(event);
    if (event.key !== "Tab" || !sheetRef.current) return;
    const items = Array.from(sheetRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !sheetRef.current.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !sheetRef.current.contains(active))) {
      event.preventDefault();
      first.focus();
    }
  };

  const cta = nextStep ? (
    nextStep.href ? (
      <Link className="rg-btn rg-btn--primary rg-cta" data-testid="guide-cta" href={nextStep.href}>
        {guideContinueLabel(nextIndex + 1)}
      </Link>
    ) : (
      <button className="rg-btn rg-btn--primary rg-cta" data-testid="guide-cta" onClick={onSwitchToSandbox} type="button">
        {guideContinueLabel(nextIndex + 1)}
      </button>
    )
  ) : (
    <button className="rg-btn rg-btn--primary rg-cta" data-testid="guide-cta" onClick={collapse} type="button">
      {GUIDE_DONE_LABEL}
    </button>
  );

  const progress = (
    <div
      aria-label={guideProgress(count, total)}
      aria-valuemax={total}
      aria-valuemin={0}
      aria-valuenow={count}
      className="rg-progress__bar"
      role="progressbar"
    >
      <div className="rg-progress__fill" style={{ width: `${Math.round((count / total) * 100)}%` }} />
    </div>
  );

  const pill = (
    <button
      className={narrow ? "rg-pill rg-pill--phone" : "rg-pill"}
      data-testid="guide-pill"
      onClick={() => guide.setOpen(true)}
      ref={pillRef}
      type="button"
    >
      <span aria-hidden="true" className="rg-pill__dot" />
      {guidePillLabel(count, total)}
    </button>
  );

  if (!open) return pill;

  if (narrow) {
    const steps = GUIDE_STEPS.filter((step) => step.part === tab);
    return (
      <>
        <div aria-hidden="true" className="rg-scrim" />
        <section
          aria-labelledby="rg-sheet-title"
          aria-modal="true"
          className="rg-sheet"
          data-testid="reviewer-guide-sheet"
          onKeyDown={onSheetKey}
          ref={sheetRef}
          role="dialog"
        >
          <div aria-hidden="true" className="rg-sheet__grip" />
          <div className="rg-head">
            <div className="rg-head__text">
              <p className="rg-eyebrow">{GUIDE_EYEBROW}</p>
              <h2 className="rg-title rg-title--sheet" id="rg-sheet-title">
                {GUIDE_SHEET_TITLE}
              </h2>
            </div>
            <button aria-label={GUIDE_CLOSE_LABEL} className="rg-icon-btn" onClick={collapse} ref={closeRef} type="button">
              <CloseIcon />
            </button>
          </div>
          <div className="rg-progress">
            <p className="rg-progress__label">{guideProgress(count, total)}</p>
            {progress}
          </div>
          <div className="rg-tabs">
            {GUIDE_PARTS.map((part) => (
              <button
                aria-pressed={tab === part.id}
                className="rg-tab"
                key={part.id}
                onClick={() => setTab(part.id)}
                type="button"
              >
                {part.tab}
              </button>
            ))}
          </div>
          <ul aria-label={GUIDE_STEPS_LABEL} className="rg-steps rg-steps--scroll">
            {steps.map((step) => (
              <StepRow
                compact
                done={done.includes(step.id)}
                key={step.id}
                n={GUIDE_STEPS.indexOf(step) + 1}
                onSwitch={onSwitchToSandbox}
                onToggle={() => guide.toggle(step.id)}
                step={step}
              />
            ))}
          </ul>
          {cta}
        </section>
      </>
    );
  }

  return (
    <aside aria-labelledby="rg-title" className="rg-panel" data-testid="reviewer-guide" onKeyDown={onEscape}>
      <div className="rg-head">
        <div className="rg-head__text">
          <p className="rg-eyebrow">{GUIDE_EYEBROW}</p>
          <h2 className="rg-title" id="rg-title">
            {GUIDE_TITLE}
          </h2>
        </div>
        <button aria-label={GUIDE_COLLAPSE_LABEL} className="rg-icon-btn" onClick={collapse} type="button">
          <CloseIcon />
        </button>
      </div>
      <p className="rg-intro">{GUIDE_INTRO}</p>
      <div className="rg-progress">
        <div className="rg-progress__row">
          <span className="rg-progress__label">{guideProgress(count, total)}</span>
          <span className="rg-progress__time">{GUIDE_DURATION}</span>
        </div>
        {progress}
      </div>
      {GUIDE_PARTS.map((part) => (
        <section aria-label={part.title} className="rg-part" key={part.id}>
          <div className="rg-part__head">
            <span className={`rg-chip rg-chip--${part.id}`}>{part.chip}</span>
            <span className="rg-part__title">{part.title}</span>
          </div>
          <ul className="rg-steps">
            {GUIDE_STEPS.filter((step) => step.part === part.id).map((step) => (
              <StepRow
                compact={false}
                done={done.includes(step.id)}
                key={step.id}
                n={GUIDE_STEPS.indexOf(step) + 1}
                onSwitch={onSwitchToSandbox}
                onToggle={() => guide.toggle(step.id)}
                step={step}
              />
            ))}
          </ul>
        </section>
      ))}
      <div className="rg-actions">
        {cta}
        <button className="rg-btn rg-btn--secondary" onClick={() => guide.reset()} type="button">
          {GUIDE_START_OVER}
        </button>
      </div>
    </aside>
  );
}
