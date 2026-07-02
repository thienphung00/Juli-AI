"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { usePostAuthRedirect } from "@/lib/use-mode-guard";

export function LoginForm() {
  const { loginAsReviewer, isAuthenticated, isLoading } = useAuth();
  usePostAuthRedirect(isAuthenticated, isLoading);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleContinue = async () => {
    setError(null);
    setLoading(true);
    try {
      await loginAsReviewer();
    } catch {
      setError("Không thể đăng nhập. Vui lòng thử lại.");
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
          <p className="mt-2 text-xs" style={{ color: "var(--muted-foreground)" }}>
            Đăng nhập demo — không cần mã xác thực.
          </p>
        </div>

        <div className="card p-6 space-y-4">
          <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
            Nhấn tiếp tục để vào ứng dụng với dữ liệu demo.
          </p>

          {error && (
            <p
              role="alert"
              className="rounded-xl px-3 py-2 text-sm"
              style={{
                background: "color-mix(in srgb, var(--destructive) 12%, transparent)",
                color: "var(--destructive)",
              }}
            >
              {error}
            </p>
          )}

          <button
            type="button"
            onClick={handleContinue}
            disabled={loading}
            className="btn-primary w-full py-3"
          >
            {loading ? "Đang vào..." : "Tiếp tục vào ứng dụng"}
          </button>
        </div>
      </div>
    </div>
  );
}
