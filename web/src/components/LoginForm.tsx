"use client";

import { useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth-context";

type Step = "phone" | "otp";

export function LoginForm() {
  const { sendOtp, verifyOtp } = useAuth();
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
    } catch (err) {
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
    } catch (err) {
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
        {/* Logo */}
        <div className="text-center">
          <h1
            className="text-3xl font-bold"
            style={{ background: "linear-gradient(135deg, #ff006e 0%, #ff4d94 100%)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}
          >
            Juli
          </h1>
          <p className="mt-2 text-sm" style={{ color: "var(--muted-foreground)" }}>
            Quản lý TikTok Shop thông minh
          </p>
        </div>

        {/* Card */}
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
                  className="mt-2 block w-full rounded-xl px-4 py-3 text-lg focus:outline-none"
                  style={{
                    background: "var(--muted)",
                    border: "1px solid var(--border)",
                    color: "var(--foreground)",
                  }}
                  required
                  autoFocus
                />
              </div>

              {error && (
                <p role="alert" className="rounded-xl px-3 py-2 text-sm" style={{ background: "#ef444420", color: "#ef4444" }}>
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={loading || !phone}
                className="w-full rounded-xl px-4 py-3 text-base font-semibold text-white transition-opacity disabled:opacity-50"
                style={{ background: "linear-gradient(135deg, #ff006e 0%, #ff4d94 100%)" }}
              >
                {loading ? "Đang gửi..." : "Nhận mã OTP"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleVerifyOtp} className="space-y-4">
              <div>
                <label
                  htmlFor="otp"
                  className="block text-sm font-medium"
                  style={{ color: "var(--muted-foreground)" }}
                >
                  Nhập mã OTP
                </label>
                <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
                  Đã gửi đến {phone}
                </p>
                <input
                  id="otp"
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  maxLength={6}
                  placeholder="000000"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  className="mt-2 block w-full rounded-xl px-4 py-3 text-center text-2xl tracking-widest focus:outline-none"
                  style={{
                    background: "var(--muted)",
                    border: "1px solid var(--border)",
                    color: "var(--foreground)",
                  }}
                  required
                  autoFocus
                />
              </div>

              {error && (
                <p role="alert" className="rounded-xl px-3 py-2 text-sm" style={{ background: "#ef444420", color: "#ef4444" }}>
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={loading || otp.length < 6}
                className="w-full rounded-xl px-4 py-3 text-base font-semibold text-white transition-opacity disabled:opacity-50"
                style={{ background: "linear-gradient(135deg, #ff006e 0%, #ff4d94 100%)" }}
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
