"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type LivestreamSession, type LivestreamsResponse, ApiError } from "@/lib/api-client";
import { formatVND, formatNumber, formatDateTime } from "@/lib/format";
import { AuthenticatedShell } from "./AuthenticatedShell";

export function LivestreamsPage() {
  const [sessions, setSessions] = useState<LivestreamSession[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data: LivestreamsResponse = await api.livestreams.list();
      setSessions(data.sessions);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setSessions([]);
      } else {
        setError("Không thể tải phiên livestream. Vui lòng thử lại.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  return (
    <AuthenticatedShell title="Trực tiếp">
      <div className="mb-3">
        <span className="badge-live">LIVE</span>
      </div>
        {error && (
          <p role="alert" className="mb-4 rounded-xl p-3 text-sm" style={{ background: "#ef444420", color: "#ef4444" }}>
            {error}
          </p>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <span className="spinner" />
          </div>
        ) : sessions.length === 0 ? (
          <div className="py-12 text-center" data-testid="livestreams-empty">
            <p className="text-lg font-medium" style={{ color: "var(--muted-foreground)" }}>Chưa có phiên livestream nào</p>
            <p className="mt-1 text-sm" style={{ color: "var(--muted-foreground)", opacity: 0.6 }}>
              Dữ liệu sẽ hiển thị khi có phiên từ TikTok Shop
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="livestreams-list">
            <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
              {formatNumber(sessions.length)} phiên
            </p>
            {sessions.map((session) => (
              <LivestreamCard key={session.id} session={session} />
            ))}
          </div>
        )}
    </AuthenticatedShell>
  );
}

function LivestreamCard({ session }: { session: LivestreamSession }) {
  return (
    <div className="card p-4" data-testid="livestream-card">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{session.title}</p>
          <p className="mt-0.5 text-xs" style={{ color: "var(--muted-foreground)" }}>
            {formatDateTime(session.started_at)} • {session.duration_minutes} phút
          </p>
        </div>
        <GradeBadge grade={session.performance_grade} />
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 pt-3" style={{ borderTop: "1px solid var(--border)" }}>
        <MetricCell label="Người xem" value={formatNumber(session.viewers_peak)} />
        <MetricCell label="GMV" value={formatVND(session.gmv)} />
        <MetricCell label="Đơn hàng" value={String(session.orders_count)} />
      </div>
    </div>
  );
}

function GradeBadge({ grade }: { grade: number }) {
  // className colour words are matched by tests (toMatch(/green|yellow|red/))
  const colorClass =
    grade >= 70 ? "grade-green" : grade >= 40 ? "grade-yellow" : "grade-red";
  const style =
    grade >= 70
      ? { background: "#10b98120", color: "#10b981" }
      : grade >= 40
      ? { background: "#f59e0b20", color: "#f59e0b" }
      : { background: "#ef444420", color: "#ef4444" };

  return (
    <span
      className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold ${colorClass}`}
      style={style}
      data-testid="performance-grade"
    >
      {grade}
    </span>
  );
}

function MetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-center">
      <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>{label}</p>
      <p className="mt-0.5 text-xs font-semibold">{value}</p>
    </div>
  );
}
