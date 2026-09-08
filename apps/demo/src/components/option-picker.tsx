"use client";

/**
 * The consent-grade option picker (issue #1317, ADR-076 decision 4,
 * PUI-DESIGN.md §3). Renders the N options carried on a
 * `workflow.approval_required` event as side-by-side cards -- a real
 * radio-group equivalent -- and owns the two-step consent flow: SELECT
 * (a card elevates, siblings dim, the CTA arms) then CONFIRM (fires). A
 * single click never authorizes a mutation -- `handleConfirm` is the only
 * function in this module that calls the confirmation client, and it is
 * wired to the CTA button alone, never to a card's own click handler.
 *
 * EVERY RENDERED NUMBER AND STRING TRACES TO THE PAYLOAD. `option_id`,
 * `proposed_change`, and `rationale` are read verbatim off each
 * `ConfirmationOptionPayload` this component is given -- nothing here
 * formats a percentage, invents an expected-effect figure, or otherwise
 * computes seller-facing content the payload did not already carry. The
 * before/after diff (`option-diff.ts`) is pure and documents its one named
 * exception (title's "before" falls back to `productName`) rather than
 * inventing silently.
 *
 * DECLINE IS NEVER GATED BEHIND SELECTION OR HIDDEN BEHIND CONFIRM. It is a
 * sibling control, always enabled (until expiry/submission/a terminal
 * outcome), reachable by Tab independent of the radiogroup's roving
 * tabindex -- "a choice, not a failure exit" (PUI-DESIGN.md §3).
 *
 * EXPIRY IS SERVER-DRIVEN. `resolveExpiryCountdown` (already built for the
 * run ledger, #1318) recomputes `expiresAt - nowMs` fresh on every render;
 * nothing here starts its own countdown timer that could drift from the
 * server's clock.
 */

import { useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import type { ConfirmationOptionPayload } from "@juli/contracts";

import { formatRunExpiryCopy } from "../lib/run-ledger/copy";
import { resolveExpiryCountdown } from "../lib/run-ledger/expiry";
import { buildOptionDiffRows, describeOptionField } from "../lib/run-surface/option-diff";
import {
  ConfirmationRejectedError,
  type ConfirmationErrorCode,
  type ConfirmDecisionFn,
  type SubmitConfirmationDecisionOptions,
} from "../lib/run-surface/confirmation-decision";
import {
  OPTION_PICKER_CONFIRM_LABEL,
  OPTION_PICKER_DECLINE_LABEL,
  OPTION_PICKER_DECLINE_OUTCOME,
  OPTION_PICKER_EXPIRED_COPY,
  OPTION_PICKER_NO_RETRY_COPY,
  OPTION_PICKER_SUBMITTING_COPY,
  describeConfirmationRejection,
  formatOptionPickerHeading,
} from "../lib/run-surface/option-picker-copy";
import { prefersReducedMotion, resolveRunSurfaceMotion } from "../lib/run-surface/motion";
import { RUN_SURFACE_LIVE_EDGE_CLASS_NAMES } from "../lib/run-surface/tokens";

export interface OptionPickerProps {
  readonly runId: string;
  readonly toolCallId: string;
  readonly options: readonly ConfirmationOptionPayload[];
  readonly expiresAt: string;
  /** The wall clock for the countdown -- sourced by the parent, never read
   *  here via `Date.now()` (purity, matches `RunStageCanvas`'s `nowMs`). */
  readonly nowMs: number | null;
  readonly productName: string;
  readonly token?: string;
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
  /** Required -- issue #1764 removed the implicit "defaults to the real
   *  HTTP client" fallback that silently let a caller forget to wire one
   *  up (exactly the bug that shipped the replay door's confirm button
   *  firing a real, unauthenticated request). Every real call site now
   *  wires this explicitly: the signed-in door passes
   *  `submitConfirmationDecision` (`confirmation-client.ts`), the replay
   *  door passes its own local continuation-resolving handler
   *  (`replay-confirm.ts`). Left optional in the TYPE (not required) only
   *  so tests that never exercise the confirm/decline path do not have to
   *  supply one -- `decide()` below fails loudly if it is ever actually
   *  invoked without one. */
  readonly confirm?: ConfirmDecisionFn;
}

type PickerStatus = "idle" | "submitting" | "confirmed" | "declined" | "rejected";

function joinClassNames(...names: Array<string | false | undefined>): string {
  return names.filter(Boolean).join(" ");
}

export function OptionPicker({
  runId,
  toolCallId,
  options,
  expiresAt,
  nowMs,
  productName,
  token,
  baseUrl,
  fetchImpl,
  confirm,
}: OptionPickerProps) {
  const [selectedOptionId, setSelectedOptionId] = useState<string | null>(null);
  const [focusedIndex, setFocusedIndex] = useState(0);
  const [status, setStatus] = useState<PickerStatus>("idle");
  const [rejection, setRejection] = useState<{
    errorCode: ConfirmationErrorCode | null;
    message: string;
  } | null>(null);
  const cardRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const expiry = nowMs !== null ? resolveExpiryCountdown(expiresAt, nowMs) : null;
  const expired = expiry?.expired ?? false;
  const interactionDisabled = expired || status !== "idle";

  const requestOptions: SubmitConfirmationDecisionOptions = { token, baseUrl, fetchImpl };

  async function decide(decision: "approve" | "decline") {
    if (interactionDisabled) return;
    if (decision === "approve" && !selectedOptionId) return;

    if (!confirm) {
      // Every real call site must wire a confirm handler explicitly (see
      // the prop's own doc comment) -- reaching here means a caller
      // forgot, which must fail loudly rather than silently do nothing or
      // silently reach for a network client that was never intended.
      throw new Error("OptionPicker rendered without a confirm handler");
    }

    setStatus("submitting");
    try {
      await confirm(
        runId,
        toolCallId,
        decision,
        decision === "approve" ? selectedOptionId : null,
        requestOptions,
      );
      setStatus(decision === "approve" ? "confirmed" : "declined");
    } catch (error) {
      if (error instanceof ConfirmationRejectedError) {
        setRejection({ errorCode: error.errorCode, message: error.message });
      } else {
        setRejection({ errorCode: null, message: (error as Error).message });
      }
      setStatus("rejected");
    }
  }

  function moveSelection(rawIndex: number) {
    if (options.length === 0) return;
    const nextIndex = ((rawIndex % options.length) + options.length) % options.length;
    setFocusedIndex(nextIndex);
    setSelectedOptionId(options[nextIndex]!.option_id);
    // Native radiogroup semantics: an arrow key moves focus AND selection
    // together, in one keystroke -- `.focus()` here is that "together,"
    // since the roving tabindex driving normal Tab focus only updates on
    // the NEXT render.
    cardRefs.current[nextIndex]?.focus();
  }

  function handleRadioGroupKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (interactionDisabled) return;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        event.preventDefault();
        moveSelection(focusedIndex + 1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        event.preventDefault();
        moveSelection(focusedIndex - 1);
        break;
      case "Home":
        event.preventDefault();
        moveSelection(0);
        break;
      case "End":
        event.preventDefault();
        moveSelection(options.length - 1);
        break;
      default:
        break;
    }
  }

  if (status === "declined") {
    return (
      <div className="option-picker option-picker--outcome" role="status">
        <p className="option-picker__outcome">{OPTION_PICKER_DECLINE_OUTCOME}</p>
      </div>
    );
  }

  const reducedMotion = prefersReducedMotion();
  const arriveMotion = resolveRunSurfaceMotion(
    "option-cards-arrive",
    { kind: "state-transition", from: "absent", to: "presented" },
    reducedMotion,
  );
  const selectMotion = resolveRunSurfaceMotion(
    "select-option",
    { kind: "state-transition", from: "unselected", to: "selected" },
    reducedMotion,
  );

  return (
    <div className="option-picker">
      <p className="option-picker__heading">{formatOptionPickerHeading(options.length)}</p>

      <div
        aria-label={formatOptionPickerHeading(options.length)}
        className="option-picker__grid"
        onKeyDown={handleRadioGroupKeyDown}
        role="radiogroup"
      >
        {options.map((option, index) => {
          const isSelected = option.option_id === selectedOptionId;
          const diffRows = buildOptionDiffRows(option.proposed_change, productName);
          // The listing miniature's headline is the FIRST proposed field --
          // "the proposed value prominent" (PUI-DESIGN.md §3). Every real
          // option today changes exactly one field; a future multi-field
          // proposal still renders every row honestly, the rest just below
          // in the smaller diff list rather than silently dropped.
          const [headlineRow, ...restRows] = diffRows;

          return (
            <button
              key={option.option_id}
              ref={(el) => {
                cardRefs.current[index] = el;
              }}
              aria-checked={isSelected}
              className={joinClassNames(
                "option-picker__card",
                isSelected ? "option-picker__card--selected" : undefined,
                selectedOptionId !== null && !isSelected
                  ? "option-picker__card--dimmed"
                  : undefined,
              )}
              disabled={interactionDisabled}
              onClick={() => {
                setFocusedIndex(index);
                setSelectedOptionId(option.option_id);
              }}
              onFocus={() => setFocusedIndex(index)}
              role="radio"
              style={{
                animationDelay: reducedMotion ? "0ms" : `${index * 150}ms`,
                animationDuration: `${arriveMotion.durationMs}ms`,
                animationTimingFunction: arriveMotion.easing,
                transitionDuration: `${selectMotion.durationMs}ms`,
                transitionTimingFunction: selectMotion.easing,
              }}
              tabIndex={index === focusedIndex ? 0 : -1}
              type="button"
            >
              {headlineRow ? (
                <div className="option-picker__headline">
                  <p className="option-picker__headline-label">
                    {describeOptionField(headlineRow.field)}
                  </p>
                  <p className="option-picker__headline-value">{headlineRow.after}</p>
                  {headlineRow.before !== undefined ? (
                    <p className="option-picker__headline-diff">
                      <span className="option-picker__diff-before">{headlineRow.before}</span>
                      <span aria-hidden="true" className="option-picker__diff-arrow">
                        →
                      </span>
                      <span className="option-picker__diff-after">{headlineRow.after}</span>
                    </p>
                  ) : null}
                </div>
              ) : null}
              {restRows.length > 0 ? (
                <dl className="option-picker__diff">
                  {restRows.map((row) => (
                    <div className="option-picker__diff-row" key={row.field}>
                      <dt>{describeOptionField(row.field)}</dt>
                      <dd>
                        {row.before !== undefined ? (
                          <span className="option-picker__diff-before">{row.before}</span>
                        ) : null}
                        <span className="option-picker__diff-after">{row.after}</span>
                      </dd>
                    </div>
                  ))}
                </dl>
              ) : null}
              {option.rationale ? (
                <p className="option-picker__rationale">{option.rationale}</p>
              ) : null}
            </button>
          );
        })}
      </div>

      {expiry ? (
        <p className="run-stage__expiry option-picker__expiry">
          {expired ? OPTION_PICKER_EXPIRED_COPY : formatRunExpiryCopy(expiry.label)}
        </p>
      ) : null}

      {status === "rejected" && rejection ? (
        <p className="option-picker__rejection" role="alert">
          {describeConfirmationRejection(rejection.errorCode)}
        </p>
      ) : null}

      {expired || status === "rejected" ? (
        <p className="option-picker__no-retry">{OPTION_PICKER_NO_RETRY_COPY}</p>
      ) : null}

      {status === "submitting" ? (
        <p className="option-picker__submitting" role="status">
          {OPTION_PICKER_SUBMITTING_COPY}
        </p>
      ) : null}

      <div className="option-picker__actions">
        <button
          className="option-picker__decline"
          disabled={interactionDisabled}
          onClick={() => void decide("decline")}
          type="button"
        >
          {OPTION_PICKER_DECLINE_LABEL}
        </button>
        <button
          className={joinClassNames(
            "option-picker__confirm",
            selectedOptionId !== null && !interactionDisabled
              ? RUN_SURFACE_LIVE_EDGE_CLASS_NAMES.ctaArmed
              : undefined,
          )}
          disabled={selectedOptionId === null || interactionDisabled}
          onClick={() => void decide("approve")}
          type="button"
        >
          {OPTION_PICKER_CONFIRM_LABEL}
        </button>
      </div>
    </div>
  );
}
