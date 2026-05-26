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
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">Juli</h1>
          <p className="mt-2 text-sm text-gray-600">
            Quản lý TikTok Shop thông minh
          </p>
        </div>

        {step === "phone" ? (
          <form onSubmit={handleSendOtp} className="space-y-4">
            <div>
              <label
                htmlFor="phone"
                className="block text-sm font-medium text-gray-700"
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
                className="mt-1 block w-full rounded-lg border border-gray-300 px-4 py-3 text-lg focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                required
                autoFocus
              />
            </div>

            {error && (
              <p role="alert" className="text-sm text-red-600">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !phone}
              className="w-full rounded-lg bg-primary-600 px-4 py-3 text-base font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
            >
              {loading ? "Đang gửi..." : "Nhận mã OTP"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleVerifyOtp} className="space-y-4">
            <div>
              <label
                htmlFor="otp"
                className="block text-sm font-medium text-gray-700"
              >
                Nhập mã OTP
              </label>
              <p className="text-xs text-gray-500">
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
                className="mt-2 block w-full rounded-lg border border-gray-300 px-4 py-3 text-center text-2xl tracking-widest focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                required
                autoFocus
              />
            </div>

            {error && (
              <p role="alert" className="text-sm text-red-600">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || otp.length < 6}
              className="w-full rounded-lg bg-primary-600 px-4 py-3 text-base font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
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
              className="w-full text-sm text-gray-500 hover:text-gray-700"
            >
              ← Đổi số điện thoại
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
