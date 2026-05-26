"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type LivestreamSession, type LivestreamsResponse, ApiError } from "@/lib/api-client";
import { formatVND, formatNumber, formatDateTime } from "@/lib/format";
import { NavBar } from "./NavBar";

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
    <div className="min-h-screen pb-20">
      <header className="sticky top-0 z-10 border-b bg-white px-4 py-3">
        <div className="mx-auto max-w-lg">
          <h1 className="text-lg font-bold">Livestream</h1>
        </div>
      </header>

      <main className="mx-auto max-w-lg px-4 pt-4">
        {error && (
          <p role="alert" className="mb-4 text-sm text-red-600">
            {error}
          </p>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
          </div>
        ) : sessions.length === 0 ? (
          <div className="py-12 text-center" data-testid="livestreams-empty">
            <p className="text-lg text-gray-400">Chưa có phiên livestream nào</p>
            <p className="mt-1 text-sm text-gray-300">
              Dữ liệu sẽ hiển thị khi có phiên từ TikTok Shop
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="livestreams-list">
            <p className="text-xs text-gray-500">
              {formatNumber(sessions.length)} phiên
            </p>
            {sessions.map((session) => (
              <LivestreamCard key={session.id} session={session} />
            ))}
          </div>
        )}
      </main>

      <NavBar />
    </div>
  );
}

function LivestreamCard({ session }: { session: LivestreamSession }) {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm" data-testid="livestream-card">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{session.title}</p>
          <p className="mt-0.5 text-xs text-gray-500">
            {formatDateTime(session.started_at)} • {session.duration_minutes} phút
          </p>
        </div>
        <GradeBadge grade={session.performance_grade} />
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 border-t pt-3">
        <MetricCell label="Người xem" value={formatNumber(session.viewers_peak)} />
        <MetricCell label="GMV" value={formatVND(session.gmv)} />
        <MetricCell label="Đơn hàng" value={String(session.orders_count)} />
      </div>
    </div>
  );
}

function GradeBadge({ grade }: { grade: number }) {
  let colorClass: string;
  if (grade >= 70) {
    colorClass = "bg-green-50 text-green-700";
  } else if (grade >= 40) {
    colorClass = "bg-yellow-50 text-yellow-700";
  } else {
    colorClass = "bg-red-50 text-red-700";
  }

  return (
    <span
      className={`inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-xs font-bold ${colorClass}`}
      data-testid="performance-grade"
    >
      {grade}
    </span>
  );
}

function MetricCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-center">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-0.5 text-xs font-semibold">{value}</p>
    </div>
  );
}
