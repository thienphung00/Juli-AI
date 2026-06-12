"use client";

import { useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import { usePostAuthRedirect } from "@/lib/use-mode-guard";
import { isUiOnly } from "@/lib/ui-only";

type Step = "phone" | "otp";

const OTP_LENGTH = 6;

function OtpInput({
  value,
  onChange,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  disabled?: boolean;
}) {
  const inputsRef = useRef<(HTMLInputElement | null)[]>([]);
  const digits = value.padEnd(OTP_LENGTH, " ").split("").slice(0, OTP_LENGTH);

  const updateDigit = (index: number, char: string) => {
    const next = digits.map((d, i) => (i === index ? char : d === " " ? "" : d)).join("");
    onChange(next.replace(/\s/g, "").slice(0, OTP_LENGTH));
  };

  const handleChange = (index: number, inputValue: string) => {
    const digit = inputValue.replace(/\D/g, "").slice(-1);
    if (!digit) {
      updateDigit(index, "");
      return;
    }
    updateDigit(index, digit);
    if (index < OTP_LENGTH - 1) {
      inputsRef.current[index + 1]?.focus();
    }
  };

  const handleKeyDown = (index: number, event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Backspace" && !digits[index]?.trim() && index > 0) {
      inputsRef.current[index - 1]?.focus();
    }
  };

  const handlePaste = (event: React.ClipboardEvent) => {
    event.preventDefault();
    const pasted = event.clipboardData.getData("text").replace(/\D/g, "").slice(0, OTP_LENGTH);
    onChange(pasted);
    const focusIndex = Math.min(pasted.length, OTP_LENGTH - 1);
    inputsRef.current[focusIndex]?.focus();
  };

  return (
    <div
      className="mt-3 flex justify-center gap-2"
      data-testid="otp-segmented-input"
      role="group"
      aria-labelledby="otp-label"
      onPaste={handlePaste}
    >
      {digits.map((digit, index) => (
        <input
          key={index}
          ref={(el) => {
            inputsRef.current[index] = el;
          }}
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          maxLength={1}
          value={digit.trim()}
          disabled={disabled}
          autoFocus={index === 0}
          aria-label={`Chữ số OTP ${index + 1}`}
          className="h-12 w-10 rounded-xl text-center text-xl font-bold focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
          style={{
            background: "var(--muted)",
            border: "1px solid var(--border)",
            color: "var(--foreground)",
          }}
          onChange={(e) => handleChange(index, e.target.value)}
          onKeyDown={(e) => handleKeyDown(index, e)}
        />
      ))}
      <input type="hidden" id="otp" name="otp" value={value} readOnly />
    </div>
  );
}

export function LoginForm() {
  const { sendOtp, verifyOtp, isAuthenticated, isLoading } = useAuth();
  usePostAuthRedirect(isAuthenticated, isLoading);
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSendOtp = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await sendOtp(phone);
      setStep("otp");
    } catch {
      setError("Không thể gửi mã OTP. Vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyOtp = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await verifyOtp(phone, otp);
    } catch {
      setError("Mã OTP không đúng. Vui lòng thử lại.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="flex min-h-screen items-center justify-center px-4"
      style={{ background: "var(--background)" }}
    >
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="brand-wordmark brand-wordmark-lg">Juli</h1>
          <p className="mt-2 text-sm" style={{ color: "var(--muted-foreground)" }}>
            Quản lý TikTok Shop thông minh
          </p>
          {isUiOnly && (
            <p className="mt-2 text-xs" style={{ color: "var(--muted-foreground)" }}>
              Chế độ UI-only: nhập số bất kỳ, mã OTP 6 chữ số bất kỳ (không cần API).
            </p>
          )}
        </div>

        <div className="card p-6">
          {step === "phone" ? (
            <form onSubmit={handleSendOtp} className="space-y-4">
              <div>
                <label
                  htmlFor="phone"
                  className="block text-sm font-medium"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  Số điện thoại
                </label>
                <input
                  id="phone"
                  type="tel"
                  inputMode="numeric"
                  placeholder="+84 xxx xxx xxx"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className="field-input mt-2 block w-full rounded-xl px-4 py-3 text-lg focus-visible:ring-2 focus-visible:ring-[var(--primary)]"
                  required
                  autoFocus
                />
              </div>

              {error && (
                <p
                  role="alert"
                  className="rounded-xl px-3 py-2 text-sm"
                  style={{ background: "color-mix(in srgb, var(--destructive) 12%, transparent)", color: "var(--destructive)" }}
                >
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={loading || !phone}
                className="btn-primary w-full py-3"
              >
                {loading ? "Đang gửi..." : "Nhận mã OTP"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleVerifyOtp} className="space-y-4">
              <div>
                <label
                  id="otp-label"
                  className="block text-sm font-medium"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  Nhập mã OTP
                </label>
                <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
                  Đã gửi đến {phone}
                </p>
                <OtpInput value={otp} onChange={setOtp} disabled={loading} />
              </div>

              {error && (
                <p
                  role="alert"
                  className="rounded-xl px-3 py-2 text-sm"
                  style={{ background: "color-mix(in srgb, var(--destructive) 12%, transparent)", color: "var(--destructive)" }}
                >
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={loading || otp.length < OTP_LENGTH}
                className="btn-primary w-full py-3"
              >
                {loading ? "Đang xác thực..." : "Xác nhận"}
              </button>

              <button
                type="button"
                onClick={() => {
                  setStep("phone");
                  setOtp("");
                  setError(null);
                }}
                className="w-full text-sm transition-opacity hover:opacity-70"
                style={{ color: "var(--muted-foreground)" }}
              >
                ← Đổi số điện thoại
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
