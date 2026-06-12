"use client";

import type { RecentProgressItem } from "@/lib/operations/recent-progress";

export function RecentProgressCard({ items }: { items: RecentProgressItem[] }) {
  if (items.length === 0) {
    return (
      <section className="card p-4" data-testid="recent-progress-card">
        <h2 className="text-base font-bold" style={{ color: "var(--foreground)" }}>
          Tiến độ gần đây
        </h2>
        <p className="text-muted mt-2 text-sm">Chưa có báo cáo tuần — phê duyệt đề xuất để bắt đầu theo dõi.</p>
      </section>
    );
  }

  return (
    <section className="space-y-3" data-testid="recent-progress-card">
      <h2 className="text-base font-bold" style={{ color: "var(--foreground)" }}>
        Tiến độ gần đây
      </h2>

      <div className="space-y-3">
        {items.map((item) => (
          <article
            key={item.id}
            className="card p-4"
            data-testid="recent-progress-item"
            data-workflow-id={item.id}
          >
            <p className="text-sm font-semibold">{item.title}</p>
            <dl className="mt-3 space-y-2 text-sm">
              <div>
                <dt className="text-muted text-xs font-medium uppercase">Thay đổi gì</dt>
                <dd className="mt-0.5">{item.whatChanged}</dd>
              </div>
              <div>
                <dt className="text-muted text-xs font-medium uppercase">Vì sao</dt>
                <dd className="mt-0.5">{item.whyChanged}</dd>
              </div>
              <div>
                <dt className="text-muted text-xs font-medium uppercase">Kết quả</dt>
                <dd className="mt-0.5">{item.resultSummary}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
    </section>
  );
}
