"use client";

import type { MockTask } from "@/lib/mock-data/seller-personas/schemas";
import { formatVND } from "@/lib/format";
import {
  assertEvidenceHasNoRawPii,
  resolveEvidence,
  type ResolvedEvidence,
} from "@/lib/workflows/leakage/resolve-evidence";
import type { SellerPersona } from "@/lib/mock-data/seller-personas/schemas";

function EvidenceRows({ evidence }: { evidence: ResolvedEvidence }) {
  assertEvidenceHasNoRawPii(evidence);

  const hasRows =
    evidence.orders.length > 0 ||
    evidence.returns.length > 0 ||
    evidence.affiliate_events.length > 0 ||
    evidence.profile_metrics.length > 0;

  if (!hasRows) {
    return (
      <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
        Không có bằng chứng chi tiết cho nhiệm vụ này.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {evidence.returns.length > 0 && (
        <section data-testid="evidence-section-returns">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Đơn trả hàng
          </h4>
          <ul className="mt-2 space-y-2">
            {evidence.returns.map((ret) => (
              <li
                key={ret.id}
                className="rounded-lg border px-3 py-2 text-sm"
                style={{ borderColor: "var(--border)" }}
                data-testid="evidence-return-row"
              >
                <p className="font-medium">{ret.product_title}</p>
                <p className="text-muted mt-1 text-xs">Mã đơn: {ret.order_id}</p>
                <p className="text-muted text-xs">Mã người mua: {ret.buyer_id}</p>
                <p className="mt-1">{ret.reason}</p>
                <p className="mt-1 text-xs font-semibold" style={{ color: "#f87171" }}>
                  Hoàn: {formatVND(ret.refund_vnd)}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {evidence.orders.length > 0 && (
        <section data-testid="evidence-section-orders">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Đơn hàng liên quan
          </h4>
          <ul className="mt-2 space-y-2">
            {evidence.orders.map((order) => (
              <li
                key={order.id}
                className="rounded-lg border px-3 py-2 text-sm"
                style={{ borderColor: "var(--border)" }}
                data-testid="evidence-order-row"
              >
                <p className="font-medium">{order.product_title}</p>
                <p className="text-muted mt-1 text-xs">Mã đơn: {order.id}</p>
                <p className="text-muted text-xs">Mã người mua: {order.buyer_id}</p>
                <p className="mt-1 text-xs">
                  Trạng thái: {order.status} · {formatVND(order.total_vnd)}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {evidence.affiliate_events.length > 0 && (
        <section data-testid="evidence-section-affiliate">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Sự kiện affiliate
          </h4>
          <ul className="mt-2 space-y-2">
            {evidence.affiliate_events.map((event) => (
              <li
                key={event.id}
                className="rounded-lg border px-3 py-2 text-sm"
                style={{ borderColor: "var(--border)" }}
                data-testid="evidence-affiliate-row"
              >
                <p className="font-medium">Affiliate: {event.affiliate_id}</p>
                <p className="text-muted mt-1 text-xs">Mã đơn: {event.order_id}</p>
                <p className="text-muted text-xs">Loại: {event.event_type}</p>
                {event.cancellation_reason && (
                  <p className="mt-1">{event.cancellation_reason}</p>
                )}
                <p className="mt-1 text-xs">GMV: {formatVND(event.gmv_vnd)}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {evidence.profile_metrics.length > 0 && (
        <section data-testid="evidence-section-profile">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">
            Chỉ số shop
          </h4>
          <ul className="mt-2 space-y-1">
            {evidence.profile_metrics.map((metric) => (
              <li key={metric.key} className="text-sm" data-testid="evidence-profile-row">
                <span className="font-medium">{metric.key}</span>: {metric.value}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export function EvidenceDrawer({
  task,
  persona,
  onClose,
}: {
  task: MockTask;
  persona: SellerPersona;
  onClose: () => void;
}) {
  const evidence = resolveEvidence(persona, task.evidence_refs);

  return (
    <div
      className="rounded-xl border p-4"
      style={{ borderColor: "var(--border)", background: "var(--card)" }}
      data-testid="evidence-drawer"
      role="region"
      aria-label="Bằng chứng rò rỉ doanh thu"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-muted text-xs font-medium uppercase tracking-wide">
            Bằng chứng
          </p>
          <h3 className="mt-1 text-sm font-semibold">{task.title}</h3>
        </div>
        <button
          type="button"
          className="rounded-lg px-2 py-1 text-xs font-semibold"
          style={{ color: "var(--muted-foreground)" }}
          onClick={onClose}
          data-testid="evidence-drawer-close"
        >
          Đóng
        </button>
      </div>

      <div className="mt-4">
        <EvidenceRows evidence={evidence} />
      </div>
    </div>
  );
}
