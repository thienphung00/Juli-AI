"use client";

import type { JuliConversationSummary } from "@juli/contracts";

import { formatHistoryTime } from "../../lib/juli/format";

/** U8: one "Lịch sử" list. Side panel on desktop, bottom sheet on mobile (CSS only). */
export function HistoryPanel({
  items,
  activeId,
  onOpen,
  onNew,
  onClose,
}: {
  readonly items: readonly JuliConversationSummary[];
  readonly activeId: string | null;
  readonly onOpen: (id: string) => void;
  readonly onNew: () => void;
  readonly onClose: () => void;
}) {
  const sorted = [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return (
    <>
      <div className="juli-scrim" onClick={onClose} aria-hidden="true" />
      <aside className="juli-history" aria-label="Lịch sử">
        <div className="juli-history__grab" aria-hidden="true" />
        <div className="juli-history__top">
          <button type="button" className="juli-btn juli-btn--primary juli-history__new" onClick={onNew}>
            Cuộc trò chuyện mới
          </button>
          <button type="button" className="juli-btn juli-history__close" onClick={onClose} aria-label="Đóng lịch sử">
            Đóng
          </button>
        </div>
        <ul className="juli-history__list">
          {sorted.map((c) => (
            <li key={c.id}>
              <button
                type="button"
                className="juli-history__item"
                aria-current={c.id === activeId ? "true" : undefined}
                onClick={() => onOpen(c.id)}
              >
                <span>{c.title}</span>
                <small>{formatHistoryTime(c.updated_at)}</small>
              </button>
            </li>
          ))}
        </ul>
      </aside>
    </>
  );
}
