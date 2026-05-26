"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type InventoryItem, type InventoryResponse, ApiError } from "@/lib/api-client";
import { formatNumber } from "@/lib/format";
import { NavBar } from "./NavBar";

const CRITICAL_DAYS_THRESHOLD = 7;

export function InventoryPage() {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadInventory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data: InventoryResponse = await api.inventory.list();
      setItems(data.items);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setItems([]);
      } else {
        setError("Không thể tải tồn kho. Vui lòng thử lại.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadInventory();
  }, [loadInventory]);

  return (
    <div className="min-h-screen pb-20">
      <header className="sticky top-0 z-10 border-b bg-white px-4 py-3">
        <div className="mx-auto max-w-lg">
          <h1 className="text-lg font-bold">Tồn kho</h1>
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
        ) : items.length === 0 ? (
          <div className="py-12 text-center" data-testid="inventory-empty">
            <p className="text-lg text-gray-400">Chưa có dữ liệu tồn kho</p>
            <p className="mt-1 text-sm text-gray-300">
              Dữ liệu sẽ hiển thị khi đồng bộ từ TikTok Shop
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="inventory-list">
            <p className="text-xs text-gray-500">
              {formatNumber(items.length)} SKU
            </p>
            {items.map((item) => (
              <InventoryCard key={item.id} item={item} />
            ))}
          </div>
        )}
      </main>

      <NavBar />
    </div>
  );
}

function InventoryCard({ item }: { item: InventoryItem }) {
  const isCritical = item.days_until_depletion <= CRITICAL_DAYS_THRESHOLD;

  return (
    <div className="rounded-xl bg-white p-4 shadow-sm" data-testid="inventory-card">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{item.product_name}</p>
          <p className="mt-0.5 text-xs text-gray-500">{item.sku}</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-gray-500">Tồn kho</p>
          <p className="text-sm font-semibold">{formatNumber(item.current_stock)}</p>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between border-t pt-3">
        <DepletionBadge days={item.days_until_depletion} isCritical={isCritical} />
        {item.reorder_recommended && (
          <ReorderBadge quantity={item.reorder_quantity} />
        )}
      </div>
    </div>
  );
}

function DepletionBadge({ days, isCritical }: { days: number; isCritical: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-1 text-xs font-medium ${
        isCritical
          ? "bg-red-50 text-red-700"
          : "bg-green-50 text-green-700"
      }`}
      data-testid={isCritical ? "depletion-critical" : "depletion-safe"}
    >
      {days} ngày
    </span>
  );
}

function ReorderBadge({ quantity }: { quantity: number }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-orange-50 px-2 py-1 text-xs font-medium text-orange-700"
      data-testid="reorder-badge"
    >
      Đặt thêm {formatNumber(quantity)}
    </span>
  );
}
