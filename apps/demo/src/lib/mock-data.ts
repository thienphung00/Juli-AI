export interface HomeDestinationFixture {
  description: string;
  eyebrow: string;
  href: "/decisions" | "/analytics";
  icon: string;
  label: "Quyết định" | "Phân tích";
}

export interface DemoSnapshotFixture {
  generatedAt: string;
  mode: "mock";
  shopName: string;
}

const homeDestination = { href: "/", label: "Trang chủ", icon: "⌂" } as const;
const decisionsDestination = {
  href: "/decisions",
  label: "Quyết định",
  icon: "✓",
} as const;
const analyticsDestination = {
  href: "/analytics",
  label: "Phân tích",
  icon: "↗",
} as const;
const settingsDestination = {
  href: "/settings",
  label: "Cài đặt",
  icon: "⚙",
} as const;

export const demoDestinations = [
  homeDestination,
  decisionsDestination,
  analyticsDestination,
  settingsDestination,
] as const;

export const homeDestinations = [
  {
    ...decisionsDestination,
    eyebrow: "Bạn là người quyết định",
    description:
      "Xem các đề xuất rõ ràng và theo dõi công việc bạn đã phê duyệt.",
  },
  {
    ...analyticsDestination,
    eyebrow: "Hiểu điều đang diễn ra",
    description:
      "Khám phá KPI, xu hướng, so sánh và dự báo của shop tại một nơi.",
  },
] as const satisfies readonly HomeDestinationFixture[];

export const demoSnapshot = {
  generatedAt: "2026-07-15T08:00:00+07:00",
  mode: "mock",
  shopName: "Juli Demo Shop",
} as const satisfies DemoSnapshotFixture;
