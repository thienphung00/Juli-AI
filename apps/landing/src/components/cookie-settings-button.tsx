"use client";

import { OPEN_CONSENT_EVENT } from "../lib/consent";

/** Footer control that reopens the consent banner so a choice can be changed. */
export function CookieSettingsButton() {
  return (
    <button
      className="lp-footer__link lp-footer__button"
      onClick={() => window.dispatchEvent(new Event(OPEN_CONSENT_EVENT))}
      type="button"
    >
      Cài đặt cookie
    </button>
  );
}
