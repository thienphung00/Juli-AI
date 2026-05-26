"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Order, type OrdersResponse, ApiError } from "@/lib/api-client";
import { formatVND, formatDateTime } from "@/lib/format";
import { NavBar } from "./NavBar";

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
    <div className="min-h-screen pb-20">
      <header className="sticky top-0 z-10 border-b bg-white px-4 py-3">
        <div className="mx-auto max-w-lg">
          <h1 className="text-lg font-bold">Đơn hàng</h1>
        </div>
      </header>

      <main className="mx-auto max-w-lg px-4 pt-4">
        {/* Filters */}
        <div className="space-y-3 pb-4" data-testid="order-filters">
          <select
            aria-label="Lọc theo trạng thái"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
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
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
            <input
              type="date"
              aria-label="Đến ngày"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
        </div>

        {error && (
          <p role="alert" className="mb-4 text-sm text-red-600">
            {error}
          </p>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
          </div>
        ) : orders.length === 0 ? (
          <div className="py-12 text-center" data-testid="orders-empty">
            <p className="text-lg text-gray-400">Chưa có đơn hàng nào</p>
            <p className="mt-1 text-sm text-gray-300">
              Đơn hàng sẽ hiển thị khi có dữ liệu từ TikTok Shop
            </p>
          </div>
        ) : (
          <div className="space-y-3" data-testid="orders-list">
            <p className="text-xs text-gray-500">
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
      </main>

      <NavBar />
    </div>
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
    <div className="rounded-xl bg-white p-4 shadow-sm" data-testid="order-card">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">
            #{order.order_id}
          </p>
          <p className="mt-0.5 text-xs text-gray-500">
            {formatDateTime(order.created_at)}
          </p>
        </div>
        <StatusBadge status={order.status} />
      </div>

      <div className="mt-2 flex items-center justify-between">
        <p className="text-sm font-semibold">
          {formatVND(order.total_amount)}
        </p>
        <p className="text-xs text-gray-400">
          {order.items_count} sản phẩm
        </p>
      </div>

      {canConfirm && (
        <button
          onClick={() => onConfirmShipment(order.id)}
          disabled={confirming}
          className="mt-3 w-full rounded-lg bg-primary-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
          data-testid="confirm-shipment-btn"
        >
          {confirming ? "Đang xử lý..." : "Xác nhận giao hàng"}
        </button>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    AWAITING_SHIPMENT: "bg-yellow-100 text-yellow-800",
    AWAITING_COLLECTION: "bg-blue-100 text-blue-800",
    IN_TRANSIT: "bg-indigo-100 text-indigo-800",
    DELIVERED: "bg-green-100 text-green-800",
    CANCELLED: "bg-red-100 text-red-800",
  };

  const labels: Record<string, string> = {
    AWAITING_SHIPMENT: "Chờ giao",
    AWAITING_COLLECTION: "Chờ lấy hàng",
    IN_TRANSIT: "Đang giao",
    DELIVERED: "Đã giao",
    CANCELLED: "Đã huỷ",
  };

  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
        styles[status] || "bg-gray-100 text-gray-800"
      }`}
    >
      {labels[status] || status}
    </span>
  );
}
