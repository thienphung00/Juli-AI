import type { TaskSeverity } from "@/lib/mock-data/seller-personas/schemas";

const SEVERITY_LABELS: Record<TaskSeverity, string> = {
  high: "Ưu tiên cao",
  medium: "Trung bình",
  low: "Thấp",
  info: "Thông tin",
};

const SEVERITY_STYLES: Record<TaskSeverity, { background: string; color: string }> = {
  high: { background: "#ef444420", color: "#f87171" },
  medium: { background: "#f59e0b20", color: "#fbbf24" },
  low: { background: "#3b82f620", color: "#60a5fa" },
  info: { background: "#71717a20", color: "#a1a1aa" },
};

export function taskSeverityLabel(severity: TaskSeverity): string {
  return SEVERITY_LABELS[severity];
}

export function taskSeverityStyle(severity: TaskSeverity): {
  background: string;
  color: string;
} {
  return SEVERITY_STYLES[severity];
}
