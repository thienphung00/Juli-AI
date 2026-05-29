"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Creator, type CreatorsResponse, ApiError } from "@/lib/api-client";
import { formatVND, formatNumber } from "@/lib/format";
import { AuthenticatedShell } from "./AuthenticatedShell";

export function CreatorsPage() {
  const [creators, setCreators] = useState<Creator[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadCreators = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data: CreatorsResponse = await api.creators.list();
      setCreators(data.creators);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setCreators([]);
      } else {
        setError("Không thể tải danh sách nhà sáng tạo. Vui lòng thử lại.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCreators();
  }, [loadCreators]);

  return (
    <AuthenticatedShell title="Creators">
        {error && (
          <p role="alert" className="mb-4 rounded-xl p-3 text-sm" style={{ background: "#ef444420", color: "#ef4444" }}>
            {error}
          </p>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <span className="spinner" />
          </div>
        ) : creators.length === 0 ? (
          <div className="py-12 text-center" data-testid="creators-empty">
            <p className="text-lg font-medium" style={{ color: "var(--muted-foreground)" }}>Chưa có nhà sáng tạo nào</p>
            <p className="mt-1 text-sm" style={{ color: "var(--muted-foreground)", opacity: 0.6 }}>
              Dữ liệu sẽ hiển thị khi có thông tin từ TikTok Shop
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="creators-list">
            <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
              {formatNumber(creators.length)} nhà sáng tạo
            </p>
            {creators.map((creator) => (
              <CreatorCard key={creator.id} creator={creator} />
            ))}
          </div>
        )}
    </AuthenticatedShell>
  );
}

function CreatorCard({ creator }: { creator: Creator }) {
  const commissionPercent = Math.round(creator.commission_rate * 100);

  return (
    <div className="card p-4" data-testid="creator-card">
      <div className="flex items-center gap-3">
        <Avatar name={creator.name} url={creator.avatar_url} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{creator.name}</p>
          <p className="mt-0.5 text-xs" style={{ color: "var(--muted-foreground)" }}>
            {creator.sessions_count} phiên livestream
          </p>
        </div>
        <EfficiencyBadge score={creator.efficiency_score} />
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 pt-3" style={{ borderTop: "1px solid var(--border)" }}>
        <div className="text-center">
          <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>GMV</p>
          <p className="mt-0.5 text-xs font-semibold">{formatVND(creator.total_gmv)}</p>
        </div>
        <div className="text-center">
          <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>Hoa hồng</p>
          <p className="mt-0.5 text-xs font-semibold">{commissionPercent}%</p>
        </div>
        <div className="text-center">
          <p className="text-[11px]" style={{ color: "var(--muted-foreground)" }}>Đã trả</p>
          <p className="mt-0.5 text-xs font-semibold">{formatVND(creator.commission_paid)}</p>
        </div>
      </div>
    </div>
  );
}

function Avatar({ name, url }: { name: string; url: string | null }) {
  if (url) {
    return (
      <img
        src={url}
        alt={name}
        className="h-10 w-10 rounded-full object-cover"
      />
    );
  }

  const initials = name
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <span
      className="flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold"
      style={{ background: "#ff006e20", color: "var(--primary)" }}
    >
      {initials}
    </span>
  );
}

function EfficiencyBadge({ score }: { score: number }) {
  const style =
    score >= 70
      ? { bg: "#10b98120", color: "#10b981" }
      : score >= 40
      ? { bg: "#f59e0b20", color: "#f59e0b" }
      : { bg: "#ef444420", color: "#ef4444" };

  return (
    <span
      className="badge font-bold"
      style={{ background: style.bg, color: style.color }}
      data-testid="efficiency-score"
    >
      {score}
    </span>
  );
}
