"use client";

export type DecisionsSubTab = "recommended" | "in_progress" | "templates";

const DECISIONS_SUB_TABS: { id: DecisionsSubTab; label: string }[] = [
  { id: "recommended", label: "Đề xuất" },
  { id: "in_progress", label: "Đang thực hiện" },
  { id: "templates", label: "Mẫu quy trình" },
];

export function DecisionsSubTabs({
  activeTab,
  onTabChange,
}: {
  activeTab: DecisionsSubTab;
  onTabChange: (tab: DecisionsSubTab) => void;
}) {
  return (
    <div
      className="mb-4 flex gap-1 overflow-x-auto pb-1"
      role="tablist"
      aria-label="Quyết định"
      data-testid="decisions-sub-tabs"
    >
      {DECISIONS_SUB_TABS.map((tab) => {
        const isActive = activeTab === tab.id;

        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            data-testid={`decisions-sub-tab-${tab.id}`}
            onClick={() => onTabChange(tab.id)}
            className={`shrink-0 rounded-full px-3 py-2 text-xs font-semibold sm:text-sm${
              isActive ? " btn-primary" : " btn-secondary"
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
