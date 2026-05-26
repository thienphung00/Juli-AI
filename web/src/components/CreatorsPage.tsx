"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Creator, type CreatorsResponse, ApiError } from "@/lib/api-client";
import { formatVND, formatNumber } from "@/lib/format";
import { NavBar } from "./NavBar";

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
    <div className="min-h-screen pb-20">
      <header className="sticky top-0 z-10 border-b bg-white px-4 py-3">
        <div className="mx-auto max-w-lg">
          <h1 className="text-lg font-bold">Nhà sáng tạo</h1>
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
        ) : creators.length === 0 ? (
          <div className="py-12 text-center" data-testid="creators-empty">
            <p className="text-lg text-gray-400">Chưa có nhà sáng tạo nào</p>
            <p className="mt-1 text-sm text-gray-300">
              Dữ liệu sẽ hiển thị khi có thông tin từ TikTok Shop
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="creators-list">
            <p className="text-xs text-gray-500">
              {formatNumber(creators.length)} nhà sáng tạo
            </p>
            {creators.map((creator) => (
              <CreatorCard key={creator.id} creator={creator} />
            ))}
          </div>
        )}
      </main>

      <NavBar />
    </div>
  );
}

function CreatorCard({ creator }: { creator: Creator }) {
  const commissionPercent = Math.round(creator.commission_rate * 100);

  return (
    <div className="rounded-xl bg-white p-4 shadow-sm" data-testid="creator-card">
      <div className="flex items-center gap-3">
        <Avatar name={creator.name} url={creator.avatar_url} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{creator.name}</p>
          <p className="mt-0.5 text-xs text-gray-500">
            {creator.sessions_count} phiên livestream
          </p>
        </div>
        <EfficiencyBadge score={creator.efficiency_score} />
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 border-t pt-3">
        <div className="text-center">
          <p className="text-xs text-gray-500">GMV</p>
          <p className="mt-0.5 text-xs font-semibold">{formatVND(creator.total_gmv)}</p>
        </div>
        <div className="text-center">
          <p className="text-xs text-gray-500">Hoa hồng</p>
          <p className="mt-0.5 text-xs font-semibold">{commissionPercent}%</p>
        </div>
        <div className="text-center">
          <p className="text-xs text-gray-500">Đã trả</p>
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
    <span className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-100 text-sm font-medium text-primary-700">
      {initials}
    </span>
  );
}

function EfficiencyBadge({ score }: { score: number }) {
  let colorClass: string;
  if (score >= 70) {
    colorClass = "bg-green-50 text-green-700";
  } else if (score >= 40) {
    colorClass = "bg-yellow-50 text-yellow-700";
  } else {
    colorClass = "bg-red-50 text-red-700";
  }

  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-bold ${colorClass}`}
      data-testid="efficiency-score"
    >
      {score}
    </span>
  );
}
