"use client";

import {
  useId,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { Button } from "./button";

export interface FormProps extends ComponentPropsWithoutRef<"form"> {
  children: ReactNode;
}

export function Form({ className, children, ...rest }: FormProps) {
  const classNames = ["juli-form", className].filter(Boolean).join(" ");

  return (
    <form className={classNames} {...rest}>
      {children}
    </form>
  );
}

export interface FormFieldProps {
  children: ReactNode;
  className?: string;
  "data-testid"?: string;
}

export function FormField({
  className,
  children,
  "data-testid": dataTestId,
}: FormFieldProps) {
  const classNames = ["juli-form__field", className].filter(Boolean).join(" ");

  return (
    <div className={classNames} data-testid={dataTestId}>
      {children}
    </div>
  );
}

export interface FormLabelProps extends ComponentPropsWithoutRef<"label"> {
  children: ReactNode;
  required?: boolean;
}

export function FormLabel({
  className,
  children,
  required,
  ...rest
}: FormLabelProps) {
  const classNames = ["juli-form__label", className].filter(Boolean).join(" ");

  return (
    <label className={classNames} {...rest}>
      {children}
      {required ? (
        <span aria-hidden="true" className="juli-form__required">
          {" *"}
        </span>
      ) : null}
    </label>
  );
}

export interface FormInputProps extends ComponentPropsWithoutRef<"input"> {
  error?: boolean;
}

export function FormInput({
  className,
  error,
  ...rest
}: FormInputProps) {
  const classNames = [
    "juli-form__input",
    error ? "juli-form__input--error" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <input
      aria-invalid={error || undefined}
      className={classNames}
      {...rest}
    />
  );
}

export interface FormErrorProps extends ComponentPropsWithoutRef<"p"> {
  children: ReactNode;
  id: string;
}

export function FormError({ className, children, id, ...rest }: FormErrorProps) {
  const classNames = ["juli-form__error", className].filter(Boolean).join(" ");

  return (
    <p className={classNames} id={id} role="alert" {...rest}>
      {children}
    </p>
  );
}

export interface TextFieldProps
  extends Omit<FormInputProps, "id" | "aria-describedby"> {
  errorMessage?: string;
  helperText?: string;
  id?: string;
  label: string;
  required?: boolean;
}

export function TextField({
  errorMessage,
  helperText,
  id: idProp,
  label,
  required,
  error,
  ...inputProps
}: TextFieldProps) {
  const generatedId = useId();
  const inputId = idProp ?? generatedId;
  const errorId = `${inputId}-error`;
  const helperId = `${inputId}-helper`;
  const describedBy = [
    errorMessage ? errorId : null,
    helperText ? helperId : null,
  ]
    .filter(Boolean)
    .join(" ");
  const hasError = Boolean(errorMessage) || error;

  return (
    <FormField data-testid={`field-${inputId}`}>
      <FormLabel htmlFor={inputId} required={required}>
        {label}
      </FormLabel>
      <FormInput
        aria-describedby={describedBy || undefined}
        error={hasError}
        id={inputId}
        required={required}
        {...inputProps}
      />
      {errorMessage ? <FormError id={errorId}>{errorMessage}</FormError> : null}
      {helperText && !errorMessage ? (
        <p className="juli-form__helper" id={helperId}>
          {helperText}
        </p>
      ) : null}
    </FormField>
  );
}

export interface PasswordFieldProps
  extends Omit<TextFieldProps, "type" | "label"> {
  label?: string;
}

export function PasswordField({
  errorMessage,
  helperText,
  id: idProp,
  label = "Mật khẩu",
  required,
  error,
  ...inputProps
}: PasswordFieldProps) {
  const generatedId = useId();
  const inputId = idProp ?? generatedId;
  const errorId = `${inputId}-error`;
  const helperId = `${inputId}-helper`;
  const [visible, setVisible] = useState(false);
  const describedBy = [
    errorMessage ? errorId : null,
    helperText ? helperId : null,
  ]
    .filter(Boolean)
    .join(" ");
  const hasError = Boolean(errorMessage) || error;

  return (
    <FormField data-testid={`field-${inputId}`}>
      <FormLabel htmlFor={inputId} required={required}>
        {label}
      </FormLabel>
      <div className="juli-form__password">
        <FormInput
          aria-describedby={describedBy || undefined}
          error={hasError}
          id={inputId}
          required={required}
          type={visible ? "text" : "password"}
          {...inputProps}
        />
        <button
          aria-label={visible ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
          className="juli-form__password-toggle"
          data-testid={`password-toggle-${inputId}`}
          onClick={() => setVisible((current) => !current)}
          type="button"
        >
          {visible ? "Ẩn" : "Hiện"}
        </button>
      </div>
      {errorMessage ? <FormError id={errorId}>{errorMessage}</FormError> : null}
      {helperText && !errorMessage ? (
        <p className="juli-form__helper" id={helperId}>
          {helperText}
        </p>
      ) : null}
    </FormField>
  );
}

export interface OtpFieldProps {
  errorMessage?: string;
  id?: string;
  label?: string;
  length?: number;
  onChange?: (value: string) => void;
  onComplete?: (value: string) => void;
  value?: string;
}

export function OtpField({
  errorMessage,
  id: idProp,
  label = "Mã OTP",
  length = 6,
  onChange,
  onComplete,
  value = "",
}: OtpFieldProps) {
  const generatedId = useId();
  const fieldId = idProp ?? generatedId;
  const errorId = `${fieldId}-error`;
  const inputRefs = useRef<Array<HTMLInputElement | null>>([]);
  const digits = value.padEnd(length, " ").slice(0, length).split("");
  const hasError = Boolean(errorMessage);

  const updateValue = (nextDigits: string[]) => {
    const nextValue = nextDigits.join("").trim();
    onChange?.(nextValue);

    if (nextValue.length === length && nextDigits.every((digit) => digit.trim())) {
      onComplete?.(nextValue);
    }
  };

  const handleChange = (index: number, digit: string) => {
    const sanitized = digit.replace(/\D/g, "").slice(-1);
    const nextDigits = [...digits.map((entry) => entry.trim())];
    nextDigits[index] = sanitized;
    updateValue(nextDigits);

    if (sanitized && index < length - 1) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (
    index: number,
    event: KeyboardEvent<HTMLInputElement>,
  ) => {
    const trimmedDigits = digits.map((entry) => entry.trim());

    if (event.key === "Backspace" && !trimmedDigits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }

    if (event.key === "ArrowLeft" && index > 0) {
      event.preventDefault();
      inputRefs.current[index - 1]?.focus();
    }

    if (event.key === "ArrowRight" && index < length - 1) {
      event.preventDefault();
      inputRefs.current[index + 1]?.focus();
    }
  };

  return (
    <FormField data-testid={`field-${fieldId}`}>
      <FormLabel id={`${fieldId}-label`}>{label}</FormLabel>
      <div
        aria-describedby={errorMessage ? errorId : undefined}
        aria-labelledby={`${fieldId}-label`}
        className={[
          "juli-form__otp",
          hasError ? "juli-form__otp--error" : null,
        ]
          .filter(Boolean)
          .join(" ")}
        role="group"
      >
        {Array.from({ length }, (_, index) => (
          <input
            key={index}
            ref={(node) => {
              inputRefs.current[index] = node;
            }}
            aria-label={`${label} chữ số ${index + 1}`}
            autoComplete={index === 0 ? "one-time-code" : "off"}
            className="juli-form__otp-digit"
            data-testid={`otp-digit-${index}`}
            inputMode="numeric"
            maxLength={1}
            onChange={(event) => handleChange(index, event.target.value)}
            onKeyDown={(event) => handleKeyDown(index, event)}
            type="text"
            value={digits[index]?.trim() ?? ""}
          />
        ))}
      </div>
      {errorMessage ? (
        <FormError id={errorId}>{errorMessage}</FormError>
      ) : null}
    </FormField>
  );
}

export interface FormActionsProps {
  children: ReactNode;
  className?: string;
}

export function FormActions({ children, className }: FormActionsProps) {
  const classNames = ["juli-form__actions", className]
    .filter(Boolean)
    .join(" ");

  return <div className={classNames}>{children}</div>;
}

export interface FormSubmitProps extends ComponentPropsWithoutRef<typeof Button> {}

export function FormSubmit({
  children = "Lưu",
  ...rest
}: FormSubmitProps) {
  return (
    <Button type="submit" variant="primary" {...rest}>
      {children}
    </Button>
  );
}
