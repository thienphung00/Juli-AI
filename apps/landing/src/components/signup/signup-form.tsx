"use client";

import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore, type FormEvent } from "react";

import { buttonClassName } from "../ui/button";

import {
  FIELDS,
  LABELS,
  NOTICES,
  ROLE_OPTIONS,
  SIGNUP_DONE_FLAG,
  SIGNUP_SUBMIT_PATH,
  SIGNUP_THANKS_PATH,
} from "./signup-content";
import styles from "./signup.module.css";
import {
  FIELD_ORDER,
  PHONE_PATTERN,
  validateSignup,
  type SignupErrors,
  type SignupValues,
} from "./validate";

/** utm_* from the URL and the referrer, read once in the browser. */
const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"] as const;

function readSource(): Record<string, string> {
  const source: Record<string, string> = {};
  try {
    const params = new URLSearchParams(window.location.search);
    for (const key of UTM_KEYS) {
      const value = params.get(key);
      if (value) source[key] = value.slice(0, 300);
    }
    if (document.referrer) source.referrer = document.referrer.slice(0, 300);
  } catch {
    // no source is fine
  }
  return source;
}

function valuesOf(form: HTMLFormElement): SignupValues {
  const data = new FormData(form);
  const text = (name: string) => String(data.get(name) ?? "");
  return {
    full_name: text(FIELDS.fullName),
    phone: text(FIELDS.phone),
    email: text(FIELDS.email),
    shop: text(FIELDS.shop),
    role: text(FIELDS.role),
    note: text(FIELDS.note),
    consent: data.get(FIELDS.consent) !== null,
    website: text(FIELDS.honeypot),
  };
}

type Notice = keyof typeof NOTICES | null;

const subscribeNothing = () => () => undefined;

interface SignupFormProps {
  /** Test seam: where to go on success (default: a full navigation). */
  readonly onDone?: (path: string) => void;
  readonly fetchImpl?: typeof fetch;
}

/**
 * The trial sign-up form. Without JavaScript it is a plain `POST` to
 * {@link SIGNUP_SUBMIT_PATH} (browser constraint validation, then a 303 to the
 * thank-you page or back to an `#anchor` notice). With JavaScript the same
 * route is called with `fetch`, errors appear inline next to each field and
 * focus moves to the first one.
 */
export function SignupForm({ onDone, fetchImpl }: SignupFormProps = {}) {
  const [errors, setErrors] = useState<SignupErrors>({});
  const [notice, setNotice] = useState<Notice>(null);
  const [pending, setPending] = useState(false);
  // false in the server HTML (browser validation for no-JS), true once hydrated.
  const enhanced = useSyncExternalStore(subscribeNothing, () => true, () => false);
  const formRef = useRef<HTMLFormElement>(null);
  const noticeRef = useRef<HTMLParagraphElement>(null);

  function focusFirst(found: SignupErrors) {
    const first = FIELD_ORDER.find((name) => found[name]);
    if (!first || !formRef.current) return;
    const target = formRef.current.querySelector<HTMLElement>(`[name="${first}"]`);
    target?.focus();
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const values = valuesOf(form);
    const found = validateSignup(values);
    setErrors(found);
    setNotice(null);
    if (Object.keys(found).length > 0) {
      focusFirst(found);
      return;
    }
    setPending(true);
    try {
      const response = await (fetchImpl ?? fetch)(SIGNUP_SUBMIT_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ ...values, source: readSource() }),
      });
      if (response.ok) {
        try {
          window.sessionStorage.setItem(SIGNUP_DONE_FLAG, "1");
        } catch {
          // no conversion event then; the sign-up itself is stored
        }
        (onDone ?? ((path: string) => window.location.assign(path)))(SIGNUP_THANKS_PATH);
        return;
      }
      if (response.status === 422) {
        const body = (await response.json().catch(() => null)) as { errors?: SignupErrors } | null;
        const serverErrors = body?.errors ?? {};
        setErrors(serverErrors);
        setNotice("invalid");
        focusFirst(serverErrors);
      } else {
        setNotice(response.status === 429 ? "rateLimited" : "failed");
      }
    } catch {
      setNotice("failed");
    }
    setPending(false);
  }

  useEffect(() => {
    if (notice) noticeRef.current?.focus();
  }, [notice]);

  const describedBy = (name: keyof SignupErrors, hint?: string) =>
    [hint, errors[name] ? `${name}-error` : null].filter(Boolean).join(" ") || undefined;

  const fieldError = (name: keyof SignupErrors) =>
    errors[name] ? (
      <p className={styles.error} id={`${name}-error`}>
        {errors[name]}
      </p>
    ) : null;

  return (
    <form
      action={SIGNUP_SUBMIT_PATH}
      aria-describedby="signup-required-note"
      className={styles.form}
      data-testid="signup-form"
      method="post"
      noValidate={enhanced}
      onSubmit={onSubmit}
      ref={formRef}
    >
      {/* No-JS answers: the route redirects back to /dang-ky#<id>; :target shows it. */}
      {Object.values(NOTICES).map((item) => (
        <p className={styles.targetNotice} id={item.id} key={item.id} role="alert">
          {item.text}
        </p>
      ))}
      {notice ? (
        <p className={styles.notice} data-testid="signup-notice" ref={noticeRef} role="alert" tabIndex={-1}>
          {NOTICES[notice].text}
        </p>
      ) : null}

      <p className={styles.required} id="signup-required-note">
        Các ô có dấu <span aria-hidden="true">*</span> là bắt buộc.
      </p>

      <div className={styles.field}>
        <label htmlFor="signup-name">
          {LABELS.fullName} <span aria-hidden="true">*</span>
        </label>
        <input
          aria-describedby={describedBy("full_name")}
          aria-invalid={errors.full_name ? true : undefined}
          autoComplete="name"
          id="signup-name"
          maxLength={120}
          minLength={2}
          name={FIELDS.fullName}
          required
          type="text"
        />
        {fieldError("full_name")}
      </div>

      <div className={`${styles.field} ${styles.half}`}>
        <label htmlFor="signup-phone">
          {LABELS.phone} <span aria-hidden="true">*</span>
        </label>
        <input
          aria-describedby={describedBy("phone", "signup-phone-hint")}
          aria-invalid={errors.phone ? true : undefined}
          autoComplete="tel"
          id="signup-phone"
          inputMode="tel"
          maxLength={20}
          name={FIELDS.phone}
          pattern={PHONE_PATTERN}
          required
          type="tel"
        />
        <p className={styles.hint} id="signup-phone-hint">
          {LABELS.phoneHint}
        </p>
        {fieldError("phone")}
      </div>

      <div className={`${styles.field} ${styles.half}`}>
        <label htmlFor="signup-email">
          {LABELS.email} <span aria-hidden="true">*</span>
        </label>
        <input
          aria-describedby={describedBy("email")}
          aria-invalid={errors.email ? true : undefined}
          autoComplete="email"
          id="signup-email"
          inputMode="email"
          maxLength={254}
          name={FIELDS.email}
          required
          type="email"
        />
        {fieldError("email")}
      </div>

      <div className={styles.field}>
        <label htmlFor="signup-shop">
          {LABELS.shop} <span aria-hidden="true">*</span>
        </label>
        <input
          aria-describedby={describedBy("shop", "signup-shop-hint")}
          aria-invalid={errors.shop ? true : undefined}
          autoComplete="organization"
          id="signup-shop"
          maxLength={300}
          minLength={2}
          name={FIELDS.shop}
          required
          type="text"
        />
        <p className={styles.hint} id="signup-shop-hint">
          {LABELS.shopHint}
        </p>
        {fieldError("shop")}
      </div>

      <fieldset
        aria-describedby={errors.role ? "role-error" : undefined}
        aria-invalid={errors.role ? true : undefined}
        className={styles.fieldset}
      >
        <legend>
          {LABELS.role} <span aria-hidden="true">*</span>
        </legend>
        <div className={styles.choices}>
          {ROLE_OPTIONS.map((option, i) => (
            <label className={styles.choice} key={option.value}>
              <input name={FIELDS.role} required={i === 0} type="radio" value={option.value} />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
        {fieldError("role")}
      </fieldset>

      <div className={styles.field}>
        <label htmlFor="signup-note">{LABELS.note}</label>
        <textarea
          aria-describedby={describedBy("note", "signup-note-hint")}
          aria-invalid={errors.note ? true : undefined}
          id="signup-note"
          maxLength={1000}
          name={FIELDS.note}
          rows={3}
        />
        <p className={styles.hint} id="signup-note-hint">
          {LABELS.noteHint}
        </p>
        {fieldError("note")}
      </div>

      {/* Honeypot: hidden from people and assistive tech; bots fill it. */}
      <div aria-hidden="true" className={styles.honeypot}>
        <label htmlFor="signup-website">Website</label>
        <input autoComplete="off" id="signup-website" name={FIELDS.honeypot} tabIndex={-1} type="text" />
      </div>

      <div className={styles.consent}>
        <input
          aria-describedby={errors.consent ? "consent-error" : undefined}
          aria-invalid={errors.consent ? true : undefined}
          id="signup-consent"
          name={FIELDS.consent}
          required
          type="checkbox"
          value="true"
        />
        <label htmlFor="signup-consent">
          Tôi đồng ý với <Link href="/terms">Điều khoản dịch vụ</Link> và{" "}
          <Link href="/privacy#dang-ky-dung-thu">Chính sách bảo mật</Link> của Juli AI, và đồng ý để đội ngũ Juli
          liên hệ qua điện thoại, Zalo hoặc email về việc dùng thử.{" "}
          <span aria-hidden="true">*</span>
        </label>
      </div>
      {fieldError("consent")}

      <button
        aria-disabled={pending || undefined}
        className={buttonClassName({ className: styles.submit })}
        data-testid="signup-submit"
        type="submit"
      >
        {pending ? LABELS.submitting : LABELS.submit}
      </button>
    </form>
  );
}
