"use client";

import { formatNumber, formatVND } from "@/lib/format";
import type { AffiliateOperationData } from "@/lib/mock-data/operation-affiliate";
import type { SellerOperationData } from "@/lib/mock-data/operation-seller";

function formatPct(value: number): string {
  return `${(value * 100).toFixed(1).replace(".", ",")}%`;
}

const ORDER_STATUS_LABELS: Record<string, string> = {
  shipping: "Đang giao",
  delivered: "Đã giao",
  returned: "Hoàn trả",
  processing: "Đang xử lý",
};

const RETURN_STATUS_LABELS: Record<string, string> = {
  pending_review: "Chờ duyệt",
  approved: "Đã duyệt",
  rejected: "Từ chối",
};

export function SellerProductsPanel({ data }: { data: SellerOperationData }) {
  return (
    <div className="space-y-3" data-testid="operation-panel-products">
      <div className="card p-4">
        <h2 className="text-muted text-sm font-medium">GMV tháng này</h2>
        <p className="mt-1 text-xl font-bold" style={{ color: "var(--primary)" }}>
          {formatVND(data.products_summary.gmv_this_month_vnd)}
        </p>
        <p className="text-muted mt-1 text-xs">
          {data.products_summary.active_products}/{data.products_summary.total_products} sản phẩm
          đang bán · {data.products_summary.low_stock_count} sắp hết hàng
        </p>
      </div>

      <ul className="space-y-2">
        {data.products.map((product) => (
          <li key={product.id} className="card p-4">
            <p className="text-sm font-semibold">{product.name}</p>
            <p className="text-muted mt-1 text-sm">
              GMV {formatVND(product.gmv_this_month_vnd)} · ROI {product.roi_pct}% · Tồn{" "}
              {formatNumber(product.stock_units)} units
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SellerCreatorsPanel({ data }: { data: SellerOperationData }) {
  return (
    <div className="space-y-3" data-testid="operation-panel-creators">
      <div className="card p-4">
        <h2 className="text-muted text-sm font-medium">Creator đang hoạt động</h2>
        <p className="mt-1 text-xl font-bold" style={{ color: "var(--primary)" }}>
          {formatNumber(data.creators_summary.active_creators)}
        </p>
        <p className="text-muted mt-1 text-xs">
          GMV {formatVND(data.creators_summary.gmv_this_month_vnd)} · Tỷ lệ hoàn trung bình{" "}
          {formatPct(data.creators_summary.avg_refund_rate)}
        </p>
      </div>

      <ul className="space-y-2">
        {data.creators.map((creator) => (
          <li key={creator.id} className="card p-4">
            <p className="text-sm font-semibold">{creator.handle}</p>
            <p className="text-muted mt-1 text-sm">
              GMV {formatVND(creator.gmv_this_month_vnd)}
              {creator.conversion_rate != null &&
                ` · Chuyển đổi ${formatPct(creator.conversion_rate)}`}
              {creator.refund_rate != null && ` · Hoàn ${formatPct(creator.refund_rate)}`}
            </p>
            {creator.status === "pending_approval" && (
              <span className="mt-2 inline-block rounded-full px-2 py-0.5 text-xs font-medium" style={{ background: "var(--muted)" }}>
                Chờ duyệt
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SellerOrdersPanel({ data }: { data: SellerOperationData }) {
  return (
    <div className="space-y-3" data-testid="operation-panel-orders">
      <div className="grid grid-cols-2 gap-2">
        <div className="card p-3">
          <p className="text-muted text-xs">Hôm nay</p>
          <p className="text-lg font-bold">{formatNumber(data.orders_summary.total_today)}</p>
        </div>
        <div className="card p-3">
          <p className="text-muted text-xs">Đang xử lý</p>
          <p className="text-lg font-bold">{formatNumber(data.orders_summary.processing)}</p>
        </div>
      </div>

      <ul className="space-y-2">
        {data.orders.map((order) => (
          <li key={order.id} className="card p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-sm font-semibold">{order.product_name}</p>
                <p className="text-muted text-xs">{order.id}</p>
              </div>
              <span className="text-xs font-medium">{ORDER_STATUS_LABELS[order.status]}</span>
            </div>
            <p className="text-muted mt-1 text-sm">
              SL {order.quantity} · {formatVND(order.total_vnd)}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function SellerReturnsPanel({ data }: { data: SellerOperationData }) {
  return (
    <div className="space-y-3" data-testid="operation-panel-returns">
      <ul className="space-y-2">
        {data.returns.map((item) => (
          <li key={item.id} className="card p-4">
            <p className="text-sm font-semibold">{item.product_name}</p>
            <p className="text-muted mt-1 text-sm">
              {item.creator_handle} · {item.reason}
            </p>
            <p className="mt-1 text-sm">
              Tác động GMV {formatVND(item.gmv_impact_vnd)} ·{" "}
              {RETURN_STATUS_LABELS[item.status]}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AffiliateProductsPanel({ data }: { data: AffiliateOperationData }) {
  return (
    <div className="space-y-3" data-testid="operation-panel-products">
      <div className="card p-4">
        <h2 className="text-muted text-sm font-medium">Hoa hồng tháng này</h2>
        <p className="mt-1 text-xl font-bold" style={{ color: "var(--primary)" }}>
          {formatVND(data.products_summary.commission_this_month_vnd)}
        </p>
        <p className="mt-1 text-xs font-medium" style={{ color: "#10b981" }}>
          ▲ +{data.products_summary.commission_mom_pct}% so với tháng trước
        </p>
        <p className="text-muted mt-1 text-xs">
          {data.products_summary.active_partnerships} đối tác đang hoạt động
        </p>
      </div>

      <ul className="space-y-2">
        {data.products.map((product) => (
          <li key={product.id} className="card p-4">
            <p className="text-sm font-semibold">{product.name}</p>
            <p className="text-muted mt-1 text-sm">
              {formatNumber(product.orders_this_month)} đơn · Hoa hồng {product.commission_pct}%
              · {formatVND(product.commission_vnd)}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AffiliateOrdersPanel({ data }: { data: AffiliateOperationData }) {
  return (
    <div className="space-y-3" data-testid="operation-panel-orders">
      <ul className="space-y-2">
        {data.orders.map((order) => (
          <li key={order.id} className="card p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-sm font-semibold">{order.product_name}</p>
                <p className="text-muted text-xs">{order.id}</p>
              </div>
              <span className="text-xs font-medium">{ORDER_STATUS_LABELS[order.status]}</span>
            </div>
            <p className="text-muted mt-1 text-sm">
              SL {order.quantity} · {formatVND(order.total_vnd)}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AffiliateReturnsPanel({ data }: { data: AffiliateOperationData }) {
  return (
    <div className="space-y-3" data-testid="operation-panel-returns">
      <ul className="space-y-2">
        {data.returns.map((item) => (
          <li key={item.id} className="card p-4">
            <p className="text-sm font-semibold">{item.product_name}</p>
            <p className="text-muted mt-1 text-sm">
              Tác động hoa hồng {formatVND(item.commission_impact_vnd)} ·{" "}
              {RETURN_STATUS_LABELS[item.status]}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}
