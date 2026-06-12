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
      {DECISIONS_SUB_TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          data-testid={`decisions-sub-tab-${tab.id}`}
          onClick={() => onTabChange(tab.id)}
          className="shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-colors"
          style={{
            background: activeTab === tab.id ? "var(--primary)" : "var(--muted)",
            color:
              activeTab === tab.id ? "var(--primary-foreground, #fff)" : "var(--foreground)",
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
