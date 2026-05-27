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
    <div className="min-h-screen pb-24" style={{ background: "var(--background)" }}>
      <header
        className="sticky top-0 z-10 px-4 py-3"
        style={{ background: "var(--background)", borderBottom: "1px solid var(--border)" }}
      >
        <div className="mx-auto max-w-lg">
          <h1 className="text-lg font-bold">Tồn kho</h1>
        </div>
      </header>

      <main className="mx-auto max-w-lg px-4 pt-4">
        {error && (
          <p role="alert" className="mb-4 rounded-xl p-3 text-sm" style={{ background: "#ef444420", color: "#ef4444" }}>
            {error}
          </p>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <span className="spinner" />
          </div>
        ) : items.length === 0 ? (
          <div className="py-12 text-center" data-testid="inventory-empty">
            <p className="text-lg font-medium" style={{ color: "var(--muted-foreground)" }}>Chưa có dữ liệu tồn kho</p>
            <p className="mt-1 text-sm" style={{ color: "var(--muted-foreground)", opacity: 0.6 }}>
              Dữ liệu sẽ hiển thị khi đồng bộ từ TikTok Shop
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="inventory-list">
            <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
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
    <div className="card p-4" data-testid="inventory-card">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{item.product_name}</p>
          <p className="mt-0.5 text-xs" style={{ color: "var(--muted-foreground)" }}>{item.sku}</p>
        </div>
        <div className="text-right">
          <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>Tồn kho</p>
          <p className="text-sm font-semibold">{formatNumber(item.current_stock)}</p>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between pt-3" style={{ borderTop: "1px solid var(--border)" }}>
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
      className="badge"
      style={isCritical
        ? { background: "#ef444420", color: "#ef4444" }
        : { background: "#10b98120", color: "#10b981" }
      }
      data-testid={isCritical ? "depletion-critical" : "depletion-safe"}
    >
      {days} ngày
    </span>
  );
}

function ReorderBadge({ quantity }: { quantity: number }) {
  return (
    <span
      className="badge"
      style={{ background: "#f59e0b20", color: "#f59e0b" }}
      data-testid="reorder-badge"
    >
      Đặt thêm {formatNumber(quantity)}
    </span>
  );
}
