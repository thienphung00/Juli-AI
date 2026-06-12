"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Order, type OrdersResponse, ApiError } from "@/lib/api-client";
import { formatVND, formatDateTime } from "@/lib/format";
import { AuthenticatedShell } from "./AuthenticatedShell";

const STATUS_OPTIONS = [
  { value: "", label: "Tất cả" },
  { value: "AWAITING_SHIPMENT", label: "Chờ giao" },
  { value: "AWAITING_COLLECTION", label: "Chờ lấy hàng" },
  { value: "IN_TRANSIT", label: "Đang giao" },
  { value: "DELIVERED", label: "Đã giao" },
  { value: "CANCELLED", label: "Đã huỷ" },
];

export function OrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const loadOrders = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = {};
      if (statusFilter) params.status = statusFilter;
      if (startDate) params.start_date = startDate;
      if (endDate) params.end_date = endDate;

      const data: OrdersResponse = await api.orders.list(params);
      setOrders(data.orders);
      setTotal(data.total);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setOrders([]);
        setTotal(0);
      } else {
        setError("Không thể tải đơn hàng. Vui lòng thử lại.");
      }
    } finally {
      setLoading(false);
    }
  }, [statusFilter, startDate, endDate]);

  useEffect(() => {
    loadOrders();
  }, [loadOrders]);

  const handleConfirmShipment = async (orderId: string) => {
    setConfirmingId(orderId);
    try {
      await api.orders.confirmShipment(orderId);
      await loadOrders();
    } catch {
      setError("Xác nhận giao hàng thất bại.");
    } finally {
      setConfirmingId(null);
    }
  };

  return (
    <AuthenticatedShell title="Đơn hàng">
        {/* Filters */}
        <div className="space-y-3 pb-4" data-testid="order-filters">
          <select
            aria-label="Lọc theo trạng thái"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="w-full rounded-xl px-3 py-2.5 text-sm focus:outline-none"
            style={{ background: "var(--muted)", border: "1px solid var(--border)", color: "var(--foreground)" }}
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value} style={{ background: "var(--card)" }}>
                {opt.label}
              </option>
            ))}
          </select>

          <div className="flex gap-2">
            <input
              type="date"
              aria-label="Từ ngày"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="flex-1 rounded-xl px-3 py-2.5 text-sm focus:outline-none"
              style={{ background: "var(--muted)", border: "1px solid var(--border)", color: "var(--foreground)" }}
            />
            <input
              type="date"
              aria-label="Đến ngày"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="flex-1 rounded-xl px-3 py-2.5 text-sm focus:outline-none"
              style={{ background: "var(--muted)", border: "1px solid var(--border)", color: "var(--foreground)" }}
            />
          </div>
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
        ) : orders.length === 0 ? (
          <div className="py-12 text-center" data-testid="orders-empty">
            <p className="text-lg font-medium" style={{ color: "var(--muted-foreground)" }}>Chưa có đơn hàng nào</p>
            <p className="mt-1 text-sm" style={{ color: "var(--muted-foreground)", opacity: 0.6 }}>
              Đơn hàng sẽ hiển thị khi có dữ liệu từ TikTok Shop
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="orders-list">
            <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
              {total} đơn hàng
            </p>
            {orders.map((order) => (
              <OrderCard
                key={order.id}
                order={order}
                confirming={confirmingId === order.id}
                onConfirmShipment={handleConfirmShipment}
              />
            ))}
          </div>
        )}
    </AuthenticatedShell>
  );
}

function OrderCard({
  order,
  confirming,
  onConfirmShipment,
}: {
  order: Order;
  confirming: boolean;
  onConfirmShipment: (id: string) => void;
}) {
  const canConfirm = order.status === "AWAITING_SHIPMENT";

  return (
    <div className="card p-4" data-testid="order-card">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">
            #{order.order_id}
          </p>
          <p className="mt-0.5 text-xs" style={{ color: "var(--muted-foreground)" }}>
            {formatDateTime(order.created_at)}
          </p>
        </div>
        <StatusBadge status={order.status} />
      </div>

      <div className="mt-2 flex items-center justify-between" style={{ borderTop: "1px solid var(--border)", paddingTop: "10px", marginTop: "10px" }}>
        <p className="text-sm font-semibold">
          {formatVND(order.total_amount)}
        </p>
        <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
          {order.items_count} sản phẩm
        </p>
      </div>

      {canConfirm && (
        <button
          onClick={() => onConfirmShipment(order.id)}
          disabled={confirming}
          className="mt-3 w-full rounded-xl px-3 py-2.5 text-sm font-semibold text-white transition-opacity disabled:opacity-50"
          style={{ background: "var(--brand-gradient)" }}
          data-testid="confirm-shipment-btn"
        >
          {confirming ? "Đang xử lý..." : "Xác nhận giao hàng"}
        </button>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, { bg: string; color: string }> = {
    AWAITING_SHIPMENT:   { bg: "#f59e0b20", color: "#f59e0b" },
    AWAITING_COLLECTION: { bg: "#06b6d420", color: "#06b6d4" },
    IN_TRANSIT:          { bg: "#8b5cf620", color: "#a78bfa" },
    DELIVERED:           { bg: "#10b98120", color: "#10b981" },
    CANCELLED:           { bg: "#ef444420", color: "#ef4444" },
  };

  const labels: Record<string, string> = {
    AWAITING_SHIPMENT: "Chờ giao",
    AWAITING_COLLECTION: "Chờ lấy hàng",
    IN_TRANSIT: "Đang giao",
    DELIVERED: "Đã giao",
    CANCELLED: "Đã huỷ",
  };

  const style = styles[status] ?? { bg: "var(--muted)", color: "var(--muted-foreground)" };

  return (
    <span
      className="badge"
      style={{ background: style.bg, color: style.color }}
    >
      {labels[status] || status}
    </span>
  );
}
