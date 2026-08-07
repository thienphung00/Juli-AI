"use client";

import { Button } from "@juli/ui";

import {
  REPEAT_CONSENT_COPY,
  type RepeatConsentSurface,
  createRepeatConsentGrant,
  withdrawRepeatConsentGrant,
} from "../lib/repeat-consent";
import { useDemoState } from "./demo-state";

interface RepeatConsentBlockProps {
  /** The workflow **kind** the standing permission would cover. */
  workflowKey: string;
  /**
   * Which surface this execution owns, decided by
   * `selectRepeatConsentSurfaces` — the component never re-derives the gates.
   * `undefined` means this execution carries no consent surface at all.
   */
  surface: RepeatConsentSurface | undefined;
}

/**
 * The repeat-consent surface (ADR-055 item 19). It renders after the work is
 * finished, never inside the approve step: approving starts one piece of work
 * and grants nothing standing.
 */
export function RepeatConsentBlock({
  workflowKey,
  surface,
}: RepeatConsentBlockProps) {
  const { updateMutableState } = useDemoState();

  if (!surface) {
    return null;
  }

  const recordAnswer = (granted: boolean) => {
    updateMutableState((current) => ({
      ...current,
      repeatConsentPromptedWorkflowKeys:
        current.repeatConsentPromptedWorkflowKeys.includes(workflowKey)
          ? current.repeatConsentPromptedWorkflowKeys
          : [...current.repeatConsentPromptedWorkflowKeys, workflowKey],
      repeatConsentGrants: granted
        ? {
            ...current.repeatConsentGrants,
            [workflowKey]: createRepeatConsentGrant(
              workflowKey,
              new Date().toISOString(),
            ),
          }
        : current.repeatConsentGrants,
    }));
  };

  /**
   * Withdrawal is one action with immediate effect: no confirmation dialog, no
   * second approval, no waiting period.
   */
  const withdraw = () => {
    updateMutableState((current) => {
      const grant = current.repeatConsentGrants[workflowKey];
      if (!grant) {
        return current;
      }

      return {
        ...current,
        repeatConsentGrants: {
          ...current.repeatConsentGrants,
          [workflowKey]: withdrawRepeatConsentGrant(
            grant,
            new Date().toISOString(),
          ),
        },
      };
    });
  };

  if (surface === "prompt") {
    return (
      <div
        className="repeat-consent repeat-consent--prompt"
        data-testid="repeat-consent-prompt"
        data-workflow-kind={workflowKey}
      >
        <p className="repeat-consent__title">
          {REPEAT_CONSENT_COPY.promptTitle}
        </p>
        <p className="repeat-consent__body">{REPEAT_CONSENT_COPY.promptBody}</p>
        <div className="repeat-consent__actions">
          <Button size="small" onClick={() => recordAnswer(true)}>
            {REPEAT_CONSENT_COPY.grantLabel}
          </Button>
          <Button
            size="small"
            variant="secondary"
            onClick={() => recordAnswer(false)}
          >
            {REPEAT_CONSENT_COPY.declineLabel}
          </Button>
        </div>
      </div>
    );
  }

  if (surface === "granted") {
    return (
      <div
        className="repeat-consent repeat-consent--granted"
        data-testid="repeat-consent-granted"
        data-workflow-kind={workflowKey}
        role="status"
      >
        <p className="repeat-consent__title">
          {REPEAT_CONSENT_COPY.grantedTitle}
        </p>
        {/* The standing permission restated in plain terms, so the seller can
            read back exactly what they agreed to — including that every run is
            reported to them. */}
        <ul className="repeat-consent__terms">
          {REPEAT_CONSENT_COPY.grantedTerms.map((term) => (
            <li key={term}>{term}</li>
          ))}
        </ul>
        <div className="repeat-consent__actions">
          <Button size="small" variant="secondary" onClick={withdraw}>
            {REPEAT_CONSENT_COPY.withdrawLabel}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      className="repeat-consent repeat-consent--withdrawn"
      data-testid="repeat-consent-withdrawn"
      data-workflow-kind={workflowKey}
      role="status"
    >
      <p className="repeat-consent__body">
        {REPEAT_CONSENT_COPY.withdrawnNotice}
      </p>
    </div>
  );
}
